"""
Video Download Service - Downloads clips from various sources using yt-dlp.

Supports YouTube, Reddit, and other platforms with quality selection
and segment extraction capabilities.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any
import uuid

logger = logging.getLogger(__name__)

# Default download directory
DOWNLOAD_DIR = Path("/tmp/videos/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class DownloadResult:
    """Result of a video download operation."""
    success: bool
    file_path: Optional[str]
    title: Optional[str]
    duration: Optional[float]
    resolution: Optional[str]
    file_size: Optional[int]
    error: Optional[str] = None


@dataclass
class VideoInfo:
    """Metadata about a video before downloading."""
    id: str
    title: str
    duration: float
    formats: List[Dict[str, Any]]
    thumbnail: Optional[str]
    resolution: Optional[str]
    uploader: Optional[str]


class VideoDownloadService:
    """Service for downloading videos using yt-dlp."""

    def __init__(self, download_dir: Optional[Path] = None):
        self.download_dir = download_dir or DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._check_yt_dlp()

    def _check_yt_dlp(self):
        """Check if yt-dlp is installed."""
        try:
            result = subprocess.run(
                ["yt-dlp", "--version"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                logger.info(f"yt-dlp version: {result.stdout.strip()}")
            else:
                logger.warning("yt-dlp not found, downloads will fail")
        except FileNotFoundError:
            logger.warning("yt-dlp not installed, downloads will fail")

    async def get_video_info(self, url: str) -> Optional[VideoInfo]:
        """
        Get video metadata without downloading.

        Args:
            url: Video URL

        Returns:
            VideoInfo object or None if failed
        """
        try:
            cmd = [
                "yt-dlp",
                "--dump-json",
                "--no-download",
                "--no-warnings",
                url,
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"Failed to get video info: {stderr.decode()}")
                return None

            data = json.loads(stdout.decode())

            # Find best resolution
            resolution = None
            for fmt in data.get("formats", []):
                if fmt.get("height"):
                    res = f"{fmt['height']}p"
                    if resolution is None or int(fmt["height"]) > int(resolution.replace("p", "")):
                        resolution = res

            return VideoInfo(
                id=data.get("id", ""),
                title=data.get("title", ""),
                duration=data.get("duration", 0),
                formats=data.get("formats", []),
                thumbnail=data.get("thumbnail"),
                resolution=resolution,
                uploader=data.get("uploader"),
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse video info: {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return None

    async def download_clip(
        self,
        url: str,
        max_height: int = 1080,
        output_filename: Optional[str] = None,
    ) -> DownloadResult:
        """
        Download a video clip with quality selection.

        Args:
            url: Video URL
            max_height: Maximum video height (default 1080p)
            output_filename: Custom output filename (without extension)

        Returns:
            DownloadResult with file path and metadata
        """
        try:
            # Generate output filename if not provided
            if output_filename is None:
                output_filename = str(uuid.uuid4())

            output_path = self.download_dir / f"{output_filename}.%(ext)s"
            final_path = self.download_dir / f"{output_filename}.mp4"

            # Format selection: best video up to max_height + best audio
            format_spec = f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best"

            cmd = [
                "yt-dlp",
                "-f", format_spec,
                "--merge-output-format", "mp4",
                "-o", str(output_path),
                "--no-playlist",
                "--no-warnings",
                "--progress",
                url,
            ]

            logger.info(f"Downloading: {url}")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"Download failed: {error_msg}")
                return DownloadResult(
                    success=False,
                    file_path=None,
                    title=None,
                    duration=None,
                    resolution=None,
                    file_size=None,
                    error=error_msg,
                )

            # Find the downloaded file (extension might vary)
            downloaded_files = list(self.download_dir.glob(f"{output_filename}.*"))
            if not downloaded_files:
                return DownloadResult(
                    success=False,
                    file_path=None,
                    title=None,
                    duration=None,
                    resolution=None,
                    file_size=None,
                    error="Downloaded file not found",
                )

            actual_path = downloaded_files[0]

            # Get video metadata
            metadata = await self._get_file_metadata(actual_path)

            return DownloadResult(
                success=True,
                file_path=str(actual_path),
                title=metadata.get("title"),
                duration=metadata.get("duration"),
                resolution=metadata.get("resolution"),
                file_size=actual_path.stat().st_size,
            )

        except Exception as e:
            logger.error(f"Download error: {e}")
            return DownloadResult(
                success=False,
                file_path=None,
                title=None,
                duration=None,
                resolution=None,
                file_size=None,
                error=str(e),
            )

    async def download_from_suggestion(
        self,
        suggestion_id: str,
        url: str,
        db_session=None,
    ) -> DownloadResult:
        """
        Download a clip from a ClipSuggestion and update the database.

        Args:
            suggestion_id: ID of the ClipSuggestion
            url: Video URL
            db_session: Optional database session

        Returns:
            DownloadResult
        """
        result = await self.download_clip(
            url=url,
            output_filename=suggestion_id,
        )

        if result.success and db_session:
            from app.models import ClipSuggestion

            suggestion = db_session.query(ClipSuggestion).filter(
                ClipSuggestion.id == suggestion_id
            ).first()

            if suggestion:
                suggestion.is_downloaded = 1
                suggestion.local_path = result.file_path
                db_session.commit()

        return result

    async def extract_segment(
        self,
        video_path: str,
        start: float,
        end: float,
        output_filename: Optional[str] = None,
    ) -> DownloadResult:
        """
        Extract a segment from a video using FFmpeg.

        Args:
            video_path: Path to source video
            start: Start time in seconds
            end: End time in seconds
            output_filename: Custom output filename (without extension)

        Returns:
            DownloadResult with extracted segment path
        """
        try:
            if not os.path.exists(video_path):
                return DownloadResult(
                    success=False,
                    file_path=None,
                    title=None,
                    duration=None,
                    resolution=None,
                    file_size=None,
                    error=f"Source file not found: {video_path}",
                )

            if output_filename is None:
                output_filename = f"segment_{uuid.uuid4()}"

            output_path = self.download_dir / f"{output_filename}.mp4"
            duration = end - start

            cmd = [
                "ffmpeg",
                "-y",
                "-ss", str(start),
                "-i", video_path,
                "-t", str(duration),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path),
            ]

            logger.info(f"Extracting segment: {start}s - {end}s from {video_path}")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "FFmpeg extraction failed"
                logger.error(f"Segment extraction failed: {error_msg}")
                return DownloadResult(
                    success=False,
                    file_path=None,
                    title=None,
                    duration=None,
                    resolution=None,
                    file_size=None,
                    error=error_msg,
                )

            metadata = await self._get_file_metadata(output_path)

            return DownloadResult(
                success=True,
                file_path=str(output_path),
                title=None,
                duration=duration,
                resolution=metadata.get("resolution"),
                file_size=output_path.stat().st_size,
            )

        except Exception as e:
            logger.error(f"Segment extraction error: {e}")
            return DownloadResult(
                success=False,
                file_path=None,
                title=None,
                duration=None,
                resolution=None,
                file_size=None,
                error=str(e),
            )

    async def remove_watermark(
        self,
        video_path: str,
        regions: List[Dict[str, int]],
        method: str = "blur",
        output_filename: Optional[str] = None,
    ) -> DownloadResult:
        """
        Remove watermarks from specific regions of a video.

        Args:
            video_path: Path to source video
            regions: List of regions to process, each with x, y, w, h
            method: 'blur' or 'crop'
            output_filename: Custom output filename

        Returns:
            DownloadResult with processed video path
        """
        try:
            if not os.path.exists(video_path):
                return DownloadResult(
                    success=False,
                    file_path=None,
                    title=None,
                    duration=None,
                    resolution=None,
                    file_size=None,
                    error=f"Source file not found: {video_path}",
                )

            if output_filename is None:
                output_filename = f"clean_{uuid.uuid4()}"

            output_path = self.download_dir / f"{output_filename}.mp4"

            if method == "blur":
                # Build blur filter for each region
                filters = []
                for i, region in enumerate(regions):
                    x, y, w, h = region["x"], region["y"], region["w"], region["h"]
                    # Create blurred version of region
                    filters.append(
                        f"[0:v]crop={w}:{h}:{x}:{y},boxblur=10:2[blur{i}];"
                        f"[0:v][blur{i}]overlay={x}:{y}"
                    )

                if not filters:
                    # No regions, just copy
                    shutil.copy(video_path, output_path)
                else:
                    # Apply blur filters
                    filter_complex = filters[0]  # Simplified for single region
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-i", video_path,
                        "-filter_complex", filter_complex,
                        "-c:a", "copy",
                        str(output_path),
                    ]

                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await process.communicate()

            elif method == "crop":
                # Get video dimensions first
                metadata = await self._get_file_metadata(Path(video_path))
                if not metadata.get("width") or not metadata.get("height"):
                    return DownloadResult(
                        success=False,
                        file_path=None,
                        title=None,
                        duration=None,
                        resolution=None,
                        file_size=None,
                        error="Could not get video dimensions",
                    )

                width = metadata["width"]
                height = metadata["height"]

                # Calculate safe crop area (exclude watermark regions)
                crop_h = height
                crop_w = width
                crop_x = 0
                crop_y = 0

                for region in regions:
                    # If watermark is in corner, crop it out
                    if region["y"] + region["h"] >= height - 50:
                        crop_h = region["y"]
                    if region["y"] <= 50:
                        crop_y = region["y"] + region["h"]
                        crop_h -= crop_y

                cmd = [
                    "ffmpeg",
                    "-y",
                    "-i", video_path,
                    "-filter:v", f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}",
                    "-c:a", "copy",
                    str(output_path),
                ]

                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await process.communicate()

            if not output_path.exists():
                return DownloadResult(
                    success=False,
                    file_path=None,
                    title=None,
                    duration=None,
                    resolution=None,
                    file_size=None,
                    error="Output file not created",
                )

            metadata = await self._get_file_metadata(output_path)

            return DownloadResult(
                success=True,
                file_path=str(output_path),
                title=None,
                duration=metadata.get("duration"),
                resolution=metadata.get("resolution"),
                file_size=output_path.stat().st_size,
            )

        except Exception as e:
            logger.error(f"Watermark removal error: {e}")
            return DownloadResult(
                success=False,
                file_path=None,
                title=None,
                duration=None,
                resolution=None,
                file_size=None,
                error=str(e),
            )

    async def _get_file_metadata(self, file_path: Path) -> Dict[str, Any]:
        """Get metadata from a video file using ffprobe."""
        try:
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(file_path),
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, _ = await process.communicate()

            if process.returncode != 0:
                return {}

            data = json.loads(stdout.decode())

            metadata = {
                "title": data.get("format", {}).get("tags", {}).get("title"),
                "duration": float(data.get("format", {}).get("duration", 0)),
            }

            # Find video stream for resolution
            for stream in data.get("streams", []):
                if stream.get("codec_type") == "video":
                    metadata["width"] = stream.get("width")
                    metadata["height"] = stream.get("height")
                    if stream.get("height"):
                        metadata["resolution"] = f"{stream['height']}p"
                    break

            return metadata

        except Exception as e:
            logger.error(f"Error getting metadata: {e}")
            return {}

    def cleanup_old_downloads(self, max_age_hours: int = 24):
        """Remove downloaded files older than max_age_hours."""
        import time

        cutoff = time.time() - (max_age_hours * 3600)

        for file_path in self.download_dir.iterdir():
            if file_path.is_file() and file_path.stat().st_mtime < cutoff:
                try:
                    file_path.unlink()
                    logger.info(f"Cleaned up old download: {file_path}")
                except Exception as e:
                    logger.error(f"Failed to clean up {file_path}: {e}")
