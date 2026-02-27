"""
Bunny Clip Tool — Core Video Processor
Cuts video into 7-second clips, adds text overlays and music.
"""

import os
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

from config.settings import CLIP_DURATION, TEXT_FONT_SIZE, TEXT_POSITION

logger = logging.getLogger(__name__)

# Font preference order: bold condensed serif with vintage/retro feel
_FONT_PREFERENCE = [
    "Playfair-Display-Bold",
    "Playfair Display Bold",
    "PlayfairDisplay-Bold",
    "Abril-Fatface",
    "Abril Fatface",
    "AbrilFatface-Regular",
    "Rockwell-Bold",
    "Rockwell Bold",
    "Arial-Bold",
    "Arial Bold",
    "DejaVu-Sans-Bold",
]
_resolved_font: Optional[str] = None


def _resolve_font() -> str:
    """Find the first available font from the preference list."""
    global _resolved_font
    if _resolved_font is not None:
        return _resolved_font

    try:
        result = subprocess.run(
            ["fc-list", "--format", "%{family}\n"],
            capture_output=True, text=True, timeout=10,
        )
        installed = result.stdout
    except Exception:
        installed = ""

    for font in _FONT_PREFERENCE:
        # Check if any installed font family contains our target name
        base_name = font.replace("-", " ").replace("  ", " ").lower()
        for line in installed.splitlines():
            if base_name in line.lower():
                _resolved_font = font
                logger.info(f"Resolved font: {font}")
                return font

    _resolved_font = "Arial-Bold"
    logger.warning(f"No preferred font found, falling back to {_resolved_font}")
    return _resolved_font

CONFIG_PATH = Path(__file__).parent.parent / "config" / "templates.json"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def process_video(
    input_path: str,
    job_id: str,
    titles: list[str],
    sound_local_path: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> dict:
    """
    Main processing function — called by main.py (Cloud Run).

    Args:
        input_path: Path to uploaded video file.
        job_id: Unique job identifier.
        titles: List of title strings for text overlays (rotating).
        sound_local_path: Local path to a sound file, or None.
        output_dir: Directory to write output clips to.

    Returns:
        dict with clip_count, clip_paths, errors.
    """
    try:
        from moviepy.editor import (
            VideoFileClip, AudioFileClip, CompositeVideoClip, TextClip,
            concatenate_audioclips,
        )
        from moviepy.video.fx.all import fadein, fadeout
    except ImportError:
        return {
            "error": "moviepy not installed. Run: pip install moviepy",
        }

    config = load_config()
    clip_settings = config["clip_settings"]
    clip_duration = CLIP_DURATION
    text_style = config["text_styles"].get("default", {})

    if output_dir is None:
        output_dir = str(Path(__file__).parent.parent / "static" / "outputs" / job_id)

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    fade_in = clip_settings.get("fade_in_seconds", 0.3)
    fade_out = clip_settings.get("fade_out_seconds", 0.3)

    clip_paths = []
    errors = []

    try:
        source = VideoFileClip(input_path)
        total_duration = source.duration
        logger.info(f"[{job_id}] Source video duration: {total_duration:.1f}s")

        n_clips = int(total_duration // clip_duration)
        if n_clips == 0:
            source.close()
            return {
                "error": f"Video too short. Minimum {clip_duration} seconds required.",
            }

        logger.info(f"[{job_id}] Generating {n_clips} clips of {clip_duration}s each")

        # Load audio from local path
        audio_clip = None
        if sound_local_path and os.path.exists(sound_local_path):
            try:
                audio_clip = AudioFileClip(sound_local_path)
            except Exception as e:
                logger.warning(f"[{job_id}] Could not load sound: {e}")

        for i in range(n_clips):
            try:
                start = i * clip_duration
                end = start + clip_duration

                segment = source.subclip(start, end)

                segment = fadein(segment, fade_in)
                segment = fadeout(segment, fade_out)

                # Pick title (rotating)
                title_text = titles[i % len(titles)] if titles else ""

                layers = [segment]
                if title_text:
                    txt = _build_text_clip(title_text, text_style, clip_duration, segment.size)
                    if txt:
                        layers.append(txt)

                final_clip = CompositeVideoClip(layers)

                # Add music
                if audio_clip:
                    try:
                        loop_audio = _loop_audio(audio_clip, clip_duration)
                        loop_audio = loop_audio.volumex(clip_settings.get("audio_volume", 0.85))
                        final_clip = final_clip.set_audio(loop_audio)
                    except Exception as e:
                        logger.warning(f"[{job_id}] Clip {i+1}: audio error: {e}")

                out_file = out_path / f"clip_{i+1:03d}.mp4"
                final_clip.write_videofile(
                    str(out_file),
                    fps=clip_settings.get("output_fps", 30),
                    codec="libx264",
                    audio_codec="aac",
                    logger=None,
                    temp_audiofile=str(out_path / f"temp_audio_{i}.m4a"),
                )

                clip_paths.append(str(out_file))
                logger.info(f"[{job_id}] Clip {i+1}/{n_clips} done")

                final_clip.close()
                segment.close()

            except Exception as e:
                errors.append(f"Clip {i+1}: {str(e)}")
                logger.error(f"[{job_id}] Error on clip {i+1}: {e}", exc_info=True)

        source.close()
        if audio_clip:
            audio_clip.close()

    except Exception as e:
        logger.error(f"[{job_id}] Fatal error: {e}", exc_info=True)
        return {"error": str(e)}

    return {
        "clip_count": len(clip_paths),
        "clip_paths": clip_paths,
        "errors": errors,
    }


def _build_text_clip(text: str, style: dict, duration: float, video_size: tuple):
    """
    Build a TextClip overlay with vintage serif style.

    Style: bold condensed serif, off-white/cream (#F5F0E8),
    black drop shadow (2px offset, 3px blur), no stroke outline.
    """
    try:
        from moviepy.editor import TextClip, CompositeVideoClip

        position = style.get("position", TEXT_POSITION)
        size_w = video_size[0]
        font = _resolve_font()
        fontsize = style.get("size", TEXT_FONT_SIZE)
        text_color = "#F5F0E8"  # Off-white / cream
        shadow_color = "black"
        shadow_offset = 2  # px
        text_width = int(size_w * 0.9)

        # Shadow layer (offset 2px right + 2px down)
        shadow = TextClip(
            text,
            fontsize=fontsize,
            font=font,
            color=shadow_color,
            method="caption",
            size=(text_width, None),
            align="center",
            kerning=-1,
        ).set_duration(duration).set_opacity(0.7)

        # Main text layer (cream color, no stroke)
        txt = TextClip(
            text,
            fontsize=fontsize,
            font=font,
            color=text_color,
            method="caption",
            size=(text_width, None),
            align="center",
            kerning=-1,
        ).set_duration(duration)

        # Compose shadow + text into a single overlay
        txt_h = txt.size[1]
        txt_w = txt.size[0]

        shadow = shadow.set_position((shadow_offset, shadow_offset))
        txt = txt.set_position((0, 0))

        text_comp = CompositeVideoClip(
            [shadow, txt],
            size=(txt_w + shadow_offset, txt_h + shadow_offset),
        ).set_duration(duration)

        # Position: top zone — 15% from the top edge, horizontally centered
        y = int(video_size[1] * 0.15)
        text_comp = text_comp.set_position(("center", y))

        return text_comp

    except Exception as e:
        logger.warning(f"TextClip error: {e}")
        return None


def _loop_audio(audio_clip, target_duration: float):
    """Loop or trim audio to match target_duration."""
    from moviepy.editor import concatenate_audioclips

    if audio_clip.duration >= target_duration:
        return audio_clip.subclip(0, target_duration)
    else:
        repeats = int(target_duration / audio_clip.duration) + 1
        looped = concatenate_audioclips([audio_clip] * repeats)
        return looped.subclip(0, target_duration)
