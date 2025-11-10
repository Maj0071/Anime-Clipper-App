import os
import subprocess
import json
from typing import List, Dict
from celery import Task
from sqlalchemy.orm import Session

from app.workers.celery_app import celery_app
from app.database import SessionLocal
from app.models import Render, Candidate, Video, Transcript
from app.services.s3_service import download_from_s3, upload_to_s3


class TemplateRenderer:
    """Handles different caption templates and styling"""
    
    def __init__(self, video_path: str, output_path: str, config: Dict):
        self.video_path = video_path
        self.output_path = output_path
        self.config = config
        self.watermark = config.get('watermark', '@myanime')
        self.loudness = config.get('loudness', '-14')
    
    def build_ffmpeg_command(
        self,
        start_s: float,
        end_s: float,
        captions: List[Dict],
        template: str,
        aspect: str
    ) -> List[str]:
        """Build FFmpeg command with filters for specified template"""
        
        duration = end_s - start_s
        
        # Base command
        cmd = [
            'ffmpeg', '-ss', str(start_s), '-i', self.video_path,
            '-t', str(duration)
        ]
        
        # Build filter complex
        filters = []
        
        # 1. Video scaling and cropping for aspect ratio
        if aspect == '9:16':
            filters.append(
                '[0:v]scale=1080:1920:force_original_aspect_ratio=increase,'
                'crop=1080:1920'
            )
        elif aspect == '1:1':
            filters.append(
                '[0:v]scale=1080:1080:force_original_aspect_ratio=increase,'
                'crop=1080:1080'
            )
        elif aspect == '4:5':
            filters.append(
                '[0:v]scale=1080:1350:force_original_aspect_ratio=increase,'
                'crop=1080:1350'
            )
        
        # 2. Optional subtle zoom (for manga template)
        if template == 'manga':
            filters[-1] += ',zoompan=z=\'min(zoom+0.0005,1.05)\':d=1:x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\':s=1080x1920'
        
        # 3. Add watermark
        watermark_filter = (
            f"drawtext=text='{self.watermark}':"
            f"fontsize=24:fontcolor=white@0.6:"
            f"x=20:y=20:shadowcolor=black@0.5:shadowx=2:shadowy=2"
        )
        filters[-1] += f',{watermark_filter}'
        
        # 4. Add captions based on template
        caption_filter = self.build_caption_filter(captions, template, aspect, start_s)
        if caption_filter:
            filters[-1] += f',{caption_filter}'
        
        filters[-1] += '[v]'
        
        # 5. Audio normalization
        audio_filter = (
            f'[0:a]loudnorm=I={self.loudness}:TP=-1:LRA=11,'
            f'aformat=sample_rates=48000[a]'
        )
        filters.append(audio_filter)
        
        # Add filter complex to command
        cmd.extend(['-filter_complex', ';'.join(filters)])
        
        # Map outputs
        cmd.extend(['-map', '[v]', '-map', '[a]'])
        
        # Encoding settings
        cmd.extend([
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-profile:v', 'high',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-y',
            self.output_path
        ])
        
        return cmd
    
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


@celery_app.task(bind=True)
def render_clips_task(self: Task, render_id: str, params: Dict):
    """
    Render task:
    1. Download source video
    2. Get candidate details and transcripts
    3. For each candidate + aspect ratio:
       - Apply template
       - Add captions from Whisper timestamps
       - Normalize audio
       - Add watermark
    4. Upload rendered files to S3
    5. Update render record
    """
    db = SessionLocal()
    
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
            'watermark': params.get('watermark', '@myanime'),
            'loudness': params.get('loudness', '-14'),
            'captions': params.get('captions', 'on')
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
            
            # Download video
            video_path = f"/tmp/videos/{video.id}.mp4"
            if not os.path.exists(video_path):
                download_from_s3(video.src_url, video_path)
            
            # Get captions for this segment
            captions = []
            if config['captions'] == 'on' and transcript:
                for word in transcript.words:
                    if candidate.start_s <= word['start'] <= candidate.end_s:
                        captions.append(word)
            
            # Render each aspect ratio
            for aspect in outputs:
                current += 1
                progress = int((current / total_renders) * 100)
                self.update_state(
                    state='PROGRESS',
                    meta={'step': f'rendering_{aspect}', 'progress': progress}
                )
                
                output_filename = f"{cand_id}_{aspect.replace(':', 'x')}.mp4"
                output_path = f"/tmp/videos/{output_filename}"
                
                # Render
                renderer = TemplateRenderer(video_path, output_path, config)
                renderer.render(
                    candidate.start_s,
                    candidate.end_s,
                    captions,
                    template,
                    aspect
                )
                
                # Upload
                s3_key = f"renders/{render_id}/{output_filename}"
                file_url = upload_to_s3(output_path, s3_key)
                
                # Track output
                if cand_id not in rendered_files:
                    rendered_files[cand_id] = {}
                rendered_files[cand_id][aspect] = file_url
                
                # Cleanup
                os.remove(output_path)
        
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
        