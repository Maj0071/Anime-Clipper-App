#!/usr/bin/env python3
"""
Test script for the Auto-Editor on One Piece video.

Tests the viral anime editing features:
- Beat sync
- White flash effects
- Smart reframing (face tracking)
- Screen shake
- Speed ramping (velocity edits)
- Hook optimization
- Multiple templates
"""

import os
import sys
import json
import subprocess
from datetime import datetime

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.workers.auto_editor import AutoEditRenderer


def get_video_info(video_path: str) -> dict:
    """Get video duration and basic info using ffprobe."""
    cmd = [
        'ffprobe', '-v', 'quiet', '-print_format', 'json',
        '-show_format', '-show_streams', video_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
        duration = float(data['format']['duration'])

        # Get video stream info
        video_stream = None
        for stream in data.get('streams', []):
            if stream['codec_type'] == 'video':
                video_stream = stream
                break

        return {
            'duration': duration,
            'width': int(video_stream['width']) if video_stream else 1920,
            'height': int(video_stream['height']) if video_stream else 1080,
            'fps': eval(video_stream['r_frame_rate']) if video_stream else 24,
        }
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"Error getting video info: {e}")
        return {'duration': 60, 'width': 1920, 'height': 1080, 'fps': 24}


def find_action_segments(video_path: str, duration: float) -> list:
    """
    Find high-action segments in the video using motion detection.

    For testing, we'll also provide manual segments for the One Piece Galaxy Impact scene.
    """
    # For the Galaxy Impact scene, the climax is typically in the middle/later portion
    # We'll create test segments focusing on different parts

    # Create segments spanning different parts of the video
    segment_length = 8.0  # Each segment is 8 seconds
    segments = []

    # Sample from different parts of the video
    # Start from 10% into the video to skip intros
    start_offset = duration * 0.1

    # Create 3-4 segments
    for i in range(4):
        start = start_offset + (i * (duration - start_offset) / 5)
        end = min(start + segment_length, duration - 1)
        if end - start > 2:  # At least 2 seconds
            segments.append({
                'start_s': start,
                'end_s': end,
            })

    return segments


def run_test(video_path: str, template: str, aspect: str, output_suffix: str,
             enable_features: dict) -> str:
    """Run a single test with specified settings."""

    video_info = get_video_info(video_path)
    duration = video_info['duration']

    print(f"\n{'='*60}")
    print(f"Testing: {template} template ({aspect})")
    print(f"Video duration: {duration:.1f}s")
    print(f"Resolution: {video_info['width']}x{video_info['height']}")
    print(f"Features: {enable_features}")
    print('='*60)

    # Create output directory
    output_dir = "/tmp/videos/test_output"
    os.makedirs(output_dir, exist_ok=True)

    # Generate output filename
    timestamp = datetime.now().strftime("%H%M%S")
    output_path = os.path.join(output_dir, f"test_{template}_{aspect.replace(':', 'x')}_{output_suffix}_{timestamp}.mp4")

    # Find action segments
    segments = find_action_segments(video_path, duration)
    print(f"Found {len(segments)} segments to render:")
    for i, seg in enumerate(segments):
        print(f"  Segment {i+1}: {seg['start_s']:.1f}s - {seg['end_s']:.1f}s ({seg['end_s']-seg['start_s']:.1f}s)")

    # Create renderer
    config = {
        'loudness': '-14',
        'max_duration': 30,  # Max 30 seconds
    }

    renderer = AutoEditRenderer(video_path, output_path, config)

    # Run render with viral features
    print(f"\nRendering with {template} template...")

    try:
        result = renderer.render(
            segments=segments,
            template_name=template,
            aspect=aspect,
            enable_beat_sync=enable_features.get('beat_sync', False),
            caption_text=enable_features.get('caption'),
            caption_style=enable_features.get('caption_style', 'pop'),
            enable_smart_reframe=enable_features.get('smart_reframe', True),
            hook_text=enable_features.get('hook_text'),
            hook_style=enable_features.get('hook_style', 'bold'),
            reorder_for_hook=enable_features.get('reorder_hook', False),
        )

        if result and os.path.exists(result):
            file_size = os.path.getsize(result) / (1024 * 1024)
            print(f"\n✓ SUCCESS! Output: {result}")
            print(f"  File size: {file_size:.2f} MB")
            return result
        else:
            print(f"\n✗ FAILED: No output file generated")
            return None

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    # Path to the One Piece video
    video_path = "/Users/majed/Desktop/Anime-Clipper-App-1/Garp GALAXY IMPACT One Piece Episode 1114 _ 4K 60FPS _.mp4"

    if not os.path.exists(video_path):
        print(f"Error: Video file not found: {video_path}")
        return 1

    print("="*60)
    print("AUTO-EDITOR TEST SUITE")
    print("="*60)
    print(f"\nVideo: {os.path.basename(video_path)}")

    # Get video info
    info = get_video_info(video_path)
    print(f"Duration: {info['duration']:.1f}s | Resolution: {info['width']}x{info['height']} | FPS: {info['fps']:.1f}")

    results = []

    # Test 1: Viral Anime template with all features (TikTok vertical)
    result = run_test(
        video_path=video_path,
        template='viral_anime',
        aspect='9:16',
        output_suffix='viral',
        enable_features={
            'beat_sync': True,
            'smart_reframe': True,
            'hook_text': 'Galaxy Impact! 💥',
            'hook_style': 'bold',
            'caption': 'When Garp goes all out...',
            'caption_style': 'pop',
        }
    )
    results.append(('viral_anime (9:16)', result))

    # Test 2: Anime Hype template (velocity edits)
    result = run_test(
        video_path=video_path,
        template='anime_hype',
        aspect='9:16',
        output_suffix='hype',
        enable_features={
            'beat_sync': True,
            'smart_reframe': True,
            'hook_text': 'This scene hits different',
            'hook_style': 'neon',
        }
    )
    results.append(('anime_hype (9:16)', result))

    # Test 3: Cinematic template (1:1 square for Instagram)
    result = run_test(
        video_path=video_path,
        template='cinematic',
        aspect='1:1',
        output_suffix='cinema',
        enable_features={
            'smart_reframe': True,
            'caption': 'Peak One Piece',
            'caption_style': 'glow',
        }
    )
    results.append(('cinematic (1:1)', result))

    # Test 4: Glitch template (cyberpunk style)
    result = run_test(
        video_path=video_path,
        template='glitch',
        aspect='9:16',
        output_suffix='glitch',
        enable_features={
            'smart_reframe': True,
            'hook_text': 'GARP GOES CRAZY',
            'hook_style': 'glitch',
        }
    )
    results.append(('glitch (9:16)', result))

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    success_count = 0
    for name, path in results:
        if path:
            success_count += 1
            print(f"✓ {name}: {path}")
        else:
            print(f"✗ {name}: FAILED")

    print(f"\nTotal: {success_count}/{len(results)} tests passed")

    if success_count > 0:
        print(f"\nOutput files saved to: /tmp/videos/test_output/")
        print("You can preview them with: open /tmp/videos/test_output/")

    return 0 if success_count == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
