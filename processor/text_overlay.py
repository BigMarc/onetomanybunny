"""
processor/text_overlay.py — Rotating text overlay logic for clips.

Provides the overlay text phrases and FFmpeg drawtext filter string
for each clip number.
"""

PHRASES = [
    "@{creator} ",
    "Link in Bio",
    "Follow for more",
    "@{creator}",
    "Don't miss out",
]


def get_overlay_text(creator_name: str, clip_number: int) -> str:
    """Return the overlay text for a given clip number (1-indexed)."""
    template = PHRASES[(clip_number - 1) % len(PHRASES)]
    return template.format(creator=creator_name)


def build_drawtext_filter(text: str) -> str:
    """Build an FFmpeg drawtext filter string for the given text.

    Text is centered horizontally, positioned near the bottom of the frame.
    White text with a black border for readability.
    """
    safe_text = text.replace("'", "'\\''").replace(":", "\\:")
    return (
        f"drawtext=text='{safe_text}':"
        "fontsize=48:fontcolor=white:borderw=2:bordercolor=black:"
        "x=(w-text_w)/2:y=h-th-80"
    )
