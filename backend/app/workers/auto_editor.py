import os
import subprocess
import json
import random
import logging
from typing import List, Dict, Optional
from celery import Task
from sqlalchemy.orm import Session

from app.workers.celery_app import celery_app
from app.database import SessionLocal
from app.models import Render, Candidate, Video
from app.services.s3_service import download_from_s3
from app.workers.renderer import _find_action_segments

logger = logging.getLogger(__name__)


class AutoEditRenderer:
    """
    Auto-Edit Studio renderer with 5 distinct viral anime editing styles.

    Templates are designed around real TikTok/Instagram anime edit trends:
    - velocity:  Velocity/VSP edits — dramatic speed ramps, zoom punches, flash impacts
    - flow:      Flow edits — smooth crossfades, warm tones, mesmerizing drift
    - hard:      Hard edits — aggressive cuts, screen shakes, dark energy
    - cinematic: Cinematic/AMV — film grain, letterbox, dramatic slow-mo
    - glitch:    Glitch/Cyberpunk — RGB split, digital noise, stutter cuts
    """

    def __init__(self, video_path: str, output_path: str, config: Dict):
        self.video_path = video_path
        self.output_path = output_path
        self.config = config
        self.loudness = config.get('loudness', '-14')
        self.max_duration = config.get('max_duration', 30)

    # ── Resolution helper ────────────────────────────────────────────

    @staticmethod
    def _dims(aspect: str):
        if aspect == '9:16':
            return 1080, 1920
        elif aspect == '1:1':
            return 1080, 1080
        return 1080, 1350

    # ── Analysis helpers ─────────────────────────────────────────────

    def detect_motion_peaks(self, start_s: float, end_s: float) -> List[Dict]:
        """Detect motion peaks using OpenCV frame differencing."""
        try:
            import cv2
            import numpy as np
        except ImportError:
            return []

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 24
        start_frame = int(start_s * fps)
        end_frame = int(end_s * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        motion_scores = []
        prev_gray = None
        sample_rate = max(1, int(fps / 6))

        for frame_idx in range(start_frame, end_frame):
            ret, frame = cap.read()
            if not ret:
                break
            if (frame_idx - start_frame) % sample_rate == 0:
                gray = cv2.cvtColor(cv2.resize(frame, (320, 180)), cv2.COLOR_BGR2GRAY)
                if prev_gray is not None:
                    diff = cv2.absdiff(gray, prev_gray)
                    motion = float(np.mean(diff))
                    motion_scores.append({
                        'time': start_s + (frame_idx - start_frame) / fps,
                        'motion': motion
                    })
                prev_gray = gray

        cap.release()

        if not motion_scores:
            return []

        max_motion = max(m['motion'] for m in motion_scores)
        if max_motion > 0:
            for m in motion_scores:
                m['motion'] /= max_motion

        return [m for m in motion_scores if m['motion'] >= 0.6]

    # ── Per-template VIDEO filter builders (NO per-segment fades) ────

    def _velocity_vfilters(self, w: int, h: int) -> str:
        """
        VELOCITY EDIT — The #1 viral anime style.
        High saturation for mobile pop, sharpening for clarity,
        subtle zoom for energy. Speed ramps handled by sub-segments.
        """
        return (
            f'scale={w}:{h}:force_original_aspect_ratio=increase,'
            f'crop={w}:{h},'
            f'eq=saturation=1.5:contrast=1.35:brightness=0.04,'
            f'unsharp=5:5:1.2:5:5:0.6,'
            f"zoompan=z='if(eq(on,1),1.0,min(zoom+0.0008,1.06))'"
            f":d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={w}x{h}:fps=30"
        )

    def _flow_vfilters(self, w: int, h: int) -> str:
        """
        FLOW EDIT — Smooth, mesmerizing, satisfying.
        Warm cinematic color grading, very gentle Ken Burns drift,
        soft vignette for depth. No speed changes.
        """
        return (
            f'scale={w}:{h}:force_original_aspect_ratio=increase,'
            f'crop={w}:{h},'
            f'colorchannelmixer=rr=1.06:gg=1.0:bb=0.88:ra=0.02,'
            f'eq=saturation=1.1:contrast=1.05:brightness=0.01,'
            f"zoompan=z='min(zoom+0.0002,1.04)'"
            f":d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={w}x{h}:fps=30,"
            f'vignette=PI/5'
        )

    def _hard_vfilters(self, w: int, h: int) -> str:
        """
        HARD EDIT — Aggressive, punchy, dark energy.
        Desaturated with crushed blacks, high contrast,
        strong sharpening, cyan-tinted shadows.
        """
        return (
            f'scale={w}:{h}:force_original_aspect_ratio=increase,'
            f'crop={w}:{h},'
            f'eq=saturation=0.5:contrast=1.5:brightness=-0.03,'
            f'colorchannelmixer=rr=0.9:gg=0.95:bb=1.1:ba=0.03,'
            f'unsharp=5:5:2.0:5:5:1.0,'
            f'curves=m=0/0:0.15/0.05:0.5/0.45:1/1'
        )

    def _cinematic_vfilters(self, w: int, h: int) -> str:
        """
        CINEMATIC/AMV — Film-quality storytelling look.
        Letterbox bars, film grain, vignette, muted warm palette,
        subtle blue shadows. Speed ramps handled by sub-segments.
        """
        bar_h = int(h * 0.07)
        return (
            f'scale={w}:{h}:force_original_aspect_ratio=increase,'
            f'crop={w}:{h},'
            f'colorchannelmixer=rr=1.04:gg=0.97:bb=0.90:ba=0.02,'
            f'eq=saturation=0.8:contrast=1.15:brightness=-0.02,'
            f'noise=alls=10:allf=t+u,'
            f'vignette=PI/3.5,'
            f'drawbox=x=0:y=0:w={w}:h={bar_h}:color=black:t=fill,'
            f'drawbox=x=0:y={h - bar_h}:w={w}:h={bar_h}:color=black:t=fill'
        )

    def _glitch_vfilters(self, w: int, h: int) -> str:
        """
        GLITCH/CYBERPUNK — Digital chaos, neon-drenched.
        Strong RGB chromatic aberration, neon saturation boost,
        heavy sharpening for that digital edge.
        """
        return (
            f'scale={w}:{h}:force_original_aspect_ratio=increase,'
            f'crop={w}:{h},'
            f'eq=contrast=1.6:saturation=1.4:brightness=0.03,'
            f'rgbashift=rh=-6:rv=3:bh=6:bv=-3,'
            f'unsharp=7:7:2.5:7:7:1.2,'
            f'colorchannelmixer=rr=1.1:gg=0.95:bb=1.15'
        )

    # ── Per-template AUDIO filter builders (NO per-segment fades) ────

    def _velocity_afilters(self, speed: float) -> str:
        """Bass boost + punch compression for impacts."""
        f = f'loudnorm=I={self.loudness}:TP=-1:LRA=11,aformat=sample_rates=48000'
        f += self._atempo(speed)
        f += ',bass=g=8:f=80,acompressor=threshold=-20dB:ratio=4:attack=5:release=50'
        return f

    def _flow_afilters(self) -> str:
        """Clean, warm audio. No tempo change."""
        return f'loudnorm=I={self.loudness}:TP=-1:LRA=11,aformat=sample_rates=48000'

    def _hard_afilters(self, speed: float) -> str:
        """Compressed, punchy, slightly boosted mids."""
        f = f'loudnorm=I={self.loudness}:TP=-1:LRA=11,aformat=sample_rates=48000'
        f += self._atempo(speed)
        f += ',bass=g=4:f=120,treble=g=3:f=4000'
        return f

    def _cinematic_afilters(self, speed: float) -> str:
        """Rich, theatrical audio with subtle reverb feel via echo."""
        f = f'loudnorm=I={self.loudness}:TP=-1:LRA=11,aformat=sample_rates=48000'
        f += self._atempo(speed)
        return f

    def _glitch_afilters(self, speed: float) -> str:
        """Distorted, bitcrushed digital audio."""
        f = f'loudnorm=I={self.loudness}:TP=-1:LRA=11,aformat=sample_rates=48000'
        f += self._atempo(speed)
        f += ',bass=g=10:f=60,acompressor=threshold=-15dB:ratio=6:attack=2:release=30'
        return f

    @staticmethod
    def _atempo(speed: float) -> str:
        """Build atempo filter chain for any speed value."""
        if speed == 1.0:
            return ''
        if 0.5 <= speed <= 2.0:
            return f',atempo={speed}'
        elif speed < 0.5:
            return f',atempo={speed * 2},atempo=0.5'
        else:
            return f',atempo={speed / 2},atempo=2.0'

    # ── Segment rendering ────────────────────────────────────────────

    def _render_segment(
        self, start_s: float, end_s: float,
        aspect: str, template: str, speed: float = 1.0
    ) -> str:
        """Render a single segment. NO fades added — fades are only on final output."""
        w, h = self._dims(aspect)
        raw_duration = end_s - start_s

        # Template-specific video filters
        if template == 'anime_hype':
            vf = self._velocity_vfilters(w, h)
        elif template == 'clean_flow':
            vf = self._flow_vfilters(w, h)
        elif template == 'hard_cuts':
            vf = self._hard_vfilters(w, h)
        elif template == 'cinematic':
            vf = self._cinematic_vfilters(w, h)
        elif template == 'glitch':
            vf = self._glitch_vfilters(w, h)
        else:
            vf = (f'scale={w}:{h}:force_original_aspect_ratio=increase,'
                  f'crop={w}:{h}')

        # Speed change via setpts
        if speed != 1.0:
            vf += f',setpts=PTS/{speed}'

        vf = f'[0:v]{vf}[v]'

        # Template-specific audio filters
        if template == 'anime_hype':
            af = self._velocity_afilters(speed)
        elif template == 'clean_flow':
            af = self._flow_afilters()
        elif template == 'hard_cuts':
            af = self._hard_afilters(speed)
        elif template == 'cinematic':
            af = self._cinematic_afilters(speed)
        elif template == 'glitch':
            af = self._glitch_afilters(speed)
        else:
            af = f'loudnorm=I={self.loudness}:TP=-1:LRA=11,aformat=sample_rates=48000'

        af = f'[0:a]{af}[a]'

        temp_dir = os.path.dirname(self.output_path)
        seg_id = random.randint(10000, 99999)
        seg_path = os.path.join(temp_dir, f"_autoedit_seg_{seg_id}.mp4")

        cmd = [
            'ffmpeg', '-ss', str(start_s), '-i', self.video_path,
            '-t', str(raw_duration),
            '-filter_complex', f'{vf};{af}',
            '-map', '[v]', '-map', '[a]',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
            '-profile:v', 'high', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
            '-y', seg_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Segment FFmpeg failed: {result.stderr[:500]}")

        return seg_path

    # ── Transition generators ────────────────────────────────────────

    def _create_flash_frame(self, w: int, h: int, duration: float, color: str = 'white') -> str:
        """Create a colored flash transition frame (white or custom)."""
        temp_dir = os.path.dirname(self.output_path)
        trans_id = random.randint(10000, 99999)
        path = os.path.join(temp_dir, f"_autoedit_flash_{trans_id}.mp4")

        cmd = [
            'ffmpeg',
            '-f', 'lavfi', '-i', f'color=c={color}:s={w}x{h}:d={duration}:r=30',
            '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000',
            '-t', str(duration),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
            '-profile:v', 'high', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k',
            '-y', path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Flash FFmpeg failed: {result.stderr[:300]}")
        return path

    def _create_glitch_transition(self, w: int, h: int) -> str:
        """Create a short digital glitch artifact transition."""
        temp_dir = os.path.dirname(self.output_path)
        trans_id = random.randint(10000, 99999)
        path = os.path.join(temp_dir, f"_autoedit_glitch_{trans_id}.mp4")

        # Random colored noise burst
        colors = ['0xFF00FF', '0x00FFFF', '0xFF0000']
        c = random.choice(colors)
        dur = 0.08  # ~2-3 frames

        cmd = [
            'ffmpeg',
            '-f', 'lavfi', '-i',
            f'color=c={c}:s={w}x{h}:d={dur}:r=30,'
            f'noise=alls=80:allf=t+u,'
            f'rgbashift=rh={random.randint(-10, 10)}:bh={random.randint(-10, 10)}',
            '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000',
            '-t', str(dur),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
            '-profile:v', 'high', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k',
            '-y', path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Glitch transition failed: {result.stderr[:300]}")
        return path

    def _get_transition(self, template: str, w: int, h: int) -> Optional[str]:
        """Get a template-specific transition clip."""
        if template == 'anime_hype':
            # White impact flash (3 frames)
            return self._create_flash_frame(w, h, 0.1, 'white')
        elif template == 'clean_flow':
            # No transition clip — segments flow into each other
            return None
        elif template == 'hard_cuts':
            # No transition — raw hard cut
            return None
        elif template == 'cinematic':
            # Brief black dip for dramatic pause
            return self._create_flash_frame(w, h, 0.15, 'black@0.7')
        elif template == 'glitch':
            # Digital glitch artifact
            return self._create_glitch_transition(w, h)
        return None

    # ── Concatenation with final fades ───────────────────────────────

    def _concat_and_finalize(self, segment_files: List[str], template: str,
                             aspect: str, output: str) -> str:
        """
        Concatenate segments and apply ONLY final intro/outro fades.
        This prevents black frames between segments.
        """
        w, h = self._dims(aspect)
        temp_dir = os.path.dirname(output)
        concat_id = random.randint(10000, 99999)

        # Step 1: concat all segments raw (no re-encode, stream copy)
        concat_list = os.path.join(temp_dir, f"_autoedit_concat_{concat_id}.txt")
        with open(concat_list, 'w') as f:
            for seg_file in segment_files:
                f.write(f"file '{seg_file}'\n")

        raw_concat = os.path.join(temp_dir, f"_autoedit_raw_{concat_id}.mp4")
        cmd = [
            'ffmpeg', '-f', 'concat', '-safe', '0', '-i', concat_list,
            '-c', 'copy', '-movflags', '+faststart',
            '-y', raw_concat
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # Fallback: re-encode concat if stream copy fails
            cmd = [
                'ffmpeg', '-f', 'concat', '-safe', '0', '-i', concat_list,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                '-profile:v', 'high', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k',
                '-movflags', '+faststart',
                '-y', raw_concat
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Concat failed: {result.stderr[:500]}")

        # Get total duration of concatenated file
        probe_cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', raw_concat
        ]
        probe = subprocess.run(probe_cmd, capture_output=True, text=True)
        total_dur = 30.0
        try:
            total_dur = float(json.loads(probe.stdout)['format']['duration'])
        except (json.JSONDecodeError, KeyError):
            pass

        # Step 2: Apply final intro/outro fades only
        fade_config = {
            'anime_hype': (0.15, 0.15),    # Snappy — minimal fade
            'clean_flow': (0.6, 0.8),       # Smooth — gentle fade
            'hard_cuts': (0.0, 0.0),        # None — raw energy
            'cinematic': (1.0, 1.2),        # Dramatic — slow fade
            'glitch': (0.1, 0.1),           # Digital — instant
        }
        fade_in, fade_out = fade_config.get(template, (0.3, 0.3))

        if fade_in > 0 or fade_out > 0:
            vf_final = ''
            af_final = ''
            if fade_in > 0:
                vf_final += f'fade=t=in:st=0:d={fade_in}'
                af_final += f'afade=t=in:st=0:d={fade_in}'
            if fade_out > 0:
                out_start = max(0, total_dur - fade_out)
                if vf_final:
                    vf_final += ','
                    af_final += ','
                vf_final += f'fade=t=out:st={out_start}:d={fade_out}'
                af_final += f'afade=t=out:st={out_start}:d={fade_out}'

            cmd = [
                'ffmpeg', '-i', raw_concat,
                '-vf', vf_final,
                '-af', af_final,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                '-profile:v', 'high', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k',
                '-movflags', '+faststart',
                '-y', output
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Final fade failed: {result.stderr[:500]}")
            os.remove(raw_concat)
        else:
            # hard_cuts: no fades, just rename
            import shutil
            shutil.move(raw_concat, output)

        # Cleanup
        if os.path.exists(concat_list):
            os.remove(concat_list)

        return output

    # ── Speed ramping ────────────────────────────────────────────────

    def _split_at_peaks(
        self, start_s: float, end_s: float,
        motion_peaks: List[Dict],
        peak_speed: float, normal_speed: float,
        peak_window: float = 1.2
    ) -> List[Dict]:
        """
        Split a segment into sub-segments with velocity-style speed ramps.
        S-curve feel: fast between impacts, slow on impacts.
        """
        peak_times = sorted(set(p['time'] for p in motion_peaks))
        sub_segments = []
        current = start_s

        for peak_time in peak_times:
            peak_start = max(current, peak_time - peak_window / 2)
            peak_end = min(end_s, peak_time + peak_window / 2)

            # Fast segment before peak (build-up)
            if peak_start > current + 0.5:
                sub_segments.append({
                    'start_s': current,
                    'end_s': peak_start,
                    'speed': normal_speed
                })

            # Slow-mo at peak (the money shot)
            if peak_end > peak_start + 0.3:
                sub_segments.append({
                    'start_s': peak_start,
                    'end_s': peak_end,
                    'speed': peak_speed
                })

            current = peak_end

        # Fast tail after last peak
        if current < end_s - 0.5:
            sub_segments.append({
                'start_s': current,
                'end_s': end_s,
                'speed': normal_speed
            })

        return sub_segments if sub_segments else [{
            'start_s': start_s,
            'end_s': end_s,
            'speed': normal_speed
        }]

    # ── Main render orchestrator ─────────────────────────────────────

    def render(self, segments: List[Dict], template_name: str, aspect: str) -> str:
        """
        Main render pipeline:
        1. Trim segments to max_duration
        2. Apply template-specific speed ramps (velocity/cinematic)
        3. Render each sub-segment with template filters (NO per-segment fades)
        4. Insert template-specific transitions between segments
        5. Concatenate and apply final intro/outro fades only
        """
        w, h = self._dims(aspect)

        # Trim segments to max_duration
        trimmed = []
        total = 0.0
        for seg in segments:
            seg_dur = seg['end_s'] - seg['start_s']
            if total + seg_dur > self.max_duration:
                remaining = self.max_duration - total
                if remaining > 1.0:
                    trimmed.append({
                        'start_s': seg['start_s'],
                        'end_s': seg['start_s'] + remaining
                    })
                break
            trimmed.append(seg)
            total += seg_dur

        if not trimmed:
            trimmed = segments[:1]

        # Template speed configurations — each is very different
        speed_config = {
            'anime_hype': {  # VELOCITY: dramatic S-curve ramps
                'peak_speed': 0.4,
                'normal_speed': 1.8,
                'peak_window': 1.5,
                'use_ramps': True,
            },
            'clean_flow': {  # FLOW: constant smooth speed
                'normal_speed': 1.0,
                'use_ramps': False,
            },
            'hard_cuts': {  # HARD: fast constant, no ramps
                'normal_speed': 1.15,
                'use_ramps': False,
            },
            'cinematic': {  # CINEMATIC: dramatic slow-mo on peaks
                'peak_speed': 0.5,
                'normal_speed': 1.0,
                'peak_window': 2.0,
                'use_ramps': True,
            },
            'glitch': {  # GLITCH: random speed stutters
                'peak_speed': 0.6,
                'normal_speed': 1.3,
                'peak_window': 0.6,
                'use_ramps': True,
            },
        }
        speeds = speed_config.get(template_name, {'normal_speed': 1.0, 'use_ramps': False})

        rendered_parts = []
        temp_files = []

        for i, seg in enumerate(trimmed):
            if speeds.get('use_ramps', False):
                motion_peaks = self.detect_motion_peaks(seg['start_s'], seg['end_s'])
                if motion_peaks:
                    sub_segments = self._split_at_peaks(
                        seg['start_s'], seg['end_s'], motion_peaks,
                        peak_speed=speeds.get('peak_speed', 0.5),
                        normal_speed=speeds['normal_speed'],
                        peak_window=speeds.get('peak_window', 1.2)
                    )
                    for sub in sub_segments:
                        seg_path = self._render_segment(
                            sub['start_s'], sub['end_s'],
                            aspect, template_name, sub['speed']
                        )
                        rendered_parts.append(seg_path)
                        temp_files.append(seg_path)
                else:
                    seg_path = self._render_segment(
                        seg['start_s'], seg['end_s'],
                        aspect, template_name, speeds['normal_speed']
                    )
                    rendered_parts.append(seg_path)
                    temp_files.append(seg_path)
            else:
                seg_path = self._render_segment(
                    seg['start_s'], seg['end_s'],
                    aspect, template_name, speeds['normal_speed']
                )
                rendered_parts.append(seg_path)
                temp_files.append(seg_path)

            # Insert transition between segments (not after the last one)
            if i < len(trimmed) - 1:
                transition = self._get_transition(template_name, w, h)
                if transition:
                    rendered_parts.append(transition)
                    temp_files.append(transition)

        # Concatenate with final fades only (no black frames!)
        if len(rendered_parts) == 1:
            import shutil
            shutil.move(rendered_parts[0], self.output_path)
            temp_files = [f for f in temp_files if f != rendered_parts[0]]
        else:
            self._concat_and_finalize(rendered_parts, template_name, aspect, self.output_path)

        # Cleanup temp files
        for f in temp_files:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except OSError:
                pass

        return self.output_path


# ── Celery task ──────────────────────────────────────────────────────

def _safe_update_state(task_self, **kwargs):
    try:
        if task_self and hasattr(task_self, 'request'):
            task_self.update_state(**kwargs)
    except Exception:
        pass


@celery_app.task(bind=True)
def auto_edit_task(self, render_id: str, params: Dict):
    """
    Celery task: Auto-Edit Studio rendering.
    Renders selected candidates with a trending template.
    """
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

        candidate_ids = params['candidate_ids']
        template = params.get('auto_edit_template', 'anime_hype')
        outputs = params.get('outputs', ['9:16'])
        max_duration = params.get('max_duration', 30)
        loudness = params.get('loudness', '-14')

        rendered_files = {}
        total_renders = len(candidate_ids) * len(outputs)
        current = 0

        for cand_id in candidate_ids:
            candidate = db.query(Candidate).filter(Candidate.id == cand_id).first()
            if not candidate:
                continue

            video = db.query(Video).filter(Video.id == candidate.video_id).first()

            # Resolve video path
            video_path = None
            if video.src_url.startswith("file://"):
                local_src = video.src_url.replace("file://", "")
                if os.path.isfile(local_src):
                    video_path = local_src
                else:
                    matches = glob_mod.glob(f"/tmp/videos/{video.id}.*")
                    if matches:
                        video_path = matches[0]
            else:
                video_path = f"/tmp/videos/{video.id}.mp4"
                if not os.path.exists(video_path):
                    download_from_s3(video.src_url, video_path)

            if not video_path or not os.path.exists(video_path):
                raise FileNotFoundError(f"Source video not found for {video.id}")

            # Detect action segments
            action_segments = _find_action_segments(
                video_path, candidate.start_s, candidate.end_s
            )

            for aspect in outputs:
                current += 1
                progress = int((current / total_renders) * 100)
                _safe_update_state(self,
                    state='PROGRESS',
                    meta={'step': f'auto_edit_{template}_{aspect}', 'progress': progress}
                )

                output_filename = f"{cand_id}_{aspect.replace(':', 'x')}_auto_{template}.mp4"
                output_path = os.path.join(RENDER_DIR, output_filename)

                config = {
                    'loudness': loudness,
                    'max_duration': max_duration,
                }

                renderer = AutoEditRenderer(video_path, output_path, config)
                renderer.render(action_segments, template, aspect)

                if cand_id not in rendered_files:
                    rendered_files[cand_id] = {}
                rendered_files[cand_id][aspect] = f"local://{output_path}"

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
