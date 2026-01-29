import os
import subprocess
import json
import random
import shutil
import logging
from typing import List, Dict, Optional, Tuple
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
    Auto-Edit Studio v2 — Viral anime editing engine.

    Uses FFmpeg xfade for seamless transitions (ZERO black frames).
    Each template has a radically different visual identity:

    - anime_hype:  Velocity/VSP edits — extreme speed ramps, zoom punch,
                   white flash impacts, hyper-saturated, crushed contrast
    - clean_flow:  Flow edits — smooth dissolves, warm dreamy color grade,
                   vignette glow, gentle Ken Burns drift
    - hard_cuts:   Hard edits — instant cuts, near-monochrome, extreme contrast,
                   cyan shadows, crushed blacks, aggressive sharpening
    - cinematic:   Cinematic/AMV — letterbox bars, film grain, muted warm palette,
                   dramatic slow-mo, deep vignette, fade transitions
    - glitch:      Glitch/Cyberpunk — extreme RGB split, neon saturation,
                   scan lines, pixelize transitions, random speed stutter
    """

    def __init__(self, video_path: str, output_path: str, config: Dict):
        self.video_path = video_path
        self.output_path = output_path
        self.config = config
        self.loudness = config.get('loudness', '-14')
        self.max_duration = config.get('max_duration', 30)

    # ── Resolution helper ────────────────────────────────────────────

    @staticmethod
    def _dims(aspect: str) -> Tuple[int, int]:
        if aspect == '9:16':
            return 1080, 1920
        elif aspect == '1:1':
            return 1080, 1080
        return 1080, 1350

    # ── Probe helper ─────────────────────────────────────────────────

    @staticmethod
    def _probe_duration(path: str) -> float:
        """Get duration of a video file in seconds."""
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        try:
            return float(json.loads(result.stdout)['format']['duration'])
        except (json.JSONDecodeError, KeyError, ValueError):
            return 5.0

    # ── Motion detection ─────────────────────────────────────────────

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
        sample_rate = max(1, int(fps / 8))

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

        # Lower threshold = more peaks detected = more speed ramp points
        return [m for m in motion_scores if m['motion'] >= 0.5]

    # ══════════════════════════════════════════════════════════════════
    #  VIDEO FILTERS — Each template has a RADICALLY different look
    # ══════════════════════════════════════════════════════════════════

    def _velocity_vfilters(self, w: int, h: int) -> str:
        """
        VELOCITY EDIT — The #1 viral anime style on TikTok.

        Hyper-saturated colors that POP on mobile screens.
        Extreme contrast for dramatic light/dark separation.
        Strong sharpening for crisp detail on small screens.
        Slow zoom-in for constant visual energy.
        """
        return (
            f'scale={w}:{h}:force_original_aspect_ratio=increase,'
            f'crop={w}:{h},'
            # Hyper color: high saturation + strong contrast
            f'eq=saturation=1.8:contrast=1.45:brightness=0.05,'
            # Aggressive sharpening for mobile clarity
            f'unsharp=7:7:1.8:7:7:0.8,'
            # Constant zoom-in for energy
            f"zoompan=z='if(eq(on,1),1.0,min(zoom+0.0015,1.08))'"
            f":d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={w}x{h}:fps=30"
        )

    def _flow_vfilters(self, w: int, h: int) -> str:
        """
        FLOW EDIT — Smooth, dreamy, mesmerizing.

        Warm cinematic color grade (boosted reds/yellows, muted blues).
        Soft vignette for depth and focus.
        Very gentle Ken Burns drift (barely noticeable).
        Slight softness/glow for dreamy feel.
        """
        return (
            f'scale={w}:{h}:force_original_aspect_ratio=increase,'
            f'crop={w}:{h},'
            # Warm color grading: boost reds, mute blues
            f'colorchannelmixer=rr=1.1:gg=1.02:bb=0.82:ra=0.04,'
            # Gentle saturation boost + slight warmth
            f'eq=saturation=1.15:contrast=1.05:brightness=0.02,'
            # Dreamy soft glow via slight unsharp with wide radius
            f'unsharp=13:13:0.3:13:13:0.0,'
            # Slow Ken Burns drift
            f"zoompan=z='min(zoom+0.0003,1.03)'"
            f":d=1:x='iw/2-(iw/zoom/2)+sin(on/120)*20'"
            f":y='ih/2-(ih/zoom/2)+cos(on/150)*15'"
            f":s={w}x{h}:fps=30,"
            # Deep vignette for cinematic depth
            f'vignette=PI/4'
        )

    def _hard_vfilters(self, w: int, h: int) -> str:
        """
        HARD EDIT — Aggressive, punchy, dark energy.

        Near-monochrome (very low saturation) for gritty look.
        Extreme contrast with crushed blacks.
        Cyan/teal tint in shadows (modern dark anime aesthetic).
        Heavy sharpening for aggressive edge detail.
        """
        return (
            f'scale={w}:{h}:force_original_aspect_ratio=increase,'
            f'crop={w}:{h},'
            # Near-monochrome + extreme contrast + dark
            f'eq=saturation=0.25:contrast=1.7:brightness=-0.06,'
            # Cyan/teal shadow tint
            f'colorchannelmixer=rr=0.8:gg=0.9:bb=1.2:ba=0.05:ga=0.02,'
            # Crushed blacks curve
            f'curves=m=0/0:0.2/0.05:0.5/0.42:0.8/0.85:1/1,'
            # Aggressive sharpening
            f'unsharp=5:5:2.5:5:5:1.5'
        )

    def _cinematic_vfilters(self, w: int, h: int) -> str:
        """
        CINEMATIC/AMV — Film-quality storytelling look.

        Letterbox bars (cinematic aspect feel).
        Film grain noise for analog texture.
        Muted warm palette with blue shadows.
        Strong vignette for theatrical depth.
        """
        bar_h = int(h * 0.08)
        return (
            f'scale={w}:{h}:force_original_aspect_ratio=increase,'
            f'crop={w}:{h},'
            # Muted warm palette: slight orange highlights, blue shadows
            f'colorchannelmixer=rr=1.06:gg=0.95:bb=0.85:ba=0.04:ga=-0.02,'
            # Muted saturation + medium contrast
            f'eq=saturation=0.75:contrast=1.2:brightness=-0.03,'
            # Film grain
            f'noise=alls=12:allf=t+u,'
            # Deep vignette
            f'vignette=PI/3,'
            # Letterbox bars
            f'drawbox=x=0:y=0:w={w}:h={bar_h}:color=black:t=fill,'
            f'drawbox=x=0:y={h - bar_h}:w={w}:h={bar_h}:color=black:t=fill'
        )

    def _glitch_vfilters(self, w: int, h: int) -> str:
        """
        GLITCH/CYBERPUNK — Digital chaos, neon-drenched.

        Extreme RGB chromatic aberration (big channel split).
        Neon-boosted saturation for cyberpunk glow.
        Heavy sharpening for digital edge.
        High contrast for neon pop.
        """
        return (
            f'scale={w}:{h}:force_original_aspect_ratio=increase,'
            f'crop={w}:{h},'
            # Neon colors: high saturation + strong contrast + brightness
            f'eq=contrast=1.6:saturation=1.7:brightness=0.04,'
            # Extreme RGB chromatic aberration
            f'rgbashift=rh=-10:rv=4:bh=10:bv=-4,'
            # Heavy digital sharpening
            f'unsharp=7:7:3.0:7:7:1.5,'
            # Neon color push (boost magenta/cyan)
            f'colorchannelmixer=rr=1.15:gg=0.9:bb=1.2:ra=0.03:ba=0.03'
        )

    # ══════════════════════════════════════════════════════════════════
    #  AUDIO FILTERS — Each template sounds different
    # ══════════════════════════════════════════════════════════════════

    def _velocity_afilters(self, speed: float) -> str:
        """Bass boost + aggressive compression for impact punch."""
        f = f'loudnorm=I={self.loudness}:TP=-1:LRA=11,aformat=sample_rates=48000'
        f += self._atempo(speed)
        f += ',bass=g=10:f=80,acompressor=threshold=-18dB:ratio=6:attack=3:release=40'
        return f

    def _flow_afilters(self) -> str:
        """Clean, warm, smooth audio. No tempo change."""
        return (
            f'loudnorm=I={self.loudness}:TP=-1:LRA=11,'
            f'aformat=sample_rates=48000,'
            f'treble=g=-2:f=8000'
        )

    def _hard_afilters(self, speed: float) -> str:
        """Punchy, compressed, boosted mids for aggressive energy."""
        f = f'loudnorm=I={self.loudness}:TP=-1:LRA=11,aformat=sample_rates=48000'
        f += self._atempo(speed)
        f += ',bass=g=6:f=120,treble=g=4:f=4000'
        f += ',acompressor=threshold=-16dB:ratio=5:attack=2:release=30'
        return f

    def _cinematic_afilters(self, speed: float) -> str:
        """Rich, theatrical audio with warmth."""
        f = f'loudnorm=I={self.loudness}:TP=-1:LRA=11,aformat=sample_rates=48000'
        f += self._atempo(speed)
        f += ',bass=g=3:f=100,treble=g=-1:f=6000'
        return f

    def _glitch_afilters(self, speed: float) -> str:
        """Distorted, heavy bass, digital crunch."""
        f = f'loudnorm=I={self.loudness}:TP=-1:LRA=11,aformat=sample_rates=48000'
        f += self._atempo(speed)
        f += ',bass=g=12:f=60,acompressor=threshold=-12dB:ratio=8:attack=1:release=20'
        return f

    @staticmethod
    def _atempo(speed: float) -> str:
        """Build atempo filter chain for any speed value."""
        if abs(speed - 1.0) < 0.01:
            return ''
        # atempo accepts 0.5-100.0; chain for extreme values
        parts = []
        remaining = speed
        while remaining < 0.5:
            parts.append(',atempo=0.5')
            remaining /= 0.5
        while remaining > 2.0:
            parts.append(',atempo=2.0')
            remaining /= 2.0
        if abs(remaining - 1.0) > 0.01:
            parts.append(f',atempo={remaining:.4f}')
        return ''.join(parts)

    # ══════════════════════════════════════════════════════════════════
    #  SEGMENT RENDERING
    # ══════════════════════════════════════════════════════════════════

    def _render_segment(
        self, start_s: float, end_s: float,
        aspect: str, template: str, speed: float = 1.0
    ) -> str:
        """Render a single segment with template-specific filters. No fades."""
        w, h = self._dims(aspect)
        raw_duration = end_s - start_s

        # Template-specific video filters
        vf_map = {
            'anime_hype': self._velocity_vfilters,
            'clean_flow': self._flow_vfilters,
            'hard_cuts': self._hard_vfilters,
            'cinematic': self._cinematic_vfilters,
            'glitch': self._glitch_vfilters,
        }
        vf_fn = vf_map.get(template)
        vf = vf_fn(w, h) if vf_fn else (
            f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}'
        )

        # Speed change via setpts
        if abs(speed - 1.0) > 0.01:
            vf += f',setpts=PTS/{speed:.4f}'

        vf = f'[0:v]{vf}[v]'

        # Template-specific audio filters
        af_map = {
            'anime_hype': lambda: self._velocity_afilters(speed),
            'clean_flow': lambda: self._flow_afilters(),
            'hard_cuts': lambda: self._hard_afilters(speed),
            'cinematic': lambda: self._cinematic_afilters(speed),
            'glitch': lambda: self._glitch_afilters(speed),
        }
        af_fn = af_map.get(template)
        af = af_fn() if af_fn else (
            f'loudnorm=I={self.loudness}:TP=-1:LRA=11,aformat=sample_rates=48000'
        )
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

    # ══════════════════════════════════════════════════════════════════
    #  SEAMLESS TRANSITIONS — xfade (NO BLACK FRAMES)
    # ══════════════════════════════════════════════════════════════════

    def _xfade_concat(self, segment_files: List[str], template: str,
                      aspect: str, output: str) -> str:
        """
        Join segments using FFmpeg xfade filter for SEAMLESS transitions.
        No black frames, no flash clips — pure video blending.

        Each template uses a different xfade transition type:
        - anime_hype:  fadewhite (0.08s) — near-instant white flash impact
        - clean_flow:  dissolve  (0.25s) — smooth crossfade
        - hard_cuts:   [none]    (0.00s) — raw hard cut, no transition
        - cinematic:   fade      (0.15s) — brief elegant fade
        - glitch:      pixelize  (0.06s) — digital pixel dissolve
        """
        if len(segment_files) == 1:
            shutil.move(segment_files[0], output)
            return output

        # Template-specific xfade configuration
        xfade_config = {
            'anime_hype': ('fadewhite', 0.08),
            'clean_flow': ('dissolve', 0.25),
            'hard_cuts': (None, 0.0),
            'cinematic': ('fade', 0.15),
            'glitch': ('pixelize', 0.06),
        }
        xfade_type, xfade_dur = xfade_config.get(template, ('fade', 0.1))

        # Hard cuts: raw concat with zero transition
        if xfade_type is None or xfade_dur <= 0:
            return self._hard_concat(segment_files, output)

        # Get duration of each segment
        durations = [self._probe_duration(f) for f in segment_files]

        n = len(segment_files)

        # Build ffmpeg inputs
        inputs = []
        for f in segment_files:
            inputs.extend(['-i', f])

        # Build filter_complex for xfade chain
        filter_parts = []

        # Normalize all video/audio streams for consistent xfade
        for i in range(n):
            filter_parts.append(f'[{i}:v]settb=AVTB,fps=30,format=yuv420p[v{i}]')
            filter_parts.append(
                f'[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo[a{i}]'
            )

        # Chain xfade operations
        cumulative = durations[0]
        prev_v = 'v0'
        prev_a = 'a0'

        for i in range(1, n):
            offset = max(0.0, cumulative - xfade_dur)
            is_last = (i == n - 1)
            out_v = 'outv' if is_last else f'xv{i}'
            out_a = 'outa' if is_last else f'xa{i}'

            filter_parts.append(
                f'[{prev_v}][v{i}]xfade=transition={xfade_type}'
                f':duration={xfade_dur}:offset={offset:.4f}[{out_v}]'
            )
            filter_parts.append(
                f'[{prev_a}][a{i}]acrossfade=d={xfade_dur}'
                f':c1=tri:c2=tri[{out_a}]'
            )

            cumulative += durations[i] - xfade_dur
            prev_v = out_v
            prev_a = out_a

        cmd = ['ffmpeg'] + inputs + [
            '-filter_complex', ';'.join(filter_parts),
            '-map', '[outv]', '-map', '[outa]',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
            '-profile:v', 'high', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k',
            '-movflags', '+faststart',
            '-y', output
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(f"xfade failed, falling back to hard concat: {result.stderr[:300]}")
            return self._hard_concat(segment_files, output)

        return output

    def _hard_concat(self, segment_files: List[str], output: str) -> str:
        """Raw concatenation with zero transition — for hard_cuts template."""
        temp_dir = os.path.dirname(output)
        concat_id = random.randint(10000, 99999)
        concat_list = os.path.join(temp_dir, f"_concat_{concat_id}.txt")

        with open(concat_list, 'w') as f:
            for seg_file in segment_files:
                f.write(f"file '{seg_file}'\n")

        # Try stream copy first (fastest)
        cmd = [
            'ffmpeg', '-f', 'concat', '-safe', '0', '-i', concat_list,
            '-c', 'copy', '-movflags', '+faststart',
            '-y', output
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            # Fallback: re-encode
            cmd = [
                'ffmpeg', '-f', 'concat', '-safe', '0', '-i', concat_list,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
                '-profile:v', 'high', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k',
                '-movflags', '+faststart',
                '-y', output
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"Hard concat failed: {result.stderr[:500]}")

        if os.path.exists(concat_list):
            os.remove(concat_list)

        return output

    # ══════════════════════════════════════════════════════════════════
    #  FINAL FADES (intro/outro only)
    # ══════════════════════════════════════════════════════════════════

    def _apply_final_fades(self, input_path: str, output: str, template: str) -> str:
        """Apply ONLY intro/outro fades to the final assembled clip."""
        fade_config = {
            'anime_hype': (0.1, 0.1),       # Snappy — minimal
            'clean_flow': (0.5, 0.7),        # Smooth — gentle
            'hard_cuts': (0.0, 0.0),         # None — raw energy
            'cinematic': (0.8, 1.0),         # Dramatic — slow
            'glitch': (0.05, 0.05),          # Digital — instant
        }
        fade_in, fade_out = fade_config.get(template, (0.2, 0.2))

        if fade_in <= 0 and fade_out <= 0:
            shutil.move(input_path, output)
            return output

        total_dur = self._probe_duration(input_path)

        vf_parts = []
        af_parts = []

        if fade_in > 0:
            vf_parts.append(f'fade=t=in:st=0:d={fade_in}')
            af_parts.append(f'afade=t=in:st=0:d={fade_in}')

        if fade_out > 0:
            out_start = max(0, total_dur - fade_out)
            vf_parts.append(f'fade=t=out:st={out_start:.4f}:d={fade_out}')
            af_parts.append(f'afade=t=out:st={out_start:.4f}:d={fade_out}')

        cmd = [
            'ffmpeg', '-i', input_path,
            '-vf', ','.join(vf_parts),
            '-af', ','.join(af_parts),
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
            '-profile:v', 'high', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k',
            '-movflags', '+faststart',
            '-y', output
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # If fades fail, just use the input as-is
            logger.warning(f"Final fade failed, using raw: {result.stderr[:200]}")
            shutil.move(input_path, output)

        return output

    # ══════════════════════════════════════════════════════════════════
    #  SPEED RAMPING — Per-template velocity profiles
    # ══════════════════════════════════════════════════════════════════

    def _split_at_peaks(
        self, start_s: float, end_s: float,
        motion_peaks: List[Dict],
        peak_speed: float, normal_speed: float,
        peak_window: float = 1.2
    ) -> List[Dict]:
        """
        Split a segment into sub-segments with velocity-style speed ramps.
        Slow on impacts (peak_speed < 1.0), fast between (normal_speed > 1.0).
        """
        peak_times = sorted(set(p['time'] for p in motion_peaks))
        sub_segments = []
        current = start_s

        for peak_time in peak_times:
            peak_start = max(current, peak_time - peak_window / 2)
            peak_end = min(end_s, peak_time + peak_window / 2)

            # Fast segment before peak (build-up rush)
            if peak_start > current + 0.3:
                sub_segments.append({
                    'start_s': current,
                    'end_s': peak_start,
                    'speed': normal_speed
                })

            # Slow-mo at peak (the money shot)
            if peak_end > peak_start + 0.2:
                sub_segments.append({
                    'start_s': peak_start,
                    'end_s': peak_end,
                    'speed': peak_speed
                })

            current = peak_end

        # Fast tail after last peak
        if current < end_s - 0.3:
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

    # ══════════════════════════════════════════════════════════════════
    #  MAIN RENDER ORCHESTRATOR
    # ══════════════════════════════════════════════════════════════════

    def render(self, segments: List[Dict], template_name: str, aspect: str) -> str:
        """
        Main render pipeline:
        1. Trim segments to max_duration
        2. Apply template-specific speed ramps
        3. Render each sub-segment with template filters
        4. Join with xfade (seamless, NO black frames)
        5. Apply final intro/outro fades only
        """
        w, h = self._dims(aspect)

        # ── 1. Trim to max_duration ──
        trimmed = []
        total = 0.0
        for seg in segments:
            seg_dur = seg['end_s'] - seg['start_s']
            if total + seg_dur > self.max_duration:
                remaining = self.max_duration - total
                if remaining > 0.5:
                    trimmed.append({
                        'start_s': seg['start_s'],
                        'end_s': seg['start_s'] + remaining
                    })
                break
            trimmed.append(seg)
            total += seg_dur

        if not trimmed:
            trimmed = segments[:1]

        # ── 2. Template speed configurations ──
        # Each template has VERY different pacing:
        speed_config = {
            'anime_hype': {
                # VELOCITY: Extreme S-curve — 0.3x slow-mo on impacts, 2.2x rush between
                'peak_speed': 0.3,
                'normal_speed': 2.2,
                'peak_window': 1.2,
                'use_ramps': True,
            },
            'clean_flow': {
                # FLOW: Constant smooth speed, no velocity changes
                'normal_speed': 1.0,
                'use_ramps': False,
            },
            'hard_cuts': {
                # HARD: Slightly fast constant, aggressive pacing
                'normal_speed': 1.3,
                'use_ramps': False,
            },
            'cinematic': {
                # CINEMATIC: Dramatic slow-mo on peaks, normal elsewhere
                'peak_speed': 0.4,
                'normal_speed': 1.0,
                'peak_window': 2.0,
                'use_ramps': True,
            },
            'glitch': {
                # GLITCH: Random speed stutters — erratic digital feel
                'peak_speed': 0.5,
                'normal_speed': 1.6,
                'peak_window': 0.5,
                'use_ramps': True,
            },
        }
        speeds = speed_config.get(template_name, {'normal_speed': 1.0, 'use_ramps': False})

        # ── 3. Render all segments ──
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

        # ── 4. Join with xfade (seamless transitions) ──
        temp_dir = os.path.dirname(self.output_path)
        join_id = random.randint(10000, 99999)

        if len(rendered_parts) == 1:
            # Single segment — just move it
            joined_path = rendered_parts[0]
            temp_files.remove(joined_path)
        else:
            joined_path = os.path.join(temp_dir, f"_autoedit_joined_{join_id}.mp4")
            self._xfade_concat(rendered_parts, template_name, aspect, joined_path)
            temp_files.append(joined_path)

        # ── 5. Apply final intro/outro fades ──
        self._apply_final_fades(joined_path, self.output_path, template_name)

        # If the output and joined are different, joined is in temp_files
        # If they're the same (single segment), the move already happened

        # ── Cleanup temp files ──
        for f in temp_files:
            try:
                if os.path.exists(f) and f != self.output_path:
                    os.remove(f)
            except OSError:
                pass

        return self.output_path


# ══════════════════════════════════════════════════════════════════════
#  CELERY TASK
# ══════════════════════════════════════════════════════════════════════

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
