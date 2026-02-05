"""
Virality Score System for Anime Clips

Analyzes clips for viral potential using multiple factors:
- Action density (motion per second)
- Character face presence
- Color vibrancy (saturation/contrast)
- Audio energy level
- Hook strength (first 2-3 seconds)

Generates a 0-100 virality score to help users pick the best clips.
"""

import os
import subprocess
import json
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ViralityFactors:
    """Individual factors that contribute to virality score."""
    action_density: float = 0.0      # 0-100: Motion intensity per second
    face_presence: float = 0.0       # 0-100: % of frames with faces
    color_vibrancy: float = 0.0      # 0-100: Saturation/contrast score
    audio_energy: float = 0.0        # 0-100: Audio loudness/punch
    hook_strength: float = 0.0       # 0-100: First 3s engagement potential
    scene_variety: float = 0.0       # 0-100: Scene change frequency

    def to_dict(self) -> Dict:
        return {
            'action_density': round(self.action_density, 1),
            'face_presence': round(self.face_presence, 1),
            'color_vibrancy': round(self.color_vibrancy, 1),
            'audio_energy': round(self.audio_energy, 1),
            'hook_strength': round(self.hook_strength, 1),
            'scene_variety': round(self.scene_variety, 1),
        }


@dataclass
class ViralityScore:
    """Complete virality analysis result."""
    score: int                       # 0-100 overall score
    grade: str                       # S/A/B/C/D grade
    factors: ViralityFactors         # Individual factor scores
    recommendations: List[str]       # Tips to improve virality
    best_hook_time: float            # Timestamp of best hook moment
    peak_action_time: float          # Timestamp of peak action

    def to_dict(self) -> Dict:
        return {
            'score': self.score,
            'grade': self.grade,
            'factors': self.factors.to_dict(),
            'recommendations': self.recommendations,
            'best_hook_time': round(self.best_hook_time, 2),
            'peak_action_time': round(self.peak_action_time, 2),
        }


class ViralityScorer:
    """
    Analyzes video clips for viral potential.

    Uses the viral content formula from research:
    VIRAL CLIP =
      (Action Density x 0.30) +
      (Face Presence x 0.15) +
      (Color Vibrancy x 0.15) +
      (Audio Energy x 0.20) +
      (Hook Strength x 0.20)
    """

    # Weights based on viral research
    WEIGHTS = {
        'action_density': 0.30,
        'face_presence': 0.15,
        'color_vibrancy': 0.15,
        'audio_energy': 0.20,
        'hook_strength': 0.20,
    }

    # Grade thresholds
    GRADES = [
        (90, 'S'),   # Viral potential
        (75, 'A'),   # High potential
        (60, 'B'),   # Good potential
        (45, 'C'),   # Average
        (0, 'D'),    # Low potential
    ]

    def __init__(self, video_path: str):
        self.video_path = video_path
        self._duration: Optional[float] = None
        self._fps: Optional[float] = None

    def _get_video_info(self) -> Tuple[float, float, int, int]:
        """Get video duration, fps, width, height."""
        if self._duration is not None:
            return self._duration, self._fps, 1920, 1080

        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', self.video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        try:
            data = json.loads(result.stdout)
            self._duration = float(data['format'].get('duration', 30))

            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    self._fps = eval(stream.get('r_frame_rate', '24/1'))
                    width = stream.get('width', 1920)
                    height = stream.get('height', 1080)
                    return self._duration, self._fps, width, height

            self._fps = 24.0
            return self._duration, self._fps, 1920, 1080

        except (json.JSONDecodeError, KeyError, ValueError):
            self._duration = 30.0
            self._fps = 24.0
            return 30.0, 24.0, 1920, 1080

    def analyze_action_density(self, start_s: float, end_s: float) -> Tuple[float, float, List[Dict]]:
        """
        Analyze motion/action density in the clip.

        Returns:
            (score 0-100, peak_action_time, motion_data)
        """
        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available for action analysis")
            return 50.0, start_s, []

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            return 50.0, start_s, []

        fps = cap.get(cv2.CAP_PROP_FPS) or 24
        start_frame = int(start_s * fps)
        end_frame = int(end_s * fps)

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        motion_scores = []
        prev_gray = None
        sample_rate = max(1, int(fps / 10))  # Sample 10 frames per second

        peak_motion = 0
        peak_time = start_s

        for frame_idx in range(start_frame, end_frame):
            ret, frame = cap.read()
            if not ret:
                break

            if (frame_idx - start_frame) % sample_rate == 0:
                # Resize for faster processing
                small = cv2.resize(frame, (160, 90))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

                if prev_gray is not None:
                    # Compute optical flow magnitude
                    diff = cv2.absdiff(gray, prev_gray)
                    motion = float(np.mean(diff))

                    current_time = start_s + (frame_idx - start_frame) / fps
                    motion_scores.append({
                        'time': current_time,
                        'motion': motion
                    })

                    if motion > peak_motion:
                        peak_motion = motion
                        peak_time = current_time

                prev_gray = gray

        cap.release()

        if not motion_scores:
            return 50.0, start_s, []

        # Normalize and compute score
        max_motion = max(m['motion'] for m in motion_scores)
        if max_motion > 0:
            for m in motion_scores:
                m['motion'] /= max_motion

        # Average motion * 100, with bonus for high peaks
        avg_motion = np.mean([m['motion'] for m in motion_scores])
        peak_bonus = min(20, peak_motion / max_motion * 20) if max_motion > 0 else 0

        # Score: base from average, bonus from peaks
        score = min(100, avg_motion * 80 + peak_bonus)

        return score, peak_time, motion_scores

    def analyze_face_presence(self, start_s: float, end_s: float) -> Tuple[float, List[Dict]]:
        """
        Detect face presence throughout the clip.

        Returns:
            (score 0-100, face_data)
        """
        try:
            import cv2
        except ImportError:
            logger.warning("OpenCV not available for face detection")
            return 50.0, []

        # Load face cascade
        cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        if not os.path.exists(cascade_path):
            # Try anime face cascade or fallback
            cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_alt.xml'

        face_cascade = cv2.CascadeClassifier(cascade_path)

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            return 50.0, []

        fps = cap.get(cv2.CAP_PROP_FPS) or 24
        start_frame = int(start_s * fps)
        end_frame = int(end_s * fps)

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        face_data = []
        frames_with_faces = 0
        total_frames = 0
        sample_rate = max(1, int(fps / 5))  # Sample 5 frames per second

        for frame_idx in range(start_frame, end_frame):
            ret, frame = cap.read()
            if not ret:
                break

            if (frame_idx - start_frame) % sample_rate == 0:
                total_frames += 1

                # Resize for faster detection
                scale = 0.5
                small = cv2.resize(frame, None, fx=scale, fy=scale)
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

                # Detect faces
                faces = face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.1,
                    minNeighbors=4,
                    minSize=(20, 20)
                )

                current_time = start_s + (frame_idx - start_frame) / fps

                if len(faces) > 0:
                    frames_with_faces += 1
                    # Store face positions (scaled back up)
                    face_rects = []
                    for (x, y, w, h) in faces:
                        face_rects.append({
                            'x': int(x / scale),
                            'y': int(y / scale),
                            'w': int(w / scale),
                            'h': int(h / scale)
                        })
                    face_data.append({
                        'time': current_time,
                        'faces': face_rects,
                        'count': len(faces)
                    })

        cap.release()

        if total_frames == 0:
            return 50.0, []

        # Score based on face presence ratio
        # Anime content benefits from character faces
        presence_ratio = frames_with_faces / total_frames

        # Score: 100 if faces in 70%+ frames, scales down
        score = min(100, presence_ratio * 140)

        return score, face_data

    def analyze_color_vibrancy(self, start_s: float, end_s: float) -> float:
        """
        Analyze color saturation and contrast.

        Returns:
            score 0-100
        """
        try:
            import cv2
        except ImportError:
            return 50.0

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            return 50.0

        fps = cap.get(cv2.CAP_PROP_FPS) or 24
        start_frame = int(start_s * fps)
        end_frame = int(end_s * fps)

        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

        saturation_scores = []
        contrast_scores = []
        sample_rate = max(1, int(fps / 3))  # Sample 3 frames per second

        for frame_idx in range(start_frame, end_frame):
            ret, frame = cap.read()
            if not ret:
                break

            if (frame_idx - start_frame) % sample_rate == 0:
                # Resize for faster processing
                small = cv2.resize(frame, (160, 90))

                # Convert to HSV for saturation
                hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
                saturation = np.mean(hsv[:, :, 1])  # S channel
                saturation_scores.append(saturation / 255.0)

                # Compute contrast (standard deviation of luminance)
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                contrast = np.std(gray) / 128.0  # Normalize
                contrast_scores.append(min(1.0, contrast))

        cap.release()

        if not saturation_scores:
            return 50.0

        # Combine saturation and contrast
        avg_saturation = np.mean(saturation_scores)
        avg_contrast = np.mean(contrast_scores)

        # Viral anime clips tend to have high saturation (1.4-1.8x boosted)
        # Score higher for vibrant colors
        saturation_score = min(100, avg_saturation * 150)
        contrast_score = min(100, avg_contrast * 120)

        # Weight saturation more for anime
        score = saturation_score * 0.6 + contrast_score * 0.4

        return score

    def analyze_audio_energy(self, start_s: float, end_s: float) -> Tuple[float, List[Dict]]:
        """
        Analyze audio energy and punch.

        Returns:
            (score 0-100, energy_data)
        """
        try:
            from app.workers.audio_analyzer import AudioAnalyzer

            analyzer = AudioAnalyzer(self.video_path)
            energy_profile = analyzer.get_energy_profile(start_s, end_s, resolution=0.2)
            bass_drops = analyzer.detect_bass_drops(start_s, end_s)
            onsets = analyzer.detect_onsets(start_s, end_s, sensitivity=0.6)
            analyzer.cleanup()

            if not energy_profile:
                return 50.0, []

            # Calculate metrics
            avg_energy = np.mean([e['energy'] for e in energy_profile])
            max_energy = max([e['energy'] for e in energy_profile])

            # Bass drops add punch (important for viral clips)
            bass_bonus = min(20, len(bass_drops) * 5)

            # Onset density (rhythmic content)
            onset_density = len(onsets) / max(1, end_s - start_s)
            onset_bonus = min(15, onset_density * 5)

            # Score: base from energy, bonus from bass and rhythm
            score = min(100, avg_energy * 60 + max_energy * 10 + bass_bonus + onset_bonus)

            return score, energy_profile

        except Exception as e:
            logger.warning(f"Audio analysis failed: {e}")
            return 50.0, []

    def analyze_hook_strength(self, start_s: float, end_s: float,
                              motion_data: List[Dict] = None) -> Tuple[float, float]:
        """
        Analyze the hook potential of the first 2-3 seconds.

        Returns:
            (score 0-100, best_hook_time)
        """
        hook_end = min(start_s + 3.0, end_s)

        if motion_data:
            # Find energy in first 3 seconds
            hook_motion = [m for m in motion_data if m['time'] <= hook_end]

            if hook_motion:
                hook_energy = np.mean([m['motion'] for m in hook_motion])
                peak_in_hook = max([m['motion'] for m in hook_motion])

                # Strong hook = high energy right from the start
                # Penalize slow builds
                first_second = [m for m in hook_motion if m['time'] <= start_s + 1.0]
                if first_second:
                    first_second_energy = np.mean([m['motion'] for m in first_second])
                else:
                    first_second_energy = hook_energy

                # Score: immediate energy matters most
                score = min(100, first_second_energy * 50 + hook_energy * 30 + peak_in_hook * 20)

                # Find best hook moment (highest energy point)
                best_hook = max(hook_motion, key=lambda m: m['motion'])
                return score, best_hook['time']

        # Fallback: analyze first 3 seconds directly
        try:
            import cv2

            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                return 50.0, start_s

            fps = cap.get(cv2.CAP_PROP_FPS) or 24
            start_frame = int(start_s * fps)
            end_frame = int(hook_end * fps)

            cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

            prev_gray = None
            motion_scores = []

            for frame_idx in range(start_frame, end_frame):
                ret, frame = cap.read()
                if not ret:
                    break

                small = cv2.resize(frame, (160, 90))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

                if prev_gray is not None:
                    diff = cv2.absdiff(gray, prev_gray)
                    motion = float(np.mean(diff))
                    current_time = start_s + (frame_idx - start_frame) / fps
                    motion_scores.append({'time': current_time, 'motion': motion})

                prev_gray = gray

            cap.release()

            if motion_scores:
                max_motion = max(m['motion'] for m in motion_scores)
                if max_motion > 0:
                    for m in motion_scores:
                        m['motion'] /= max_motion

                avg = np.mean([m['motion'] for m in motion_scores])
                best = max(motion_scores, key=lambda m: m['motion'])
                return min(100, avg * 100), best['time']

        except Exception as e:
            logger.warning(f"Hook analysis failed: {e}")

        return 50.0, start_s

    def get_recommendations(self, factors: ViralityFactors) -> List[str]:
        """Generate recommendations based on factor scores."""
        recommendations = []

        if factors.action_density < 50:
            recommendations.append("Add more action-packed moments or speed ramps")
        if factors.face_presence < 40:
            recommendations.append("Include more character close-ups for engagement")
        if factors.color_vibrancy < 50:
            recommendations.append("Boost saturation and contrast for mobile pop")
        if factors.audio_energy < 50:
            recommendations.append("Use bass-heavy music or add sound effects")
        if factors.hook_strength < 60:
            recommendations.append("Start with your best moment - hook viewers in 2s")

        if factors.action_density >= 80 and factors.hook_strength >= 70:
            recommendations.append("Great action and hook! Consider beat sync for maximum impact")
        if factors.face_presence >= 70:
            recommendations.append("Good character presence - add captions for extra engagement")

        if not recommendations:
            recommendations.append("Strong viral potential! Enable all effects for maximum impact")

        return recommendations

    def calculate_score(self, start_s: float = 0, end_s: float = None) -> ViralityScore:
        """
        Calculate complete virality score for a clip segment.

        Args:
            start_s: Start time in seconds
            end_s: End time in seconds (None = end of video)

        Returns:
            ViralityScore with all factors and recommendations
        """
        duration, fps, width, height = self._get_video_info()

        if end_s is None:
            end_s = duration

        # Analyze all factors
        action_score, peak_action_time, motion_data = self.analyze_action_density(start_s, end_s)
        face_score, face_data = self.analyze_face_presence(start_s, end_s)
        color_score = self.analyze_color_vibrancy(start_s, end_s)
        audio_score, audio_data = self.analyze_audio_energy(start_s, end_s)
        hook_score, best_hook_time = self.analyze_hook_strength(start_s, end_s, motion_data)

        # Create factors object
        factors = ViralityFactors(
            action_density=action_score,
            face_presence=face_score,
            color_vibrancy=color_score,
            audio_energy=audio_score,
            hook_strength=hook_score,
        )

        # Calculate weighted score
        weighted_score = (
            factors.action_density * self.WEIGHTS['action_density'] +
            factors.face_presence * self.WEIGHTS['face_presence'] +
            factors.color_vibrancy * self.WEIGHTS['color_vibrancy'] +
            factors.audio_energy * self.WEIGHTS['audio_energy'] +
            factors.hook_strength * self.WEIGHTS['hook_strength']
        )

        final_score = int(min(100, max(0, weighted_score)))

        # Determine grade
        grade = 'D'
        for threshold, g in self.GRADES:
            if final_score >= threshold:
                grade = g
                break

        # Get recommendations
        recommendations = self.get_recommendations(factors)

        return ViralityScore(
            score=final_score,
            grade=grade,
            factors=factors,
            recommendations=recommendations,
            best_hook_time=best_hook_time,
            peak_action_time=peak_action_time,
        )


def score_candidate(video_path: str, start_s: float, end_s: float) -> Dict:
    """
    Convenience function to score a single candidate clip.

    Returns dict with score, grade, factors, and recommendations.
    """
    scorer = ViralityScorer(video_path)
    result = scorer.calculate_score(start_s, end_s)
    return result.to_dict()


def score_candidates_batch(video_path: str, candidates: List[Dict]) -> List[Dict]:
    """
    Score multiple candidates from the same video efficiently.

    Args:
        video_path: Path to video file
        candidates: List of dicts with 'id', 'start_s', 'end_s'

    Returns:
        List of dicts with candidate id and virality score
    """
    scorer = ViralityScorer(video_path)
    results = []

    for cand in candidates:
        try:
            score_result = scorer.calculate_score(cand['start_s'], cand['end_s'])
            results.append({
                'candidate_id': cand['id'],
                **score_result.to_dict()
            })
        except Exception as e:
            logger.error(f"Failed to score candidate {cand['id']}: {e}")
            results.append({
                'candidate_id': cand['id'],
                'score': 50,
                'grade': 'C',
                'error': str(e)
            })

    return results
