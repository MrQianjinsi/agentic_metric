"""Generate the system tray icon image."""

from __future__ import annotations

from PIL import Image, ImageDraw


def create_icon() -> Image.Image:
    """Create a simple 64x64 icon: green circle on transparent background."""
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # Draw a filled green circle with a small margin
    margin = 4
    draw.ellipse(
        [margin, margin, size - margin, size - margin],
        fill=(76, 175, 80, 255),  # Material green
    )
    return image
