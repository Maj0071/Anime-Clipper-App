import os
import subprocess
import json
import numpy as np
import cv2
import whisper
from typing import List, Dict, Tuple
from celery import Task
from sqlalchemy.orm import Session

from app.workers.celery_app import celery_app
from app.database import SessionLocal
from app.models import Job, Video, Transcript, Candidate
from app.services.s3_service import download_from_s3, upload_to_s3


class VideoAnalyzer:
    """Main video analysis pipeline"""
    
    def __init__(self, video_path: str, config: Dict):
        self.video_path = video_path
        self.config = config
        self.duration = None
        self.fps = None
        
    def get_video_info(self) -> Dict:
        """Extract video metadata using FFprobe"""
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', self.video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        info = json.loads(result.stdout)
        
        video_stream = next(s for s in info['streams'] if s['codec_type'] == 'video')
        self.duration = float(info['format']['duration'])
        self.fps = eval(video_stream['r_frame_rate'])  # e.g., "24/1"
        
        return {
            'duration': self.duration,
            'resolution': f"{video_stream['width']}x{video_stream['height']}",
            'fps': self.fps
        }
    
    def extract_audio(self, output_path: str) -> str:
        """Extract audio as 16kHz mono WAV for Whisper"""
        cmd = [
            'ffmpeg', '-i', self.video_path, '-vn',
            '-ar', '16000', '-ac', '1', '-y', output_path
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        return output_path
    
    def transcribe_audio(self, audio_path: str) -> Dict:
        """Run Whisper ASR with word-level timestamps"""
        model = whisper.load_model(self.config.get('whisper_model', 'base'))
        result = model.transcribe(
            audio_path,
            language=self.config.get('language', None),  # None = auto-detect
            word_timestamps=True
        )
        
        # Extract word-level data
        words = []
        for segment in result['segments']:
            for word_data in segment.get('words', []):
                words.append({
                    'word': word_data['word'].strip(),
                    'start': word_data['start'],
                    'end': word_data['end'],
                    'confidence': word_data.get('probability', 1.0)
                })
        
        return {
            'language': result['language'],
            'words': words,
            'text': result['text']
        }
    
    def detect_scenes(self, threshold: float = 0.3) -> List[float]:
        """Detect scene boundaries using histogram differences"""
        cap = cv2.VideoCapture(self.video_path)
        scene_boundaries = [0.0]
        prev_hist = None
        frame_count = 0
        sample_rate = 3  # Check every 3rd frame
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            
            if frame_count % sample_rate == 0:
                # Downsample and convert to HSV
                small = cv2.resize(frame, (160, 90))
                hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
                hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
                hist = cv2.normalize(hist, hist).flatten()
                
                if prev_hist is not None:
                    # Compare histograms
                    diff = np.sum(np.abs(hist - prev_hist))
                    if diff > threshold:
                        timestamp = frame_count / self.fps
                        scene_boundaries.append(timestamp)
                
                prev_hist = hist
            
            frame_count += 1
        
        cap.release()
        scene_boundaries.append(self.duration)
        return scene_boundaries
    
    def compute_motion_scores(self, sample_rate: int = 5) -> np.ndarray:
        """Compute motion intensity per second using frame differencing"""
        cap = cv2.VideoCapture(self.video_path)
        motion_scores = []
        prev_gray = None
        frame_count = 0
        current_second = 0
        second_diffs = []
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            
            if frame_count % sample_rate == 0:
                gray = cv2.cvtColor(cv2.resize(frame, (320, 180)), cv2.COLOR_BGR2GRAY)
                
                if prev_gray is not None:
                    diff = cv2.absdiff(gray, prev_gray)
                    motion = np.mean(diff)
                    
                    second = int(frame_count / self.fps)
                    if second > current_second:
                        # Store average motion for previous second
                        motion_scores.append(np.mean(second_diffs) if second_diffs else 0)
                        second_diffs = []
                        current_second = second
                    
                    second_diffs.append(motion)
                
                prev_gray = gray
            
            frame_count += 1
        
        cap.release()
        
        # Add final second
        if second_diffs:
            motion_scores.append(np.mean(second_diffs))
        
        # Normalize to 0-1
        motion_array = np.array(motion_scores)
        if motion_array.max() > 0:
            motion_array = motion_array / motion_array.max()
        
        return motion_array
    
    def compute_audio_peaks(self, audio_path: str) -> np.ndarray:
        """Detect audio energy peaks per second"""
        # Use FFmpeg to get audio RMS per second
        cmd = [
            'ffmpeg', '-i', audio_path, '-af',
            'astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-',
            '-f', 'null', '-'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, stderr=subprocess.STDOUT)
        
        # Parse RMS values (simplified - in production, use more robust parsing)
        rms_values = []
        for line in result.stdout.split('\n'):
            if 'lavfi.astats.Overall.RMS_level' in line:
                try:
                    value = float(line.split('=')[-1])
                    rms_values.append(abs(value))  # Convert dB to positive
                except:
                    continue
        
        # Group by second
        audio_scores = []
        fps = len(rms_values) / self.duration if self.duration > 0 else 1
        for i in range(int(self.duration)):
            start_idx = int(i * fps)
            end_idx = int((i + 1) * fps)
            second_values = rms_values[start_idx:end_idx]
            audio_scores.append(np.mean(second_values) if second_values else 0)
        
        # Normalize
        audio_array = np.array(audio_scores)
        if audio_array.max() > 0:
            audio_array = audio_array / audio_array.max()
        
        return audio_array


def detect_hook_phrases(words: List[Dict], start_s: float, end_s: float) -> float:
    """Score speech hooks in the first 2-3 seconds"""
    hook_words = {'wait', 'hey', 'no', 'stop', 'what', 'now', 'look', 'watch'}
    question_words = {'who', 'what', 'where', 'when', 'why', 'how'}
    
    score = 0.0
    early_window = start_s + 2.5  # First 2.5 seconds
    
    for word in words:
        if word['start'] < start_s or word['start'] > end_s:
            continue
        
        word_lower = word['word'].lower().strip('.,!?')
        
        # Hook words in first 2.5s
        if word['start'] <= early_window:
            if word_lower in hook_words:
                score += 0.5
            if word_lower in question_words:
                score += 0.3
            if word['word'].endswith('!'):
                score += 0.2
    
    return min(score, 1.0)


def score_candidate(
    start_s: float,
    end_s: float,
    transcript_words: List[Dict],
    motion_scores: np.ndarray,
    audio_scores: np.ndarray,
    keywords: List[str],
    existing_candidates: List[Tuple[float, float]],
    weights: Dict[str, float]
) -> Tuple[float, Dict]:
    """Score a candidate clip segment"""
    
    # 1. Speech hook score
    speech_hook = detect_hook_phrases(transcript_words, start_s, end_s)
    
    # 2. Motion score (average in window)
    start_idx = int(start_s)
    end_idx = int(end_s)
    motion_score = float(np.mean(motion_scores[start_idx:end_idx])) if start_idx < len(motion_scores) else 0
    
    # 3. Audio peak score
    audio_score = float(np.mean(audio_scores[start_idx:end_idx])) if start_idx < len(audio_scores) else 0
    
    # 4. Keyword match
    segment_words = [w['word'].lower() for w in transcript_words if start_s <= w['start'] <= end_s]
    keyword_score = sum(1 for kw in keywords if kw.lower() in ' '.join(segment_words))
    keyword_score = min(keyword_score / max(len(keywords), 1), 1.0)
    
    # 5. Scene freshness (penalize overlap)
    overlap_penalty = 0.0
    for ex_start, ex_end in existing_candidates:
        overlap = min(end_s, ex_end) - max(start_s, ex_start)
        if overlap > 0:
            overlap_penalty += overlap / (end_s - start_s)
    freshness = max(0, 1.0 - overlap_penalty)
    
    # Weighted sum
    total_score = (
        weights.get('speech_hook', 0.30) * speech_hook +
        weights.get('motion', 0.25) * motion_score +
        weights.get('audio_peak', 0.20) * audio_score +
        weights.get('keyword_match', 0.15) * keyword_score +
        weights.get('scene_freshness', 0.10) * freshness
    )
    
    features = {
        'speech_hook': speech_hook,
        'motion': motion_score,
        'audio_peak': audio_score,
        'keyword_match': keyword_score,
        'scene_freshness': freshness
    }
    
    return total_score, features


@celery_app.task(bind=True)
def analyze_video_task(self: Task, job_id: str, video_id: str, config: Dict):
    """
    Main analysis task:
    1. Download video from S3
    2. Extract audio and run Whisper
    3. Detect scenes, motion, audio peaks
    4. Generate and score candidates
    5. Create thumbnails
    6. Store results in DB
    """
    db = SessionLocal()
    
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        video = db.query(Video).filter(Video.id == video_id).first()
        
        if not job or not video:
            raise ValueError("Job or Video not found")
        
        # Update job status
        job.status = 'processing'
        job.progress = 0
        db.commit()
        
        # Download video
        self.update_state(state='PROGRESS', meta={'step': 'downloading', 'progress': 5})
        video_path = f"/tmp/videos/{video_id}.mp4"
        download_from_s3(video.src_url, video_path)
        
        # Initialize analyzer
        analyzer = VideoAnalyzer(video_path, config)
        
        # Get video info
        self.update_state(state='PROGRESS', meta={'step': 'analyzing_metadata', 'progress': 10})
        video_info = analyzer.get_video_info()
        video.duration = video_info['duration']
        video.resolution = video_info['resolution']
        db.commit()
        
        # Extract and transcribe audio
        self.update_state(state='PROGRESS', meta={'step': 'transcribing', 'progress': 20})
        audio_path = f"/tmp/videos/{video_id}.wav"
        analyzer.extract_audio(audio_path)
        transcript_data = analyzer.transcribe_audio(audio_path)
        
        # Store transcript
        transcript = Transcript(
            video_id=video_id,
            lang=transcript_data['language'],
            words=transcript_data['words']
        )
        db.add(transcript)
        db.commit()
        
        # Scene detection
        self.update_state(state='PROGRESS', meta={'step': 'detecting_scenes', 'progress': 40})
        scene_boundaries = analyzer.detect_scenes()
        
        # Motion analysis
        self.update_state(state='PROGRESS', meta={'step': 'analyzing_motion', 'progress': 55})
        motion_scores = analyzer.compute_motion_scores()
        
        # Audio peaks
        self.update_state(state='PROGRESS', meta={'step': 'analyzing_audio', 'progress': 70})
        audio_scores = analyzer.compute_audio_peaks(audio_path)
        
        # Generate candidates
        self.update_state(state='PROGRESS', meta={'step': 'generating_candidates', 'progress': 80})
        min_duration = config.get('clip_min_s', 7)
        max_duration = config.get('clip_max_s', 15)
        target_duration = config.get('target_s', 10)
        keywords = config.get('keywords', [])
        weights = config.get('weights', {})
        
        candidates = []
        existing_segments = []
        
        # Generate candidates around scene boundaries and speech onsets
        for i in range(len(scene_boundaries) - 1):
            scene_start = scene_boundaries[i]
            scene_end = scene_boundaries[i + 1]
            
            # Try different clip lengths around this scene
            for duration in [target_duration, min_duration, max_duration]:
                if scene_end - scene_start < duration:
                    continue
                
                # Clip starting at scene boundary
                start_s = scene_start
                end_s = min(start_s + duration, scene_end, analyzer.duration)
                
                if end_s - start_s >= min_duration:
                    score, features = score_candidate(
                        start_s, end_s, transcript_data['words'],
                        motion_scores, audio_scores, keywords,
                        existing_segments, weights
                    )
                    
                    candidates.append({
                        'start_s': start_s,
                        'end_s': end_s,
                        'score': score,
                        'features': features
                    })
                    existing_segments.append((start_s, end_s))
        
        # Sort by score and keep top candidates
        candidates.sort(key=lambda x: x['score'], reverse=True)
        top_candidates = candidates[:config.get('max_candidates', 20)]
        
        # Create thumbnails and store candidates
        self.update_state(state='PROGRESS', meta={'step': 'creating_thumbnails', 'progress': 90})
        for idx, cand in enumerate(top_candidates):
            # Extract thumbnail at midpoint
            thumb_time = (cand['start_s'] + cand['end_s']) / 2
            thumb_path = f"/tmp/videos/{video_id}_thumb_{idx}.jpg"
            
            cmd = [
                'ffmpeg', '-ss', str(thumb_time), '-i', video_path,
                '-vframes', '1', '-q:v', '2', '-y', thumb_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            
            # Upload thumbnail
            thumb_url = upload_to_s3(thumb_path, f"thumbnails/{video_id}_{idx}.jpg")
            
            # Store candidate
            candidate = Candidate(
                video_id=video_id,
                start_s=cand['start_s'],
                end_s=cand['end_s'],
                score=cand['score'],
                features=cand['features'],
                thumb_url=thumb_url
            )
            db.add(candidate)
        
        db.commit()
        
        # Complete job
        job.status = 'completed'
        job.progress = 100
        job.logs = {'candidates_generated': len(top_candidates)}
        db.commit()
        
        # Cleanup
        os.remove(video_path)
        os.remove(audio_path)
        
        return {'status': 'completed', 'candidates': len(top_candidates)}
        
    except Exception as e:
        job.status = 'failed'
        job.logs = {'error': str(e)}
        db.commit()
        raise
    finally:
        db.close()