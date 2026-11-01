"""Draw the report's page background (1920×1080): snow-white page, thin maple-red side bands
(a nod to the flag's red–white–red) and a faint maple leaf watermark in the lower-right corner.

    uv run python powerbi/make_background.py

Visuals have white backgrounds, so the decoration only shows in the gaps between them and never
reduces readability. The leaf is an original stylised drawing.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = (
    Path(__file__).parent
    / "canadian_financial_lakehouse.Report"
    / "StaticResources"
    / "RegisteredResources"
    / "cfl_background.png"
)
W, H = 1920, 1080
SNOW = (238, 243, 248)
MAPLE = (200, 16, 46)

# Right half of a stylised 11-point maple leaf in a 100 × 100 box (y downwards), mirrored for the left half.
RIGHT = [(50, 2), (57, 16), (63, 12), (61, 32), (71, 21), (74, 28), (86, 25), (81, 38), (90, 42), (71, 56),
         (74, 63), (55, 59), (53, 76), (52, 76), (52, 92)]  # fmt: skip
LEAF = RIGHT + [(100 - x, y) for x, y in reversed(RIGHT)]


def leaf(size: int, opacity: int) -> Image.Image:
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(layer).polygon([(x * size / 100, y * size / 100) for x, y in LEAF], fill=(*MAPLE, opacity))
    return layer.filter(ImageFilter.GaussianBlur(1))


def main() -> None:
    page = Image.new("RGBA", (W, H), (*SNOW, 255))
    draw = ImageDraw.Draw(page)
    band = 14
    draw.rectangle([0, 0, band, H], fill=(*MAPLE, 255))
    draw.rectangle([W - band, 0, W, H], fill=(*MAPLE, 255))
    size = 520
    page.alpha_composite(leaf(size, 22), (W - size - 30, H - size + 60))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    page.convert("RGB").save(OUT, optimize=True)
    print(f"{OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
