"""
Bunny Clip Tool — Core Video Processor
Cuts video into 7-second clips, adds text overlays and music.
"""

import os
import json
import uuid
import random
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "templates.json"
SOUNDS_PATH = Path(__file__).parent.parent / "static" / "sounds"
OUTPUTS_PATH = Path(__file__).parent.parent / "static" / "outputs"


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_available_titles(config: dict) -> list[str]:
    return config.get("title_presets", [])


def get_sound_path(config: dict, sound_id: Optional[str] = None) -> Optional[str]:
    """Return path to a sound file. If no sound_id given, picks a random one."""
    library = config.get("sound_library", [])
    if not library:
        return None
    if sound_id:
        match = next((s for s in library if s["id"] == sound_id), None)
        sound = match if match else random.choice(library)
    else:
        sound = random.choice(library)
    path = SOUNDS_PATH / sound["file"]
    return str(path) if path.exists() else None


def process_video(
    input_path: str,
    job_id: str,
    custom_titles: Optional[list[str]] = None,
    sound_id: Optional[str] = None,
    text_style_key: str = "default",
    clip_duration: int = 7,
) -> dict:
    """
    Main processing function.
    
    Args:
        input_path: Path to uploaded video file
        job_id: Unique job identifier
        custom_titles: List of custom title strings (overrides presets if provided)
        sound_id: Sound ID from library, or None for random
        text_style_key: Key from text_styles config
        clip_duration: Seconds per clip (default 7)
    
    Returns:
        dict with job_id, clip_count, output_dir, clip_paths, status
    """
    try:
        # Import here so app still starts even if moviepy not installed yet
        from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, TextClip
        from moviepy.video.fx.all import fadein, fadeout
    except ImportError:
        return {
            "job_id": job_id,
            "status": "error",
            "error": "moviepy not installed. Run: pip install moviepy"
        }

    config = load_config()
    clip_settings = config["clip_settings"]
    titles_pool = custom_titles if custom_titles else get_available_titles(config)
    text_style = config["text_styles"].get(text_style_key, config["text_styles"]["default"])
    sound_path = get_sound_path(config, sound_id)

    output_dir = OUTPUTS_PATH / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    fade_in = clip_settings["fade_in_seconds"]
    fade_out = clip_settings["fade_out_seconds"]

    clip_paths = []
    errors = []

    try:
        source = VideoFileClip(input_path)
        total_duration = source.duration
        logger.info(f"[{job_id}] Source video duration: {total_duration:.1f}s")

        # Calculate how many clips we can make
        n_clips = int(total_duration // clip_duration)
        if n_clips == 0:
            source.close()
            return {
                "job_id": job_id,
                "status": "error",
                "error": f"Video too short. Minimum {clip_duration} seconds required."
            }

        logger.info(f"[{job_id}] Generating {n_clips} clips of {clip_duration}s each")

        # Load audio
        audio_clip = None
        if sound_path:
            try:
                audio_clip = AudioFileClip(sound_path)
            except Exception as e:
                logger.warning(f"[{job_id}] Could not load sound: {e}")

        for i in range(n_clips):
            try:
                start = i * clip_duration
                end = start + clip_duration

                # Cut video segment
                segment = source.subclip(start, end)

                # Apply fade
                segment = fadein(segment, fade_in)
                segment = fadeout(segment, fade_out)

                # Pick title
                title_text = titles_pool[i % len(titles_pool)] if titles_pool else ""

                # Build text overlay
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
                        loop_audio = loop_audio.volumex(clip_settings["audio_volume"])
                        final_clip = final_clip.set_audio(loop_audio)
                    except Exception as e:
                        logger.warning(f"[{job_id}] Clip {i+1}: audio error: {e}")

                # Export
                out_file = output_dir / f"clip_{i+1:03d}.mp4"
                final_clip.write_videofile(
                    str(out_file),
                    fps=clip_settings["output_fps"],
                    codec="libx264",
                    audio_codec="aac",
                    logger=None,
                    temp_audiofile=str(output_dir / f"temp_audio_{i}.m4a"),
                )

                clip_paths.append(str(out_file))
                logger.info(f"[{job_id}] ✅ Clip {i+1}/{n_clips} done")

                # Cleanup
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
        return {
            "job_id": job_id,
            "status": "error",
            "error": str(e)
        }

    return {
        "job_id": job_id,
        "status": "done" if not errors else "partial",
        "clip_count": len(clip_paths),
        "clip_paths": clip_paths,
        "output_dir": str(output_dir),
        "errors": errors,
        "titles_used": titles_pool[:n_clips],
    }


def _build_text_clip(text: str, style: dict, duration: float, video_size: tuple):
    """Build a TextClip overlay with the given style."""
    try:
        from moviepy.editor import TextClip
        position = style.get("position", "bottom")
        size_w = video_size[0]

        txt = TextClip(
            text,
            fontsize=style.get("size", 52),
            font=style.get("font", "Arial-Bold"),
            color=style.get("color", "white"),
            stroke_color=style.get("stroke_color", "black"),
            stroke_width=style.get("stroke_width", 2),
            method="caption",
            size=(int(size_w * 0.9), None),
            align="center",
        ).set_duration(duration)

        # Position
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
    from moviepy.editor import AudioFileClip, concatenate_audioclips
    if audio_clip.duration >= target_duration:
        return audio_clip.subclip(0, target_duration)
    else:
        repeats = int(target_duration / audio_clip.duration) + 1
        looped = concatenate_audioclips([audio_clip] * repeats)
        return looped.subclip(0, target_duration)
