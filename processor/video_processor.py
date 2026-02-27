"""
Bunny Clip Tool — Core Video Processor
Cuts video into 7-second clips, adds text overlays and music.
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional

from config.settings import CLIP_DURATION, TEXT_FONT_SIZE, TEXT_POSITION

logger = logging.getLogger(__name__)

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
    """Build a TextClip overlay with the given style."""
    try:
        from moviepy.editor import TextClip

        position = style.get("position", TEXT_POSITION)
        size_w = video_size[0]

        txt = TextClip(
            text,
            fontsize=style.get("size", TEXT_FONT_SIZE),
            font=style.get("font", "Arial-Bold"),
            color=style.get("color", "white"),
            stroke_color=style.get("stroke_color", "black"),
            stroke_width=style.get("stroke_width", 2),
            method="caption",
            size=(int(size_w * 0.9), None),
            align="center",
        ).set_duration(duration)

        if position == "bottom":
            margin = style.get("margin_bottom", 80)
            txt = txt.set_position(("center", video_size[1] - txt.size[1] - margin))
        elif position == "top":
            margin = style.get("margin_top", 60)
            txt = txt.set_position(("center", margin))
        elif position == "center":
            txt = txt.set_position("center")

        return txt

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
