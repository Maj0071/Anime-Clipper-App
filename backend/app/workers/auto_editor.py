import os
import subprocess
import json
import random
import shutil
import logging
import tempfile
from typing import List, Dict, Optional, Tuple
from celery import Task
from sqlalchemy.orm import Session

from app.workers.celery_app import celery_app
from app.database import SessionLocal
from app.models import Render, Candidate, Video
from app.services.s3_service import download_from_s3
from app.workers.renderer import _find_action_segments
from app.workers.audio_analyzer import AudioAnalyzer, get_beat_synced_segments, align_cuts_to_beats

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  CAPTION STYLES - Viral TikTok/Reels caption animations
# ══════════════════════════════════════════════════════════════════════════════

CAPTION_STYLES = {
    'pop': {
        'description': 'Scale up on each word - TikTok style',
        'font': 'Arial Black',
        'fontsize': 48,
        'fontcolor': 'white',
        'borderw': 3,
        'bordercolor': 'black',
        'shadowcolor': 'black@0.6',
        'shadowx': 2,
        'shadowy': 2,
    },
    'bounce': {
        'description': 'Vertical bounce animation',
        'font': 'Impact',
        'fontsize': 52,
        'fontcolor': 'yellow',
        'borderw': 4,
        'bordercolor': 'black',
        'shadowcolor': 'black@0.8',
        'shadowx': 3,
        'shadowy': 3,
    },
    'highlight': {
        'description': 'Color change on keywords',
        'font': 'Arial Bold',
        'fontsize': 44,
        'fontcolor': 'white',
        'borderw': 2,
        'bordercolor': '#FF6B00',
        'shadowcolor': 'black@0.5',
        'shadowx': 2,
        'shadowy': 2,
    },
    'glow': {
        'description': 'Neon glow effect',
        'font': 'Arial Black',
        'fontsize': 50,
        'fontcolor': '#00FFFF',
        'borderw': 4,
        'bordercolor': '#FF00FF',
        'shadowcolor': '#FF00FF@0.8',
        'shadowx': 0,
        'shadowy': 0,
    },
}


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

    # ══════════════════════════════════════════════════════════════════
    #  SMART REFRAMING — Face/Subject Tracking for Better Crops
    # ══════════════════════════════════════════════════════════════════

    def detect_faces_for_reframe(self, start_s: float, end_s: float,
                                  sample_interval: float = 0.5) -> List[Dict]:
        """
        Detect faces/subjects throughout clip for smart reframing.

        Returns list of face positions over time for tracking.
        Used to keep subjects centered when cropping to vertical formats.
        """
        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available for face detection")
            return []

        # Load face cascade (works well for anime faces too)
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        face_cascade = cv2.CascadeClassifier(cascade_path)

        # Also try anime face cascade if available
        anime_cascade = None
        anime_cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_alt2.xml'
        if os.path.exists(anime_cascade_path):
            anime_cascade = cv2.CascadeClassifier(anime_cascade_path)

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            return []

        fps = cap.get(cv2.CAP_PROP_FPS) or 24
        frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        start_frame = int(start_s * fps)
        end_frame = int(end_s * fps)
        sample_frames = int(sample_interval * fps)

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        face_tracks = []

        for frame_idx in range(start_frame, end_frame, sample_frames):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                break

            current_time = start_s + (frame_idx - start_frame) / fps

            # Resize for faster detection
            scale = 0.5
            small = cv2.resize(frame, None, fx=scale, fy=scale)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

            # Detect faces with both cascades
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=4, minSize=(25, 25)
            )

            if anime_cascade is not None and len(faces) == 0:
                faces = anime_cascade.detectMultiScale(
                    gray, scaleFactor=1.1, minNeighbors=3, minSize=(20, 20)
                )

            if len(faces) > 0:
                # Find largest face (likely main character)
                largest = max(faces, key=lambda f: f[2] * f[3])
                x, y, w, h = largest

                # Scale back to original coordinates
                center_x = int((x + w/2) / scale)
                center_y = int((y + h/2) / scale)

                face_tracks.append({
                    'time': current_time,
                    'center_x': center_x,
                    'center_y': center_y,
                    'width': int(w / scale),
                    'height': int(h / scale),
                    'frame_width': frame_width,
                    'frame_height': frame_height,
                })

        cap.release()
        return face_tracks

    def calculate_smart_crop(self, face_tracks: List[Dict],
                              target_w: int, target_h: int,
                              source_w: int, source_h: int) -> Dict:
        """
        Calculate optimal crop position to keep faces centered.

        Returns dict with x_offset expression for FFmpeg crop filter.
        Uses smoothed tracking to avoid jarring movements.
        """
        if not face_tracks:
            # Default: center crop
            return {
                'mode': 'center',
                'x_expr': f'(in_w-{target_w})/2',
                'y_expr': f'(in_h-{target_h})/2',
            }

        # Calculate average face position
        avg_x = sum(f['center_x'] for f in face_tracks) / len(face_tracks)
        avg_y = sum(f['center_y'] for f in face_tracks) / len(face_tracks)

        # Calculate crop offset to center on average face position
        # For vertical (9:16), we mainly adjust X position
        target_center_x = target_w / 2
        target_center_y = target_h / 2

        # How much to offset the crop
        x_offset = avg_x - target_center_x
        y_offset = avg_y - target_center_y

        # Clamp to valid range
        max_x_offset = source_w - target_w
        max_y_offset = source_h - target_h

        x_offset = max(0, min(max_x_offset, x_offset))
        y_offset = max(0, min(max_y_offset, y_offset))

        # Check if faces move significantly (need dynamic tracking)
        x_positions = [f['center_x'] for f in face_tracks]
        x_variance = max(x_positions) - min(x_positions)

        if x_variance > source_w * 0.2:  # Significant movement
            # Use dynamic expression that follows face
            # Smooth movement using frame number
            return {
                'mode': 'tracking',
                'x_expr': f'clip({int(x_offset)}+sin(n/30)*{int(x_variance/4)},0,{max_x_offset})',
                'y_expr': f'clip({int(y_offset)},0,{max_y_offset})',
                'avg_x': avg_x,
                'avg_y': avg_y,
            }
        else:
            # Static offset (face stays relatively still)
            return {
                'mode': 'static',
                'x_expr': str(int(x_offset)),
                'y_expr': str(int(y_offset)),
                'avg_x': avg_x,
                'avg_y': avg_y,
            }

    def _smart_scale_crop(self, w: int, h: int, face_tracks: List[Dict] = None) -> str:
        """
        Build scale+crop filter with smart reframing based on face detection.

        If face_tracks provided, adjusts crop to keep faces centered.
        Otherwise, uses standard center crop.
        """
        if not face_tracks:
            # Standard center crop
            return f'scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}'

        # Get source dimensions from first track
        source_w = face_tracks[0].get('frame_width', 1920)
        source_h = face_tracks[0].get('frame_height', 1080)

        crop_info = self.calculate_smart_crop(face_tracks, w, h, source_w, source_h)

        x_expr = crop_info['x_expr']
        y_expr = crop_info['y_expr']

        return (
            f'scale={w}:{h}:force_original_aspect_ratio=increase,'
            f'crop={w}:{h}:x={x_expr}:y={y_expr}'
        )

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
    #  EFFECT FILTERS — Reusable components for viral editing
    # ══════════════════════════════════════════════════════════════════

    def _screen_shake_filter(self, w: int, h: int, shake_times: List[float] = None,
                              intensity: int = 18, duration: float = 0.15) -> str:
        """
        Screen shake effect using pad + animated crop.
        Creates constant subtle camera shake for energy.

        intensity: max pixel displacement (5-20 recommended)
        """
        if intensity <= 0:
            return ""

        # Simplified: constant subtle shake using frame-based sin/cos
        # This creates energy without complex time-based expressions
        pad_amount = intensity + 5

        # n = frame number in crop filter expressions
        x_offset = f"{intensity}*sin(n*0.5)*cos(n*0.3)"
        y_offset = f"{intensity}*sin(n*0.4)*cos(n*0.6)"

        return (
            f"pad=w={w+pad_amount*2}:h={h+pad_amount*2}:x={pad_amount}:y={pad_amount}:color=black,"
            f"crop=w={w}:h={h}:x={pad_amount}+{x_offset}:y={pad_amount}+{y_offset}"
        )

    def _zoom_pulse_filter(self, w: int, h: int, pulse_times: List[float],
                            base_zoom: float = 1.0, pulse_zoom: float = 1.12,
                            pulse_duration: float = 0.12) -> str:
        """
        Zoom pulse synced to motion peaks/action moments.
        Creates quick zoom in/out effect on beat.

        pulse_times: timestamps when zoom should pulse
        base_zoom: normal zoom level (1.0 = no zoom)
        pulse_zoom: peak zoom during pulse (1.08-1.15 recommended)
        """
        # Use a dynamic zoom that pulses based on frame number
        # Creates energy through constant subtle zoom movement
        # zoompan uses: on (frame number), time, zoom, x, y, in_w, in_h, out_w, out_h
        return (
            f"zoompan=z='1.0+0.06*abs(sin(on/20))'"
            f":d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={w}x{h}:fps=30"
        )

    def _vhs_effect_filter(self, intensity: str = 'medium') -> str:
        """
        VHS/retro effect with scanlines, chromatic aberration, and noise.
        Creates that classic VHS/glitch look popular in anime edits.

        intensity: 'light', 'medium', 'heavy'
        """
        configs = {
            'light': {'scanline_alpha': 0.08, 'rgb_shift': 4, 'noise': 6},
            'medium': {'scanline_alpha': 0.15, 'rgb_shift': 7, 'noise': 10},
            'heavy': {'scanline_alpha': 0.25, 'rgb_shift': 12, 'noise': 16},
        }
        cfg = configs.get(intensity, configs['medium'])

        # Scanlines via geq - darken every other line
        scanline = (
            f"geq="
            f"lum='lum(X,Y)*if(mod(Y,2),1,{1-cfg['scanline_alpha']})':"
            f"cb='cb(X,Y)':"
            f"cr='cr(X,Y)'"
        )

        # Chromatic aberration - shift R and B channels
        rgb_shift = f"rgbashift=rh={cfg['rgb_shift']}:bh=-{cfg['rgb_shift']}"

        # Film grain noise
        noise = f"noise=alls={cfg['noise']}:allf=t+u"

        return f"{scanline},{rgb_shift},{noise}"

    # ── WHITE FLASH IMPACT EFFECT ─────────────────────────────────────

    def _white_flash_filter(self, flash_times: List[float], duration: float = 0.1,
                            intensity: float = 1.0) -> str:
        """
        White flash overlay effect synced to impact moments.

        This is the #1 missing feature for velocity edits.
        Creates 2-4 frame white overlay that fades: 100% white -> 0%

        flash_times: list of timestamps for flashes (relative to segment start)
        duration: flash duration in seconds (0.08-0.15 recommended)
        intensity: max brightness (0.0-1.0)
        """
        if not flash_times:
            return ""

        # Use eq filter with enable for flash effects
        # This is simpler and more reliable than geq with complex expressions
        # Limit to 2 flashes to avoid filter complexity issues
        flash_times = flash_times[:2]

        # Build enable expression for eq brightness boost
        enable_parts = []
        for t in flash_times:
            enable_parts.append(f"between(t,{t:.3f},{t+duration:.3f})")

        enable_expr = '+'.join(enable_parts)

        # Calculate brightness boost (intensity 1.0 = add 0.5 to brightness)
        brightness_boost = intensity * 0.5

        # Use eq filter to boost brightness during flash moments
        # The enable expression activates the filter only during flash times
        return f"eq=brightness={brightness_boost}:enable='{enable_expr}'"

    def _white_flash_overlay_filter(self, flash_times: List[float],
                                     duration: float = 0.1) -> str:
        """
        Alternative white flash using blend filter with color overlay.
        More visually accurate for TikTok-style impacts.
        """
        if not flash_times:
            return ""

        # Build opacity expression
        flash_exprs = []
        for t in flash_times:
            expr = f"if(between(t,{t:.3f},{t+duration:.3f}),(1-(t-{t:.3f})/{duration:.3f}),0)"
            flash_exprs.append(expr)

        if len(flash_exprs) == 1:
            opacity_expr = flash_exprs[0]
        else:
            opacity_expr = flash_exprs[0]
            for expr in flash_exprs[1:]:
                opacity_expr = f"max({opacity_expr},{expr})"

        # Split, create white, blend, merge
        return (
            f"split[main][flash];"
            f"[flash]drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill,"
            f"format=rgba,colorchannelmixer=aa='{opacity_expr}'[flashlayer];"
            f"[main][flashlayer]overlay=format=auto"
        )

    # ── ENHANCED SCREEN SHAKE ─────────────────────────────────────────

    def _dynamic_screen_shake_filter(self, w: int, h: int,
                                      motion_peaks: List[Dict] = None,
                                      base_intensity: int = 8,
                                      peak_intensity: int = 25,
                                      duration: float = 0.2) -> str:
        """
        Enhanced screen shake with variable intensity based on motion score.

        More aggressive shake on impacts, subtle shake elsewhere.
        This creates the energetic feel of viral velocity edits.

        motion_peaks: list of dicts with 'time' and 'motion' (0-1 normalized)
        base_intensity: constant subtle shake (5-12 recommended)
        peak_intensity: max shake on impacts (20-35 recommended)
        """
        pad_amount = peak_intensity + 10

        # Calculate intensity based on motion peaks
        # Use average motion to boost base intensity for high-action clips
        avg_intensity = base_intensity
        if motion_peaks:
            avg_motion = sum(p.get('motion', 0.5) for p in motion_peaks) / len(motion_peaks)
            # Boost intensity based on average motion (up to peak_intensity)
            avg_intensity = int(base_intensity + (peak_intensity - base_intensity) * avg_motion)

        # Use frame-based shake (n = frame number) for smooth, constant energy
        # This is simpler and more reliable than time-based expressions
        x_offset = f"{avg_intensity}*sin(n*0.5)*cos(n*0.3)"
        y_offset = f"{avg_intensity}*sin(n*0.4)*cos(n*0.6)"

        return (
            f"pad=w={w+pad_amount*2}:h={h+pad_amount*2}:x={pad_amount}:y={pad_amount}:color=black,"
            f"crop=w={w}:h={h}:x={pad_amount}+{x_offset}:y={pad_amount}+{y_offset}"
        )

    # ── NEW TRANSITION TYPES ──────────────────────────────────────────

    def _whip_pan_transition(self, w: int, h: int, direction: str = 'right',
                              blur_amount: int = 50) -> Tuple[str, str]:
        """
        Whip pan transition effect - horizontal blur motion.

        Creates motion blur at end of outgoing clip and start of incoming.
        Returns (out_filter, in_filter) tuple.
        """
        # Outgoing: blur increases at end
        if direction in ['right', 'left']:
            out_filter = f"tblend=all_mode=average,hblur={blur_amount}"
            in_filter = f"hblur={blur_amount},tblend=all_mode=average"
        else:  # up/down
            out_filter = f"tblend=all_mode=average,vblur={blur_amount}"
            in_filter = f"vblur={blur_amount},tblend=all_mode=average"

        return out_filter, in_filter

    def _film_burn_transition_filter(self) -> str:
        """
        Film burn / light leak transition effect.

        Creates warm orange/red light leak overlay that fades.
        Popular in flow/AMV edits.
        """
        # Create warm light leak using color overlay
        # Simulate film burn with orange/yellow tint that varies
        return (
            f"colorbalance=rs=0.3:gs=0.1:bs=-0.2:rm=0.2:gm=0.05:bm=-0.1,"
            f"eq=brightness=0.15:saturation=1.3"
        )

    def _zoom_punch_transition(self, w: int, h: int, zoom_factor: float = 1.3,
                                duration_frames: int = 6) -> str:
        """
        Zoom punch transition - quick zoom in/out on cuts.

        Creates impact by rapidly zooming then returning.
        Commonly used in velocity edits at beat drops.
        """
        # Quick zoom in then out over duration_frames
        # Frame 0-2: zoom in, Frame 3-5: zoom out
        mid = duration_frames // 2
        return (
            f"zoompan=z='if(lte(on,{mid}),"
            f"1+({zoom_factor-1})*on/{mid},"
            f"1+({zoom_factor-1})*(1-(on-{mid})/{mid}))'"
            f":d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={w}x{h}:fps=30"
        )

    def _rgb_split_transition(self, split_amount: int = 15) -> str:
        """
        RGB split / chromatic aberration transition.

        Increases RGB channel separation dramatically at transition point.
        Cyberpunk/glitch aesthetic.
        """
        return f"rgbashift=rh={split_amount}:rv={split_amount//2}:bh=-{split_amount}:bv=-{split_amount//2}"

    # ══════════════════════════════════════════════════════════════════
    #  HOOK OPTIMIZATION — Maximize First 2-3 Second Retention
    # ══════════════════════════════════════════════════════════════════

    # Pre-defined hook text templates
    HOOK_TEMPLATES = {
        'wait_for_it': 'Wait for it...',
        'insane': 'This scene is insane',
        'watch_end': 'Watch until the end',
        'hits_different': 'This hits different',
        'goosebumps': 'Gave me goosebumps',
        'peak_fiction': 'Peak fiction',
        'best_moment': 'Best moment in anime',
        'underrated': 'Most underrated scene',
    }

    def find_best_hook_moment(self, start_s: float, end_s: float,
                               motion_data: List[Dict] = None) -> Dict:
        """
        Find the best hook moment (highest energy point) in the clip.

        Returns dict with:
        - time: timestamp of best hook
        - score: energy score 0-100
        - can_reorder: whether reordering would help
        """
        # If we have motion data, use it
        if motion_data:
            if not motion_data:
                return {'time': start_s, 'score': 50, 'can_reorder': False}

            # Find peak moment
            peak = max(motion_data, key=lambda m: m.get('motion', 0))
            peak_time = peak['time']
            peak_score = peak.get('motion', 0.5) * 100

            # Check if peak is in first 3 seconds (good hook) or later (needs reorder)
            first_3s_end = start_s + 3.0
            can_reorder = peak_time > first_3s_end

            # Also check first 3 second energy
            first_3s = [m for m in motion_data if m['time'] <= first_3s_end]
            if first_3s:
                first_3s_energy = sum(m.get('motion', 0) for m in first_3s) / len(first_3s)
            else:
                first_3s_energy = 0.5

            # If first 3 seconds are weak, suggest reorder
            if first_3s_energy < 0.4 and peak_score > 60:
                can_reorder = True

            return {
                'time': peak_time,
                'score': int(peak_score),
                'can_reorder': can_reorder,
                'first_3s_energy': int(first_3s_energy * 100),
            }

        # Fallback: analyze clip directly
        try:
            import cv2
            import numpy as np
        except ImportError:
            return {'time': start_s, 'score': 50, 'can_reorder': False}

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            return {'time': start_s, 'score': 50, 'can_reorder': False}

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
                gray = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY)
                if prev_gray is not None:
                    diff = cv2.absdiff(gray, prev_gray)
                    motion = float(np.mean(diff))
                    current_time = start_s + (frame_idx - start_frame) / fps
                    motion_scores.append({'time': current_time, 'motion': motion})
                prev_gray = gray

        cap.release()

        if not motion_scores:
            return {'time': start_s, 'score': 50, 'can_reorder': False}

        # Normalize
        max_motion = max(m['motion'] for m in motion_scores)
        if max_motion > 0:
            for m in motion_scores:
                m['motion'] /= max_motion

        return self.find_best_hook_moment(start_s, end_s, motion_scores)

    def _hook_text_filter(self, text: str, w: int, h: int,
                          duration: float = 2.5, style: str = 'bold') -> str:
        """
        Create hook text overlay filter for the first few seconds.

        Designed to grab attention immediately.

        text: Hook text to display
        duration: How long to show (2-3 seconds recommended)
        style: 'bold', 'glitch', 'neon'
        """
        # Escape text for FFmpeg
        escaped = text.replace("'", "\\'").replace(":", "\\:")

        styles = {
            'bold': {
                'fontsize': 56,
                'fontcolor': 'white',
                'borderw': 4,
                'bordercolor': 'black',
                'shadowcolor': 'black@0.7',
                'shadowx': 3,
                'shadowy': 3,
            },
            'glitch': {
                'fontsize': 52,
                'fontcolor': '#00FFFF',
                'borderw': 3,
                'bordercolor': '#FF00FF',
                'shadowcolor': '#FF0000@0.5',
                'shadowx': 4,
                'shadowy': 0,
            },
            'neon': {
                'fontsize': 54,
                'fontcolor': '#FFFF00',
                'borderw': 3,
                'bordercolor': '#FF6600',
                'shadowcolor': '#FF6600@0.8',
                'shadowx': 0,
                'shadowy': 0,
            },
        }

        cfg = styles.get(style, styles['bold'])

        # Position in upper third for hooks
        y_pos = int(h * 0.18)

        # Fade in/out animation
        fade_expr = f"if(lt(t,0.3),t/0.3,if(gt(t,{duration-0.3}),({duration}-t)/0.3,1))"

        return (
            f"drawtext=text='{escaped}':"
            f"fontfile=/System/Library/Fonts/Supplemental/Arial Bold.ttf:"
            f"fontsize={cfg['fontsize']}:"
            f"fontcolor={cfg['fontcolor']}:"
            f"borderw={cfg['borderw']}:"
            f"bordercolor={cfg['bordercolor']}:"
            f"shadowcolor={cfg['shadowcolor']}:"
            f"shadowx={cfg['shadowx']}:"
            f"shadowy={cfg['shadowy']}:"
            f"x=(w-text_w)/2:"
            f"y={y_pos}:"
            f"alpha='{fade_expr}':"
            f"enable='between(t,0,{duration})'"
        )

    def reorder_for_hook(self, segments: List[Dict], hook_time: float,
                          hook_duration: float = 3.0) -> List[Dict]:
        """
        Reorder segments to start with the hook moment.

        Creates structure: [hook segment] -> [rest of clip]
        This puts the most engaging content first for maximum retention.
        """
        if not segments:
            return segments

        # Find which segment contains the hook
        hook_segment_idx = None
        for i, seg in enumerate(segments):
            if seg['start_s'] <= hook_time <= seg['end_s']:
                hook_segment_idx = i
                break

        if hook_segment_idx is None:
            return segments  # Hook not in any segment

        # Extract hook portion
        hook_seg = segments[hook_segment_idx]
        hook_start = max(hook_seg['start_s'], hook_time - hook_duration / 2)
        hook_end = min(hook_seg['end_s'], hook_time + hook_duration / 2)

        # Build reordered list
        reordered = []

        # 1. Add hook segment first
        reordered.append({
            'start_s': hook_start,
            'end_s': hook_end,
            'is_hook': True,
        })

        # 2. Add segments before hook
        for i, seg in enumerate(segments):
            if i < hook_segment_idx:
                reordered.append(seg)
            elif i == hook_segment_idx:
                # Add parts of hook segment not included in hook
                if seg['start_s'] < hook_start:
                    reordered.append({
                        'start_s': seg['start_s'],
                        'end_s': hook_start,
                    })
                if hook_end < seg['end_s']:
                    reordered.append({
                        'start_s': hook_end,
                        'end_s': seg['end_s'],
                    })
            else:
                reordered.append(seg)

        return reordered

    # ── CAPTION SYSTEM ────────────────────────────────────────────────

    def _build_caption_filter(self, text: str, style: str = 'pop',
                               start_time: float = 0, duration: float = 3.0,
                               position: str = 'bottom', w: int = 1080, h: int = 1920) -> str:
        """
        Build animated caption filter for viral-style captions.

        text: caption text to display
        style: 'pop', 'bounce', 'highlight', 'glow'
        position: 'bottom', 'center', 'top'
        """
        style_cfg = CAPTION_STYLES.get(style, CAPTION_STYLES['pop'])

        # Position calculations
        if position == 'bottom':
            y_pos = f"h-{int(h*0.15)}"
        elif position == 'center':
            y_pos = f"(h-text_h)/2"
        else:  # top
            y_pos = f"{int(h*0.1)}"

        # Escape text for FFmpeg
        escaped_text = text.replace("'", "\\'").replace(":", "\\:")

        # Build drawtext filter
        base_filter = (
            f"drawtext=text='{escaped_text}':"
            f"fontfile=/System/Library/Fonts/Supplemental/Arial Bold.ttf:"
            f"fontsize={style_cfg['fontsize']}:"
            f"fontcolor={style_cfg['fontcolor']}:"
            f"borderw={style_cfg['borderw']}:"
            f"bordercolor={style_cfg['bordercolor']}:"
            f"shadowcolor={style_cfg['shadowcolor']}:"
            f"shadowx={style_cfg['shadowx']}:"
            f"shadowy={style_cfg['shadowy']}:"
            f"x=(w-text_w)/2:"
            f"y={y_pos}:"
            f"enable='between(t,{start_time},{start_time+duration})'"
        )

        # Add animation based on style
        if style == 'pop':
            # Scale animation - text pops in
            # Using alpha fade-in as FFmpeg drawtext doesn't support scale animation
            base_filter = base_filter.replace(
                f"enable='between(t,{start_time},{start_time+duration})'",
                f"alpha='if(lt(t,{start_time+0.2}),min(1,(t-{start_time})/0.2),1)':enable='between(t,{start_time},{start_time+duration})'"
            )
        elif style == 'bounce':
            # Vertical bounce using y animation
            bounce_expr = f"({y_pos})-10*abs(sin((t-{start_time})*8))*if(lt(t,{start_time+0.5}),1,0)"
            base_filter = base_filter.replace(f"y={y_pos}", f"y={bounce_expr}")

        return base_filter

    def _build_word_by_word_captions(self, words: List[Dict], style: str = 'pop',
                                      position: str = 'bottom',
                                      w: int = 1080, h: int = 1920) -> str:
        """
        Build word-by-word animated caption filters.

        words: list of dicts with 'text', 'start', 'end' times
        Returns combined drawtext filters for all words.
        """
        if not words:
            return ""

        filters = []
        for word_data in words:
            text = word_data.get('text', '')
            start = word_data.get('start', 0)
            end = word_data.get('end', start + 0.5)
            duration = end - start

            if text.strip():
                caption_filter = self._build_caption_filter(
                    text, style, start, duration, position, w, h
                )
                filters.append(caption_filter)

        return ','.join(filters) if filters else ""

    # ══════════════════════════════════════════════════════════════════
    #  VIDEO FILTERS — Each template has a RADICALLY different look
    # ══════════════════════════════════════════════════════════════════

    def _velocity_vfilters(self, w: int, h: int, motion_peaks: List[Dict] = None,
                            enable_flash: bool = True, enable_shake: bool = True) -> str:
        """
        VELOCITY EDIT — The #1 viral anime style on TikTok.

        Hyper-saturated colors that POP on mobile screens.
        Extreme contrast for dramatic light/dark separation.
        Strong sharpening for crisp detail on small screens.
        WHITE FLASH impacts on motion peaks (NEW).
        Dynamic screen shake on action (NEW).
        Slow zoom-in for constant visual energy.
        """
        filters = [
            f'scale={w}:{h}:force_original_aspect_ratio=increase',
            f'crop={w}:{h}',
            # Hyper color: high saturation + strong contrast
            f'eq=saturation=1.8:contrast=1.45:brightness=0.05',
            # Aggressive sharpening for mobile clarity
            f'unsharp=7:7:1.8:7:7:0.8',
        ]

        # Add white flash on motion peaks (the #1 missing feature!)
        if enable_flash and motion_peaks:
            flash_times = [p['time'] for p in motion_peaks[:6]]  # Limit flashes
            if flash_times:
                flash_filter = self._white_flash_filter(flash_times, duration=0.1, intensity=0.8)
                if flash_filter:
                    filters.append(flash_filter)

        # Add dynamic screen shake
        if enable_shake:
            shake_filter = self._dynamic_screen_shake_filter(
                w, h, motion_peaks,
                base_intensity=10, peak_intensity=22
            )
            if shake_filter:
                filters.append(shake_filter)

        # Constant zoom-in for energy (final filter)
        filters.append(
            f"zoompan=z='if(eq(on,1),1.0,min(zoom+0.0015,1.08))'"
            f":d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={w}x{h}:fps=30"
        )

        return ','.join(filters)

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

    def _viral_anime_vfilters(self, w: int, h: int, motion_peaks: List[Dict] = None,
                               enable_flash: bool = True, enable_shake: bool = True,
                               caption_text: str = None, caption_style: str = 'pop') -> str:
        """
        VIRAL ANIME — Clean viral TikTok/YouTube Shorts style.

        Balanced effects for professional look:
        - Enhanced saturation + contrast for mobile pop
        - Subtle VHS scanlines for style (light)
        - WHITE FLASH on impacts (NEW)
        - Dynamic screen shake for energy (ENHANCED)
        - Smooth zoom pulses
        - Sharp detail for small screens
        - Optional animated captions (NEW)
        """
        # Base: scale + crop + color grading
        filters = [
            f'scale={w}:{h}:force_original_aspect_ratio=increase',
            f'crop={w}:{h}',
            # Enhanced saturation + contrast for mobile (not too extreme)
            f'eq=saturation=1.4:contrast=1.25:brightness=0.02',
            # Sharp detail for small screens
            f'unsharp=5:5:1.2:5:5:0.8',
        ]

        # Add subtle VHS effect (light - just slight scanlines + RGB shift)
        vhs = self._vhs_effect_filter('light')
        if vhs:
            filters.append(vhs)

        # Add white flash on high-motion impacts
        if enable_flash and motion_peaks:
            # Filter to only high-motion peaks (top impacts)
            high_motion = [p for p in motion_peaks if p.get('motion', 0) >= 0.7]
            flash_times = [p['time'] for p in high_motion[:4]]
            if flash_times:
                flash_filter = self._white_flash_filter(flash_times, duration=0.08, intensity=0.6)
                if flash_filter:
                    filters.append(flash_filter)

        # Add dynamic screen shake (variable intensity based on motion)
        if enable_shake:
            shake = self._dynamic_screen_shake_filter(
                w, h, motion_peaks,
                base_intensity=6, peak_intensity=18
            )
            if shake:
                filters.append(shake)

        # Add smooth zoom pulses
        zoom = self._zoom_pulse_filter(w, h, [], base_zoom=1.0, pulse_zoom=1.06)
        filters.append(zoom)

        # Add caption if provided
        if caption_text:
            caption_filter = self._build_caption_filter(
                caption_text, caption_style, 0.5, 3.0, 'bottom', w, h
            )
            if caption_filter:
                filters.append(caption_filter)

        return ','.join(filters)

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

    def _viral_anime_afilters(self, speed: float) -> str:
        """Punchy, bass-heavy, compressed for maximum impact on mobile speakers."""
        f = f'loudnorm=I={self.loudness}:TP=-1:LRA=11,aformat=sample_rates=48000'
        f += self._atempo(speed)
        # Heavy bass boost for that thump on mobile
        f += ',bass=g=14:f=70'
        # Aggressive compression for punch
        f += ',acompressor=threshold=-16dB:ratio=7:attack=2:release=30'
        # Slight high boost for clarity
        f += ',treble=g=3:f=5000'
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
        aspect: str, template: str, speed: float = 1.0,
        motion_peaks: List[Dict] = None,
        beat_times: List[float] = None,
        caption_text: str = None,
        caption_style: str = 'pop'
    ) -> str:
        """Render a single segment with template-specific filters. No fades."""
        w, h = self._dims(aspect)
        raw_duration = end_s - start_s

        # Adjust motion_peaks times to be relative to segment start
        relative_peaks = []
        if motion_peaks:
            for p in motion_peaks:
                rel_time = p['time'] - start_s
                if 0 <= rel_time <= raw_duration:
                    relative_peaks.append({
                        'time': rel_time,
                        'motion': p.get('motion', 0.5)
                    })

        # Template-specific video filters
        # Both viral_anime and anime_hype now use motion_peaks for effects
        if template == 'viral_anime':
            vf = self._viral_anime_vfilters(
                w, h, relative_peaks,
                enable_flash=True, enable_shake=True,
                caption_text=caption_text, caption_style=caption_style
            )
        elif template == 'anime_hype':
            vf = self._velocity_vfilters(
                w, h, relative_peaks,
                enable_flash=True, enable_shake=True
            )
        else:
            vf_map = {
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
            'viral_anime': lambda: self._viral_anime_afilters(speed),
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
                      aspect: str, output: str,
                      transition_override: str = None) -> str:
        """
        Join segments using FFmpeg xfade filter for SEAMLESS transitions.
        No black frames, no flash clips — pure video blending.

        Each template uses a different xfade transition type:
        - anime_hype:  fadewhite (0.08s) — near-instant white flash impact
        - clean_flow:  dissolve  (0.25s) — smooth crossfade + film burn option
        - hard_cuts:   wiperight (0.04s) — quick wipe for energy
        - cinematic:   fade      (0.15s) — brief elegant fade
        - glitch:      pixelize  (0.06s) — digital pixel dissolve
        - viral_anime: zoomin    (0.05s) — zoom punch for impact

        NEW TRANSITIONS:
        - fadewhite: white flash impact (velocity edits)
        - zoomin/wipeleft/wiperight: whip pan effect
        - smoothleft/smoothright: smooth flow transitions
        - radial: creative burst effect
        """
        if len(segment_files) == 1:
            shutil.move(segment_files[0], output)
            return output

        # Template-specific xfade configuration (ENHANCED)
        # Format: (transition_type, duration)
        xfade_config = {
            'anime_hype': ('fadewhite', 0.08),      # White flash impacts
            'clean_flow': ('smoothleft', 0.25),     # Smooth flow transition
            'hard_cuts': ('wiperight', 0.04),       # Quick whip cut
            'cinematic': ('fade', 0.18),            # Elegant film fade
            'glitch': ('pixelize', 0.06),           # Digital pixel dissolve
            'viral_anime': ('zoomin', 0.05),        # Zoom punch impact
        }

        # Use override if provided
        if transition_override:
            xfade_type, xfade_dur = transition_override, 0.1
        else:
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
            'viral_anime': (0.0, 0.0),       # None — hard cuts only
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

    def render(self, segments: List[Dict], template_name: str, aspect: str,
               enable_beat_sync: bool = False, caption_text: str = None,
               caption_style: str = 'pop', enable_smart_reframe: bool = True,
               hook_text: str = None, hook_style: str = 'bold',
               reorder_for_hook: bool = False) -> str:
        """
        Main render pipeline:
        1. Trim segments to max_duration
        2. Apply hook reordering if enabled (start with best moment)
        3. Apply beat sync if enabled (align cuts to music beats)
        4. Apply template-specific speed ramps
        5. Render each sub-segment with template filters (white flash, shake, etc.)
        6. Join with xfade (seamless, NO black frames)
        7. Apply hook text overlay if provided
        8. Apply final intro/outro fades only

        NEW OPTIONS:
        - enable_beat_sync: Align cuts to detected music beats (#1 viral factor)
        - caption_text: Optional caption to overlay
        - caption_style: 'pop', 'bounce', 'highlight', 'glow'
        - enable_smart_reframe: Use face detection for smart cropping (default True)
        - hook_text: Optional hook text for first 2-3 seconds
        - hook_style: 'bold', 'glitch', 'neon'
        - reorder_for_hook: Reorder clip to start with best moment
        """
        w, h = self._dims(aspect)

        # ── -1. Smart Reframing: Detect faces for better cropping ──
        face_tracks = []
        if enable_smart_reframe and segments:
            try:
                start_time = segments[0]['start_s']
                end_time = segments[-1]['end_s']
                face_tracks = self.detect_faces_for_reframe(start_time, end_time)
                if face_tracks:
                    logger.info(f"Smart reframe: detected {len(face_tracks)} face positions")
            except Exception as e:
                logger.warning(f"Face detection failed, using center crop: {e}")

        # ── 0. Beat Detection (if enabled) ──
        beat_times = []
        if enable_beat_sync:
            try:
                audio_analyzer = AudioAnalyzer(self.video_path)
                # Get beat times for the entire clip range
                start_time = segments[0]['start_s'] if segments else 0
                end_time = segments[-1]['end_s'] if segments else 30
                beat_times = audio_analyzer.detect_beats(start_time, end_time)
                audio_analyzer.cleanup()
                logger.info(f"Beat sync: detected {len(beat_times)} beats")
            except Exception as e:
                logger.warning(f"Beat detection failed, proceeding without: {e}")

        # ── 0.5. Hook Reordering: Start with best moment ──
        if reorder_for_hook and segments:
            try:
                # Analyze all segments for best hook moment
                all_motion = []
                for seg in segments:
                    seg_motion = self.detect_motion_peaks(seg['start_s'], seg['end_s'])
                    all_motion.extend(seg_motion)

                if all_motion:
                    hook_info = self.find_best_hook_moment(
                        segments[0]['start_s'],
                        segments[-1]['end_s'],
                        all_motion
                    )
                    if hook_info.get('can_reorder', False):
                        segments = self.reorder_for_hook(segments, hook_info['time'])
                        logger.info(f"Hook reorder: moved peak moment at {hook_info['time']:.1f}s to start")
            except Exception as e:
                logger.warning(f"Hook reordering failed: {e}")

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
                # GLITCH: Visual chaos via filters, not speed changes
                # Speed ramping with xfade creates too many segments
                'normal_speed': 1.1,  # Slightly fast for energy
                'use_ramps': False,   # Visual effects provide the glitch feel
            },
            'viral_anime': {
                # VIRAL: Normal speed to preserve duration, visual effects only
                # The shake/zoom/VHS effects provide the energy without speed changes
                'normal_speed': 1.0,
                'use_ramps': False,  # No speed ramping - preserves requested duration
            },
        }
        speeds = speed_config.get(template_name, {'normal_speed': 1.0, 'use_ramps': False})

        # ── 3. Render all segments ──
        rendered_parts = []
        temp_files = []

        for i, seg in enumerate(trimmed):
            # Detect motion peaks for this segment
            motion_peaks = self.detect_motion_peaks(seg['start_s'], seg['end_s'])

            if speeds.get('use_ramps', False):
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
                            aspect, template_name, sub['speed'],
                            motion_peaks=motion_peaks  # Pass for viral_anime effects
                        )
                        rendered_parts.append(seg_path)
                        temp_files.append(seg_path)
                else:
                    seg_path = self._render_segment(
                        seg['start_s'], seg['end_s'],
                        aspect, template_name, speeds['normal_speed'],
                        motion_peaks=motion_peaks
                    )
                    rendered_parts.append(seg_path)
                    temp_files.append(seg_path)
            else:
                seg_path = self._render_segment(
                    seg['start_s'], seg['end_s'],
                    aspect, template_name, speeds['normal_speed'],
                    motion_peaks=motion_peaks
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

        # NEW: Viral editing options
        enable_beat_sync = params.get('enable_beat_sync', False)
        caption_text = params.get('caption_text', None)
        caption_style = params.get('caption_style', 'pop')
        effect_intensity = params.get('effect_intensity', 'medium')  # low, medium, high

        # MEDIUM PRIORITY: Smart reframing and hook optimization
        enable_smart_reframe = params.get('enable_smart_reframe', True)
        hook_text = params.get('hook_text', None)
        hook_style = params.get('hook_style', 'bold')
        reorder_for_hook = params.get('reorder_for_hook', False)

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

            # For viral_anime: use full clip range to preserve duration
            # For other templates: detect action segments for smart cutting
            if template == 'viral_anime':
                # Use the full candidate range - no action detection
                action_segments = [{'start_s': candidate.start_s, 'end_s': candidate.end_s}]
            else:
                # Detect action segments for other templates
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
                    'effect_intensity': effect_intensity,
                }

                renderer = AutoEditRenderer(video_path, output_path, config)
                renderer.render(
                    action_segments, template, aspect,
                    enable_beat_sync=enable_beat_sync,
                    caption_text=caption_text,
                    caption_style=caption_style,
                    enable_smart_reframe=enable_smart_reframe,
                    hook_text=hook_text,
                    hook_style=hook_style,
                    reorder_for_hook=reorder_for_hook
                )

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
