"""
processor/clip_generator.py — FFmpeg clip creation.

Generates a single clip from a source video with:
- 9:16 vertical scaling (1080x1920)
- Rotating text overlay
- Random background music from the sounds/ directory
"""

import glob
import os
import random
import subprocess

from processor.text_overlay import get_overlay_text, build_drawtext_filter

SOUNDS_DIR = os.path.join(os.path.dirname(__file__), "..", "sounds")


def generate_clip(
    source_path: str,
    output_path: str,
    start_time: float,
    duration: int,
    creator_name: str,
    clip_number: int,
) -> None:
    """Generate a single clip with text overlay and background music using FFmpeg."""

    # Pick random music track
    music_files = glob.glob(os.path.join(SOUNDS_DIR, "*.mp3"))
    music_file = random.choice(music_files) if music_files else None

    # Build overlay text
    text = get_overlay_text(creator_name, clip_number)
    drawtext = build_drawtext_filter(text)

    # Video filter: scale to 1080x1920 (9:16) + text overlay
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,"
        f"{drawtext}"
    )

    if music_file:
        # Use music track as audio, replacing original audio
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-i", source_path,
            "-i", music_file,
            "-t", str(duration),
            "-vf", vf,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            "-movflags", "+faststart",
            output_path,
        ]
    else:
        # No music — keep original audio
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-i", source_path,
            "-t", str(duration),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]

    subprocess.run(cmd, check=True, capture_output=True, text=True)
