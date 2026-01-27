import os
import subprocess
import json
import random
from typing import List, Dict
from celery import Task
from sqlalchemy.orm import Session

from app.workers.celery_app import celery_app
from app.database import SessionLocal
from app.models import Render, Candidate, Video, Transcript
from app.services.s3_service import download_from_s3, upload_to_s3


# Relatable captions that resonate with people worldwide
RELATABLE_CAPTIONS = [
    "When you finally understand...",
    "This hit different",
    "No one talks about this",
    "POV: You realized too late",
    "Why is this so accurate",
    "The moment everything changed",
    "When it all makes sense",
    "This is the sign you needed",
    "Some things never change",
    "Real ones understand",
    "That feeling when...",
    "We've all been here",
    "Story of my life",
    "When you least expect it",
    "The truth nobody tells you",
    "This hits home",
    "Caught in 4K",
    "Main character moment",
    "Plot twist incoming",
    "When the beat drops",
    "Energy check",
    "Mood forever",
    "Living rent free in my head",
    "This changed everything",
    "Unexpected but perfect",
    "The comeback is always stronger",
    "Built different",
    "Trust the process",
    "Vibes only",
    "When you know, you know",
]


def get_random_caption() -> str:
    """Get a random relatable caption"""
    return random.choice(RELATABLE_CAPTIONS)


class TemplateRenderer:
    """Handles different caption templates and styling for TikTok/Instagram ready clips"""

    def __init__(self, video_path: str, output_path: str, config: Dict):
        self.video_path = video_path
        self.output_path = output_path
        self.config = config
        self.watermark = config.get('watermark', '')
        self.loudness = config.get('loudness', '-14')
        # Auto-editing settings for social media
        self.auto_edit = config.get('auto_edit', True)
        self.fade_duration = config.get('fade_duration', 0.3)
        # Use random relatable caption if not provided
        self.hook_text = config.get('hook_text', '') or get_random_caption()
        self.cta_text = config.get('cta_text', '')
    
    def build_ffmpeg_command(
        self,
        start_s: float,
        end_s: float,
        captions: List[Dict],
        template: str,
        aspect: str
    ) -> List[str]:
        """Build FFmpeg command with filters for TikTok/Instagram ready clips"""

        duration = end_s - start_s

        # Get dimensions based on aspect ratio
        if aspect == '9:16':
            width, height = 1080, 1920
        elif aspect == '1:1':
            width, height = 1080, 1080
        else:  # 4:5
            width, height = 1080, 1350

        # Base command
        cmd = [
            'ffmpeg', '-ss', str(start_s), '-i', self.video_path,
            '-t', str(duration)
        ]

        # Build filter complex
        filters = []

        # 1. Video scaling and cropping for aspect ratio
        scale_crop = f'[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}'
        filters.append(scale_crop)

        # 2. Optional subtle zoom (for manga template)
        if template == 'manga':
            filters[-1] += f",zoompan=z='min(zoom+0.0005,1.05)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}"

        # 3. Auto-editing effects for social media readiness
        if self.auto_edit:
            # Fade in at start
            filters[-1] += f',fade=t=in:st=0:d={self.fade_duration}'
            # Fade out at end
            filters[-1] += f',fade=t=out:st={duration - self.fade_duration}:d={self.fade_duration}'

            # Add subtle color enhancement for social media pop
            filters[-1] += ',eq=saturation=1.1:contrast=1.05'

        # 4. Add relatable caption overlay (shows for entire video, TikTok style)
        if self.hook_text:
            # Main caption at top third of screen - visible throughout
            hook_filter = (
                f"drawtext=text='{self._escape_text(self.hook_text)}':"
                f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                f"fontsize=56:fontcolor=white:"
                f"borderw=4:bordercolor=black:"
                f"x=(w-text_w)/2:y=h*0.15:"
                f"shadowcolor=black@0.9:shadowx=3:shadowy=3"
            )
            filters[-1] += f',{hook_filter}'

        # 5. Add CTA overlay at the end (last 2 seconds) if provided
        if self.cta_text:
            cta_filter = (
                f"drawtext=text='{self._escape_text(self.cta_text)}':"
                f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                f"fontsize=40:fontcolor=yellow:"
                f"borderw=3:bordercolor=black:"
                f"x=(w-text_w)/2:y=h-200:"
                f"shadowcolor=black@0.7:shadowx=2:shadowy=2:"
                f"enable='between(t,{max(0, duration - 2)},{duration})'"
            )
            filters[-1] += f',{cta_filter}'

        # 6. Add watermark (positioned to avoid platform UI elements)
        if self.watermark:
            # Position in safe zone (avoid bottom 250px for TikTok UI, avoid top 100px for IG)
            watermark_filter = (
                f"drawtext=text='{self._escape_text(self.watermark)}':"
                f"fontsize=28:fontcolor=white@0.8:"
                f"x=20:y=120:shadowcolor=black@0.6:shadowx=2:shadowy=2"
            )
            filters[-1] += f',{watermark_filter}'

        # 7. Add captions based on template
        caption_filter = self.build_caption_filter(captions, template, aspect, start_s)
        if caption_filter:
            filters[-1] += f',{caption_filter}'

        filters[-1] += '[v]'

        # 8. Audio processing for social media
        audio_filter = (
            f'[0:a]loudnorm=I={self.loudness}:TP=-1:LRA=11,'
            f'aformat=sample_rates=48000'
        )
        if self.auto_edit:
            # Add subtle audio fade in/out
            audio_filter += f',afade=t=in:st=0:d={self.fade_duration}'
            audio_filter += f',afade=t=out:st={duration - self.fade_duration}:d={self.fade_duration}'
        audio_filter += '[a]'
        filters.append(audio_filter)

        # Add filter complex to command
        cmd.extend(['-filter_complex', ';'.join(filters)])

        # Map outputs
        cmd.extend(['-map', '[v]', '-map', '[a]'])

        # Encoding settings optimized for social media upload
        cmd.extend([
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '18',  # Higher quality for social media
            '-profile:v', 'high',
            '-level', '4.0',  # Compatibility with most devices
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',  # Faster playback start
            '-c:a', 'aac',
            '-b:a', '192k',  # Higher audio bitrate for music/voice
            '-ar', '48000',
            '-y',
            self.output_path
        ])

        return cmd

    def _escape_text(self, text: str) -> str:
        """Escape special characters for FFmpeg drawtext filter"""
        return text.replace("'", "\\'").replace(":", "\\:").replace("\\", "\\\\")
    
    def build_caption_filter(
        self,
        captions: List[Dict],
        template: str,
        aspect: str,
        video_start: float
    ) -> str:
        """Build drawtext filter for captions based on template"""
        
        if not captions:
            return ''
        
        # Safe zone calculations (avoid bottom 250px for TikTok UI)
        if aspect == '9:16':
            safe_y = 1920 - 300  # 300px from bottom
            width = 1080
        elif aspect == '1:1':
            safe_y = 1080 - 200
            width = 1080
        else:  # 4:5
            safe_y = 1350 - 250
            width = 1080
        
        if template == 'clean':
            return self._build_clean_captions(captions, safe_y, width, video_start)
        elif template == 'manga':
            return self._build_manga_captions(captions, safe_y, width, video_start)
        elif template == 'impact':
            return self._build_impact_captions(captions, safe_y, width, video_start)
        elif template == 'karaoke':
            return self._build_karaoke_captions(captions, safe_y, width, video_start)
        
        return ''
    
    def _build_clean_captions(self, captions: List[Dict], y: int, width: int, start: float) -> str:
        """Clean subtitle style with outline and shadow"""
        filters = []
        
        for cap in captions:
            # Adjust timing relative to clip start
            enable_start = cap['start'] - start
            enable_end = cap['end'] - start
            
            text = cap['word'].replace("'", "\\'").replace(":", "\\:")
            
            filter_part = (
                f"drawtext=text='{text}':"
                f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                f"fontsize=48:fontcolor=white:"
                f"borderw=3:bordercolor=black:"
                f"x=(w-text_w)/2:y={y}:"
                f"shadowcolor=black@0.5:shadowx=2:shadowy=2:"
                f"enable='between(t,{enable_start},{enable_end})'"
            )
            filters.append(filter_part)
        
        return ','.join(filters)
    
    def _build_manga_captions(self, captions: List[Dict], y: int, width: int, start: float) -> str:
        """Manga/comic style with bold font"""
        filters = []
        
        for cap in captions:
            enable_start = cap['start'] - start
            enable_end = cap['end'] - start
            text = cap['word'].replace("'", "\\'").replace(":", "\\:")
            
            filter_part = (
                f"drawtext=text='{text}':"
                f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                f"fontsize=56:fontcolor=yellow:"
                f"borderw=4:bordercolor=black:"
                f"x=(w-text_w)/2:y={y}:"
                f"shadowcolor=black@0.8:shadowx=3:shadowy=3:"
                f"enable='between(t,{enable_start},{enable_end})'"
            )
            filters.append(filter_part)
        
        return ','.join(filters)
    
    def _build_impact_captions(self, captions: List[Dict], y: int, width: int, start: float) -> str:
        """Impact text with word-by-word pop-in effect"""
        filters = []
        
        # Group into phrases for emphasis
        for i, cap in enumerate(captions):
            enable_start = cap['start'] - start
            enable_end = cap['end'] - start
            text = cap['word'].replace("'", "\\'").replace(":", "\\:")
            
            # Emphasize nouns/verbs (simplified: just cap first letter check)
            is_emphasized = cap['word'][0].isupper() if cap['word'] else False
            fontsize = 60 if is_emphasized else 50
            fontcolor = 'red' if is_emphasized else 'white'
            
            filter_part = (
                f"drawtext=text='{text}':"
                f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                f"fontsize={fontsize}:fontcolor={fontcolor}:"
                f"borderw=4:bordercolor=black:"
                f"x=(w-text_w)/2:y={y - i*10}:"  # Slight vertical offset per word
                f"shadowcolor=black@0.7:shadowx=3:shadowy=3:"
                f"enable='between(t,{enable_start},{enable_end})'"
            )
            filters.append(filter_part)
        
        return ','.join(filters)
    
    def _build_karaoke_captions(self, captions: List[Dict], y: int, width: int, start: float) -> str:
        """Karaoke style with progressive word highlight"""
        filters = []
        
        # Build full text line
        full_text = ' '.join(cap['word'] for cap in captions)
        full_text = full_text.replace("'", "\\'").replace(":", "\\:")
        
        # Base text (unhighlighted)
        base_filter = (
            f"drawtext=text='{full_text}':"
            f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
            f"fontsize=48:fontcolor=gray:"
            f"borderw=3:bordercolor=black:"
            f"x=(w-text_w)/2:y={y}:"
            f"shadowcolor=black@0.5:shadowx=2:shadowy=2"
        )
        filters.append(base_filter)
        
        # Highlighted words (overlay)
        for cap in captions:
            enable_start = cap['start'] - start
            enable_end = cap['end'] - start
            text = cap['word'].replace("'", "\\'").replace(":", "\\:")
            
            highlight_filter = (
                f"drawtext=text='{text}':"
                f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                f"fontsize=48:fontcolor=yellow:"
                f"borderw=3:bordercolor=black:"
                f"x=(w-text_w)/2:y={y}:"
                f"shadowcolor=black@0.5:shadowx=2:shadowy=2:"
                f"enable='between(t,{enable_start},{enable_end})'"
            )
            filters.append(highlight_filter)
        
        return ','.join(filters)
    
    def render(
        self,
        start_s: float,
        end_s: float,
        captions: List[Dict],
        template: str,
        aspect: str
    ):
        """Execute FFmpeg render"""
        cmd = self.build_ffmpeg_command(start_s, end_s, captions, template, aspect)

        # Run FFmpeg
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")

        return self.output_path

    def render_viral(
        self,
        segments: List[Dict],
        template: str,
        aspect: str
    ):
        """
        Render a viral clip by cutting filler and stitching only
        the action-packed segments together with fast cuts.

        segments: list of {'start_s': float, 'end_s': float} for high-action parts
        """
        if not segments:
            return None

        # Get dimensions
        if aspect == '9:16':
            width, height = 1080, 1920
        elif aspect == '1:1':
            width, height = 1080, 1080
        else:
            width, height = 1080, 1350

        # Render each segment to a temp file, then concat them
        temp_dir = os.path.dirname(self.output_path)
        segment_files = []

        for i, seg in enumerate(segments):
            seg_path = os.path.join(temp_dir, f"_seg_{i}_{os.path.basename(self.output_path)}")
            duration = seg['end_s'] - seg['start_s']

            cmd = [
                'ffmpeg', '-ss', str(seg['start_s']), '-i', self.video_path,
                '-t', str(duration),
                '-filter_complex',
                f'[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,'
                f'crop={width}:{height},'
                f'fade=t=in:st=0:d=0.15,fade=t=out:st={max(0, duration - 0.15)}:d=0.15,'
                f'eq=saturation=1.15:contrast=1.08'
                f'[v];'
                f'[0:a]loudnorm=I={self.loudness}:TP=-1:LRA=11,'
                f'afade=t=in:st=0:d=0.1,'
                f'afade=t=out:st={max(0, duration - 0.1)}:d=0.1'
                f'[a]',
                '-map', '[v]', '-map', '[a]',
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                '-profile:v', 'high', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k',
                '-y', seg_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Segment {i} FFmpeg failed: {result.stderr[:300]}")
            segment_files.append(seg_path)

        if len(segment_files) == 1:
            # Only one segment - just add the caption overlay
            self._add_caption_overlay(segment_files[0], self.output_path, width, height)
            os.remove(segment_files[0])
            return self.output_path

        # Create concat list file
        concat_list_path = os.path.join(temp_dir, f"_concat_{os.path.basename(self.output_path)}.txt")
        with open(concat_list_path, 'w') as f:
            for seg_file in segment_files:
                f.write(f"file '{seg_file}'\n")

        # Concat all segments
        concat_output = os.path.join(temp_dir, f"_concat_{os.path.basename(self.output_path)}")
        cmd = [
            'ffmpeg', '-f', 'concat', '-safe', '0', '-i', concat_list_path,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
            '-profile:v', 'high', '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            '-c:a', 'aac', '-b:a', '192k',
            '-y', concat_output
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Concat FFmpeg failed: {result.stderr[:300]}")

        # Add caption overlay to final video
        self._add_caption_overlay(concat_output, self.output_path, width, height)

        # Cleanup temp files
        for seg_file in segment_files:
            if os.path.exists(seg_file):
                os.remove(seg_file)
        if os.path.exists(concat_list_path):
            os.remove(concat_list_path)
        if os.path.exists(concat_output):
            os.remove(concat_output)

        return self.output_path

    def _add_caption_overlay(self, input_path: str, output_path: str, width: int, height: int):
        """Add the relatable caption text on top of a rendered video"""
        # Get duration of input
        probe_cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', input_path
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True)
        try:
            duration = float(json.loads(probe_result.stdout)['format']['duration'])
        except (KeyError, ValueError):
            duration = 15.0

        filters = []

        # Caption text overlay
        if self.hook_text:
            caption_filter = (
                f"drawtext=text='{self._escape_text(self.hook_text)}':"
                f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
                f"fontsize=56:fontcolor=white:"
                f"borderw=4:bordercolor=black:"
                f"x=(w-text_w)/2:y=h*0.15:"
                f"shadowcolor=black@0.9:shadowx=3:shadowy=3"
            )
            filters.append(caption_filter)

        # Watermark if set
        if self.watermark:
            wm_filter = (
                f"drawtext=text='{self._escape_text(self.watermark)}':"
                f"fontsize=28:fontcolor=white@0.8:"
                f"x=20:y=120:shadowcolor=black@0.6:shadowx=2:shadowy=2"
            )
            filters.append(wm_filter)

        if not filters:
            # No overlays needed - just copy
            import shutil
            shutil.copy2(input_path, output_path)
            return

        filter_str = ','.join(filters)
        cmd = [
            'ffmpeg', '-i', input_path,
            '-vf', filter_str,
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
            '-c:a', 'copy',
            '-movflags', '+faststart',
            '-y', output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Caption overlay FFmpeg failed: {result.stderr[:300]}")


def _find_action_segments(video_path: str, start_s: float, end_s: float) -> List[Dict]:
    """
    Analyze a clip and find the high-action sub-segments.
    Uses frame differencing to detect motion intensity.
    Returns only the action-packed parts, cutting filler.
    """
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return [{'start_s': start_s, 'end_s': end_s}]

    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Jump to the start of the clip
    start_frame = int(start_s * fps)
    end_frame = int(end_s * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    # Compute motion score per second
    motion_per_second = []
    prev_gray = None
    frame_idx = start_frame
    current_second_diffs = []
    current_second = int(start_s)

    sample_rate = max(1, int(fps / 8))  # Sample ~8 frames per second

    while frame_idx < end_frame:
        ret, frame = cap.read()
        if not ret:
            break

        if (frame_idx - start_frame) % sample_rate == 0:
            gray = cv2.cvtColor(cv2.resize(frame, (320, 180)), cv2.COLOR_BGR2GRAY)
            if prev_gray is not None:
                diff = cv2.absdiff(gray, prev_gray)
                motion = float(np.mean(diff))

                second = int(frame_idx / fps)
                if second > current_second and current_second_diffs:
                    motion_per_second.append({
                        'second': current_second,
                        'motion': np.mean(current_second_diffs)
                    })
                    current_second_diffs = []
                    current_second = second

                current_second_diffs.append(motion)
            prev_gray = gray

        frame_idx += 1

    # Final second
    if current_second_diffs:
        motion_per_second.append({
            'second': current_second,
            'motion': np.mean(current_second_diffs)
        })

    cap.release()

    if not motion_per_second:
        return [{'start_s': start_s, 'end_s': end_s}]

    # Normalize motion scores
    max_motion = max(m['motion'] for m in motion_per_second)
    if max_motion > 0:
        for m in motion_per_second:
            m['motion'] /= max_motion

    # Find action-packed segments (motion > 0.3 = action)
    ACTION_THRESHOLD = 0.3
    MIN_SEGMENT_DURATION = 1.5  # Minimum segment length in seconds

    segments = []
    current_seg_start = None

    for m in motion_per_second:
        if m['motion'] >= ACTION_THRESHOLD:
            if current_seg_start is None:
                current_seg_start = float(m['second'])
        else:
            if current_seg_start is not None:
                seg_end = float(m['second'])
                if seg_end - current_seg_start >= MIN_SEGMENT_DURATION:
                    segments.append({
                        'start_s': current_seg_start,
                        'end_s': seg_end
                    })
                current_seg_start = None

    # Close last segment
    if current_seg_start is not None:
        seg_end = float(motion_per_second[-1]['second'] + 1)
        if seg_end - current_seg_start >= MIN_SEGMENT_DURATION:
            segments.append({
                'start_s': current_seg_start,
                'end_s': min(seg_end, end_s)
            })

    # If we found good action segments, return them
    # Otherwise fall back to the full clip
    if segments:
        total_action = sum(s['end_s'] - s['start_s'] for s in segments)
        total_clip = end_s - start_s
        # Only use viral mode if we're cutting at least 15% of filler
        if total_action < total_clip * 0.85:
            return segments

    # Not enough filler to cut - use full clip as one segment
    return [{'start_s': start_s, 'end_s': end_s}]


@celery_app.task(bind=True)
def render_clips_task(self: Task, render_id: str, params: Dict):
    """
    Render task - produces download-ready clips with auto-editing.
    Handles both local file:// and S3 source videos.
    Keeps rendered files on local disk for direct download.
    """
    import shutil
    import glob as glob_mod

    db = SessionLocal()
    RENDER_DIR = "/tmp/videos/renders"
    os.makedirs(RENDER_DIR, exist_ok=True)

    try:
        render = db.query(Render).filter(Render.id == render_id).first()
        if not render:
            raise ValueError("Render not found")

        render.status = 'processing'
        db.commit()

        # Extract parameters
        candidate_ids = params['candidate_ids']
        template = params.get('template', 'clean')
        outputs = params.get('outputs', ['9:16'])
        config = {
            'watermark': params.get('watermark', ''),
            'loudness': params.get('loudness', '-14'),
            'captions': params.get('captions', 'off'),
            'auto_edit': params.get('auto_edit', True),
            'fade_duration': params.get('fade_duration', 0.3),
            'hook_text': params.get('hook_text', ''),
            'cta_text': params.get('cta_text', '')
        }

        rendered_files = {}
        total_renders = len(candidate_ids) * len(outputs)
        current = 0

        for cand_id in candidate_ids:
            candidate = db.query(Candidate).filter(Candidate.id == cand_id).first()
            if not candidate:
                continue

            video = db.query(Video).filter(Video.id == candidate.video_id).first()
            transcript = db.query(Transcript).filter(
                Transcript.video_id == candidate.video_id
            ).first()

            # Resolve video path - handle local file:// and S3
            video_path = None
            if video.src_url.startswith("file://"):
                local_src = video.src_url.replace("file://", "")
                if os.path.isfile(local_src):
                    video_path = local_src
                else:
                    # Try finding by video ID in /tmp/videos
                    matches = glob_mod.glob(f"/tmp/videos/{video.id}.*")
                    if matches:
                        video_path = matches[0]
            else:
                # S3 source - download locally
                video_path = f"/tmp/videos/{video.id}.mp4"
                if not os.path.exists(video_path):
                    download_from_s3(video.src_url, video_path)

            if not video_path or not os.path.exists(video_path):
                raise FileNotFoundError(f"Source video not found for {video.id}")

            # Get captions for this segment
            captions = []
            if config['captions'] == 'on' and transcript:
                for word in transcript.words:
                    if candidate.start_s <= word['start'] <= candidate.end_s:
                        captions.append(word)

            # Detect high-action sub-segments within this clip
            action_segments = _find_action_segments(
                video_path, candidate.start_s, candidate.end_s
            )

            # Render each aspect ratio
            for aspect in outputs:
                current += 1
                progress = int((current / total_renders) * 100)
                self.update_state(
                    state='PROGRESS',
                    meta={'step': f'rendering_{aspect}', 'progress': progress}
                )

                output_filename = f"{cand_id}_{aspect.replace(':', 'x')}.mp4"
                output_path = os.path.join(RENDER_DIR, output_filename)

                renderer = TemplateRenderer(video_path, output_path, config)

                if action_segments and len(action_segments) > 1:
                    # Viral mode: stitch only action-packed parts
                    renderer.render_viral(action_segments, template, aspect)
                else:
                    # Standard render for the full clip
                    renderer.render(
                        candidate.start_s,
                        candidate.end_s,
                        captions,
                        template,
                        aspect
                    )

                # Store local path for direct download
                if cand_id not in rendered_files:
                    rendered_files[cand_id] = {}
                rendered_files[cand_id][aspect] = f"local://{output_path}"

        # Update render record
        render.status = 'completed'
        render.files = rendered_files
        db.commit()

        return {'status': 'completed', 'files': rendered_files}

    except Exception as e:
        render.status = 'failed'
        render.files = {'error': str(e)}
        db.commit()
        raise
    finally:
        db.close()
        