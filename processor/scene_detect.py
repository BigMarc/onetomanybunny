"""
processor/scene_detect.py — Video duration and timestamp selection.

Selects evenly spaced timestamps for clip extraction,
avoiding the first and last 2 seconds of the video.
"""

import subprocess


def get_duration(video_path: str) -> float:
    """Get video duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def select_timestamps(
    duration: float, clip_dur: float, count: int
) -> list[float]:
    """Select evenly spaced timestamps, avoiding the first/last 2 seconds."""
    safe_start = 2.0
    safe_end = max(duration - clip_dur - 2.0, safe_start + clip_dur)
    usable = safe_end - safe_start

    if usable <= 0:
        return [0.0]

    actual_count = min(count, int(usable / clip_dur))
    if actual_count <= 0:
        return [safe_start]

    step = usable / actual_count
    return [round(safe_start + i * step, 2) for i in range(actual_count)]
