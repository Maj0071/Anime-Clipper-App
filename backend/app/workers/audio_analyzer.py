"""
Audio Analyzer Module for Viral Anime Clips

Provides beat detection and BPM analysis for music synchronization.
This is the #1 factor for viral edits according to research.

Uses librosa for professional-grade audio analysis.
"""

import os
import subprocess
import json
import tempfile
import logging
from typing import List, Dict, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class AudioAnalyzer:
    """
    Analyzes audio tracks for beat detection and music synchronization.

    Key features:
    - BPM detection for tempo matching
    - Beat timestamp extraction for cut alignment
    - Onset detection for impact moments
    - Energy peaks for bass drops
    """

    def __init__(self, video_path: str):
        self.video_path = video_path
        self._audio_path: Optional[str] = None
        self._sample_rate: int = 22050
        self._audio_data: Optional[np.ndarray] = None

    def _extract_audio(self) -> str:
        """Extract audio from video file to temporary WAV."""
        if self._audio_path and os.path.exists(self._audio_path):
            return self._audio_path

        # Create temp file for audio
        fd, self._audio_path = tempfile.mkstemp(suffix='.wav')
        os.close(fd)

        cmd = [
            'ffmpeg', '-i', self.video_path,
            '-vn',  # No video
            '-acodec', 'pcm_s16le',  # PCM format for librosa
            '-ar', str(self._sample_rate),  # Sample rate
            '-ac', '1',  # Mono
            '-y', self._audio_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(f"Audio extraction failed: {result.stderr[:200]}")
            return ""

        return self._audio_path

    def _load_audio(self) -> Tuple[Optional[np.ndarray], int]:
        """Load audio data using librosa or fallback to numpy."""
        if self._audio_data is not None:
            return self._audio_data, self._sample_rate

        audio_path = self._extract_audio()
        if not audio_path or not os.path.exists(audio_path):
            return None, self._sample_rate

        try:
            import librosa
            self._audio_data, self._sample_rate = librosa.load(
                audio_path, sr=self._sample_rate, mono=True
            )
            return self._audio_data, self._sample_rate
        except ImportError:
            logger.warning("librosa not available, using fallback beat detection")
            # Fallback: use scipy to read WAV
            try:
                from scipy.io import wavfile
                sr, data = wavfile.read(audio_path)
                # Convert to float and normalize
                if data.dtype == np.int16:
                    data = data.astype(np.float32) / 32768.0
                elif data.dtype == np.int32:
                    data = data.astype(np.float32) / 2147483648.0
                # Handle stereo
                if len(data.shape) > 1:
                    data = np.mean(data, axis=1)
                self._audio_data = data
                self._sample_rate = sr
                return self._audio_data, self._sample_rate
            except Exception as e:
                logger.warning(f"Fallback audio load failed: {e}")
                return None, self._sample_rate

    def detect_bpm(self, start_s: float = 0, end_s: float = None) -> float:
        """
        Detect BPM (beats per minute) of the audio.

        Returns estimated BPM, typically 60-200 for music.
        Default 120 BPM if detection fails.
        """
        y, sr = self._load_audio()
        if y is None:
            return 120.0  # Default fallback

        try:
            import librosa

            # Get segment
            start_sample = int(start_s * sr)
            end_sample = int(end_s * sr) if end_s else len(y)
            y_segment = y[start_sample:end_sample]

            if len(y_segment) < sr:  # Less than 1 second
                return 120.0

            # Detect tempo
            tempo, _ = librosa.beat.beat_track(y=y_segment, sr=sr)
            return float(tempo) if tempo > 0 else 120.0

        except ImportError:
            # Fallback: estimate from onset detection
            return self._estimate_bpm_fallback(start_s, end_s)
        except Exception as e:
            logger.warning(f"BPM detection failed: {e}")
            return 120.0

    def _estimate_bpm_fallback(self, start_s: float = 0, end_s: float = None) -> float:
        """Estimate BPM using simple onset detection without librosa."""
        y, sr = self._load_audio()
        if y is None:
            return 120.0

        try:
            from scipy.signal import find_peaks

            start_sample = int(start_s * sr)
            end_sample = int(end_s * sr) if end_s else len(y)
            y_segment = y[start_sample:end_sample]

            # Compute energy envelope
            frame_size = int(sr * 0.02)  # 20ms frames
            hop_size = frame_size // 2

            energy = []
            for i in range(0, len(y_segment) - frame_size, hop_size):
                frame = y_segment[i:i + frame_size]
                energy.append(np.sum(frame ** 2))

            energy = np.array(energy)
            if len(energy) < 10:
                return 120.0

            # Find peaks
            peaks, _ = find_peaks(energy, height=np.mean(energy), distance=sr // hop_size // 4)

            if len(peaks) < 2:
                return 120.0

            # Calculate average time between peaks
            peak_times = peaks * hop_size / sr
            intervals = np.diff(peak_times)

            if len(intervals) == 0:
                return 120.0

            avg_interval = np.median(intervals)
            if avg_interval > 0:
                bpm = 60.0 / avg_interval
                # Clamp to reasonable range
                return max(60.0, min(200.0, bpm))

            return 120.0

        except Exception as e:
            logger.warning(f"BPM fallback failed: {e}")
            return 120.0

    def detect_beats(self, start_s: float = 0, end_s: float = None) -> List[float]:
        """
        Detect beat timestamps in the audio.

        Returns list of timestamps (in seconds) where beats occur.
        These are ideal cut points for music sync.
        """
        y, sr = self._load_audio()
        if y is None:
            # Generate fallback beats at regular intervals
            duration = end_s - start_s if end_s else 30
            bpm = 120
            beat_interval = 60.0 / bpm
            return [start_s + i * beat_interval for i in range(int(duration / beat_interval))]

        try:
            import librosa

            start_sample = int(start_s * sr)
            end_sample = int(end_s * sr) if end_s else len(y)
            y_segment = y[start_sample:end_sample]

            if len(y_segment) < sr:
                return [start_s]

            # Detect beats
            tempo, beat_frames = librosa.beat.beat_track(y=y_segment, sr=sr)
            beat_times = librosa.frames_to_time(beat_frames, sr=sr)

            # Offset by start time
            return [float(start_s + t) for t in beat_times]

        except ImportError:
            return self._detect_beats_fallback(start_s, end_s)
        except Exception as e:
            logger.warning(f"Beat detection failed: {e}")
            return self._detect_beats_fallback(start_s, end_s)

    def _detect_beats_fallback(self, start_s: float = 0, end_s: float = None) -> List[float]:
        """Detect beats without librosa using onset detection."""
        y, sr = self._load_audio()
        if y is None:
            bpm = 120
            duration = (end_s - start_s) if end_s else 30
            beat_interval = 60.0 / bpm
            return [start_s + i * beat_interval for i in range(int(duration / beat_interval))]

        try:
            from scipy.signal import find_peaks

            start_sample = int(start_s * sr)
            end_sample = int(end_s * sr) if end_s else len(y)
            y_segment = y[start_sample:end_sample]

            # Compute energy envelope with smaller frames for better resolution
            frame_size = int(sr * 0.015)  # 15ms frames
            hop_size = frame_size // 2

            energy = []
            for i in range(0, len(y_segment) - frame_size, hop_size):
                frame = y_segment[i:i + frame_size]
                energy.append(np.sum(np.abs(frame)))

            energy = np.array(energy)
            if len(energy) < 10:
                return [start_s]

            # Onset detection: find sudden increases in energy
            onset_env = np.diff(energy)
            onset_env[onset_env < 0] = 0

            # Find peaks with adaptive threshold
            threshold = np.percentile(onset_env, 75)
            peaks, _ = find_peaks(onset_env, height=threshold, distance=int(0.2 * sr / hop_size))

            # Convert to timestamps
            beat_times = [start_s + (p * hop_size / sr) for p in peaks]

            return beat_times if beat_times else [start_s]

        except Exception as e:
            logger.warning(f"Beat fallback failed: {e}")
            bpm = 120
            duration = (end_s - start_s) if end_s else 30
            beat_interval = 60.0 / bpm
            return [start_s + i * beat_interval for i in range(int(duration / beat_interval))]

    def detect_onsets(self, start_s: float = 0, end_s: float = None,
                      sensitivity: float = 0.5) -> List[Dict]:
        """
        Detect audio onset events (sudden changes in audio).

        Returns list of dicts with:
        - time: timestamp in seconds
        - strength: onset strength (0-1)

        sensitivity: 0.0 = few onsets, 1.0 = many onsets
        """
        y, sr = self._load_audio()
        if y is None:
            return []

        try:
            import librosa

            start_sample = int(start_s * sr)
            end_sample = int(end_s * sr) if end_s else len(y)
            y_segment = y[start_sample:end_sample]

            if len(y_segment) < sr:
                return []

            # Compute onset strength envelope
            onset_env = librosa.onset.onset_strength(y=y_segment, sr=sr)

            # Detect onset times
            onset_frames = librosa.onset.onset_detect(
                onset_envelope=onset_env,
                sr=sr,
                backtrack=False
            )
            onset_times = librosa.frames_to_time(onset_frames, sr=sr)

            # Get strengths
            max_strength = np.max(onset_env) if len(onset_env) > 0 else 1.0

            results = []
            for frame, time in zip(onset_frames, onset_times):
                if frame < len(onset_env):
                    strength = onset_env[frame] / max_strength if max_strength > 0 else 0.5
                    # Filter by sensitivity threshold
                    if strength >= (1.0 - sensitivity):
                        results.append({
                            'time': float(start_s + time),
                            'strength': float(strength)
                        })

            return results

        except ImportError:
            return self._detect_onsets_fallback(start_s, end_s, sensitivity)
        except Exception as e:
            logger.warning(f"Onset detection failed: {e}")
            return []

    def _detect_onsets_fallback(self, start_s: float = 0, end_s: float = None,
                                sensitivity: float = 0.5) -> List[Dict]:
        """Detect onsets without librosa."""
        y, sr = self._load_audio()
        if y is None:
            return []

        try:
            from scipy.signal import find_peaks

            start_sample = int(start_s * sr)
            end_sample = int(end_s * sr) if end_s else len(y)
            y_segment = y[start_sample:end_sample]

            # Compute spectral flux (energy difference)
            frame_size = int(sr * 0.02)
            hop_size = frame_size // 2

            flux = []
            prev_energy = 0
            for i in range(0, len(y_segment) - frame_size, hop_size):
                frame = y_segment[i:i + frame_size]
                energy = np.sum(frame ** 2)
                diff = max(0, energy - prev_energy)
                flux.append(diff)
                prev_energy = energy

            flux = np.array(flux)
            if len(flux) < 10:
                return []

            # Find peaks
            threshold = np.percentile(flux, int(100 - sensitivity * 50))
            peaks, properties = find_peaks(flux, height=threshold)

            max_height = np.max(properties['peak_heights']) if len(properties['peak_heights']) > 0 else 1.0

            results = []
            for peak in peaks:
                time = start_s + (peak * hop_size / sr)
                strength = properties['peak_heights'][list(peaks).index(peak)] / max_height if max_height > 0 else 0.5
                results.append({
                    'time': float(time),
                    'strength': float(strength)
                })

            return results

        except Exception as e:
            logger.warning(f"Onset fallback failed: {e}")
            return []

    def detect_bass_drops(self, start_s: float = 0, end_s: float = None) -> List[Dict]:
        """
        Detect bass drops and heavy bass moments.

        These are ideal for white flash impacts and speed changes.
        Returns list of dicts with time and intensity.
        """
        y, sr = self._load_audio()
        if y is None:
            return []

        try:
            import librosa
            from scipy.signal import butter, filtfilt

            start_sample = int(start_s * sr)
            end_sample = int(end_s * sr) if end_s else len(y)
            y_segment = y[start_sample:end_sample]

            if len(y_segment) < sr:
                return []

            # Low-pass filter to isolate bass (< 150 Hz)
            nyquist = sr / 2
            low_cutoff = 150 / nyquist
            b, a = butter(4, low_cutoff, btype='low')
            bass = filtfilt(b, a, y_segment)

            # Compute bass energy envelope
            frame_size = int(sr * 0.05)  # 50ms frames for bass
            hop_size = frame_size // 2

            bass_energy = []
            for i in range(0, len(bass) - frame_size, hop_size):
                frame = bass[i:i + frame_size]
                bass_energy.append(np.sum(frame ** 2))

            bass_energy = np.array(bass_energy)
            if len(bass_energy) < 5:
                return []

            # Find sudden increases (bass drops)
            bass_diff = np.diff(bass_energy)
            bass_diff[bass_diff < 0] = 0

            threshold = np.percentile(bass_diff, 85)
            max_diff = np.max(bass_diff) if len(bass_diff) > 0 else 1.0

            drops = []
            for i, diff in enumerate(bass_diff):
                if diff > threshold:
                    time = start_s + (i * hop_size / sr)
                    intensity = diff / max_diff if max_diff > 0 else 0.5
                    drops.append({
                        'time': float(time),
                        'intensity': float(intensity)
                    })

            return drops

        except ImportError:
            # Fallback without librosa
            return self._detect_bass_drops_fallback(start_s, end_s)
        except Exception as e:
            logger.warning(f"Bass drop detection failed: {e}")
            return []

    def _detect_bass_drops_fallback(self, start_s: float = 0, end_s: float = None) -> List[Dict]:
        """Detect bass drops without librosa (approximation)."""
        y, sr = self._load_audio()
        if y is None:
            return []

        try:
            from scipy.signal import butter, filtfilt, find_peaks

            start_sample = int(start_s * sr)
            end_sample = int(end_s * sr) if end_s else len(y)
            y_segment = y[start_sample:end_sample]

            # Low-pass filter
            nyquist = sr / 2
            low_cutoff = min(0.99, 150 / nyquist)  # Ensure cutoff is valid
            b, a = butter(4, low_cutoff, btype='low')
            bass = filtfilt(b, a, y_segment)

            # Energy envelope
            frame_size = int(sr * 0.05)
            hop_size = frame_size // 2

            energy = []
            for i in range(0, len(bass) - frame_size, hop_size):
                frame = bass[i:i + frame_size]
                energy.append(np.sum(frame ** 2))

            energy = np.array(energy)
            if len(energy) < 5:
                return []

            # Find peaks
            peaks, properties = find_peaks(energy, height=np.percentile(energy, 80))
            max_height = np.max(energy) if len(energy) > 0 else 1.0

            drops = []
            for peak in peaks:
                time = start_s + (peak * hop_size / sr)
                intensity = energy[peak] / max_height if max_height > 0 else 0.5
                drops.append({
                    'time': float(time),
                    'intensity': float(intensity)
                })

            return drops

        except Exception as e:
            logger.warning(f"Bass drop fallback failed: {e}")
            return []

    def get_energy_profile(self, start_s: float = 0, end_s: float = None,
                           resolution: float = 0.1) -> List[Dict]:
        """
        Get energy profile of the audio over time.

        resolution: time step in seconds
        Returns list of dicts with time and energy (0-1 normalized).
        """
        y, sr = self._load_audio()
        if y is None:
            return []

        try:
            start_sample = int(start_s * sr)
            end_sample = int(end_s * sr) if end_s else len(y)
            y_segment = y[start_sample:end_sample]

            frame_size = int(sr * resolution)

            profile = []
            max_energy = 0

            # First pass: compute energies and find max
            energies = []
            for i in range(0, len(y_segment) - frame_size, frame_size):
                frame = y_segment[i:i + frame_size]
                energy = np.sqrt(np.mean(frame ** 2))  # RMS energy
                energies.append(energy)
                max_energy = max(max_energy, energy)

            # Second pass: normalize
            for i, energy in enumerate(energies):
                time = start_s + (i * resolution)
                normalized = energy / max_energy if max_energy > 0 else 0
                profile.append({
                    'time': float(time),
                    'energy': float(normalized)
                })

            return profile

        except Exception as e:
            logger.warning(f"Energy profile failed: {e}")
            return []

    def cleanup(self):
        """Clean up temporary audio file."""
        if self._audio_path and os.path.exists(self._audio_path):
            try:
                os.remove(self._audio_path)
            except OSError:
                pass
            self._audio_path = None

    def __del__(self):
        self.cleanup()


def align_cuts_to_beats(cuts: List[float], beats: List[float],
                        max_shift: float = 0.3) -> List[float]:
    """
    Align cut times to nearest beat timestamps.

    cuts: list of desired cut timestamps
    beats: list of beat timestamps
    max_shift: maximum time to shift a cut (seconds)

    Returns adjusted cut times aligned to beats.
    """
    if not beats:
        return cuts

    aligned = []
    for cut in cuts:
        # Find nearest beat
        nearest_beat = min(beats, key=lambda b: abs(b - cut))
        shift = nearest_beat - cut

        # Only shift if within max_shift
        if abs(shift) <= max_shift:
            aligned.append(nearest_beat)
        else:
            aligned.append(cut)

    return aligned


def get_beat_synced_segments(video_path: str, start_s: float, end_s: float,
                             target_cuts: int = None) -> List[Dict]:
    """
    Create segment list with cuts aligned to audio beats.

    Returns list of segments with start_s and end_s.
    """
    analyzer = AudioAnalyzer(video_path)

    try:
        # Detect beats and BPM
        bpm = analyzer.detect_bpm(start_s, end_s)
        beats = analyzer.detect_beats(start_s, end_s)

        if not beats:
            return [{'start_s': start_s, 'end_s': end_s}]

        # If target_cuts specified, select subset of beats
        if target_cuts and len(beats) > target_cuts + 1:
            # Select evenly spaced beats
            step = len(beats) // (target_cuts + 1)
            selected_beats = [beats[i * step] for i in range(target_cuts + 1)]
            selected_beats = [b for b in selected_beats if start_s <= b <= end_s]
        else:
            selected_beats = [b for b in beats if start_s <= b <= end_s]

        # Ensure start and end are included
        if not selected_beats or selected_beats[0] > start_s + 0.5:
            selected_beats.insert(0, start_s)
        if selected_beats[-1] < end_s - 0.5:
            selected_beats.append(end_s)

        # Create segments
        segments = []
        for i in range(len(selected_beats) - 1):
            seg_start = selected_beats[i]
            seg_end = selected_beats[i + 1]
            if seg_end - seg_start >= 0.3:  # Minimum segment duration
                segments.append({
                    'start_s': seg_start,
                    'end_s': seg_end,
                    'is_beat_aligned': True
                })

        return segments if segments else [{'start_s': start_s, 'end_s': end_s}]

    finally:
        analyzer.cleanup()
