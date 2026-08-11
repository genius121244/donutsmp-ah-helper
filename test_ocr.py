"""
test_ocr.py
Checks the reader without needing the game running.

  python test_ocr.py

1. Renders price strings exactly the way Minecraft does - glyphs blitted
   from the resource pack atlas, 1px drop shadow, nearest-neighbour scaled
   by the GUI scale - and reads them back at every GUI scale 1-4.
2. Reads the real in-game capture in samples/, if present.

Rendering from the same atlas the reader matches against is deliberate:
that IS what the game does, so a mismatch here means the reader's scale
detection, line splitting or glyph segmentation is wrong, which is what
these tests are for.
"""

import os
import sys

import numpy as np
from PIL import Image

import mcfont
import ocr

CELL_GRID = 16
LOGICAL_CELL = 8  # Minecraft draws every glyph cell 8 logical px wide
BG = (22, 7, 22)
FG = (252, 252, 252)
SHADOW = (63, 63, 63)


def _atlas():
    path = mcfont.find_atlas()
    if path is None:
        sys.exit("No ascii.png atlas found next to the macro.")
    img = Image.open(path).convert("RGBA")
    arr = np.asarray(img)
    mask = (arr[:, :, 3] > 128) & (arr[:, :, :3].max(axis=2) > 64)
    return mask, mask.shape[0] // CELL_GRID


def _glyph(mask, cell, ch):
    """Glyph cell reduced to Minecraft's 8x8 logical grid, trimmed to its
    used width the way the game trims trailing blank columns."""
    code = ord(ch)
    row, col = divmod(code, CELL_GRID)
    glyph = mask[row * cell:(row + 1) * cell, col * cell:(col + 1) * cell]
    reduced = mcfont.reduce_bitmap(glyph, max(1, cell // LOGICAL_CELL))
    used = np.flatnonzero(reduced.any(axis=0))
    width = int(used.max()) + 1 if len(used) else 2
    return reduced[:, :width]


def render(text, scale):
    """Draw `text` like the game: 1x logical bitmap + drop shadow, then
    nearest-neighbour upscale by the GUI scale. '\n' starts a new line at
    Minecraft's 9px line spacing."""
    mask, cell = _atlas()
    lines = [[_glyph(mask, cell, ch) for ch in line] for line in text.split("\n")]
    width = max(sum(g.shape[1] + 1 for g in line) for line in lines) + 2
    height = LOGICAL_CELL + 3 + 9 * (len(lines) - 1)

    canvas = np.zeros((height, width), dtype=bool)
    for row, line in enumerate(lines):
        x, y = 1, 1 + row * 9
        for g in line:
            canvas[y:y + g.shape[0], x:x + g.shape[1]] |= g
            x += g.shape[1] + 1

    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = BG
    shadow = np.zeros_like(canvas)
    shadow[1:, 1:] = canvas[:-1, :-1]
    img[shadow & ~canvas] = SHADOW
    img[canvas] = FG

    out = Image.fromarray(img)
    return out.resize((width * scale, height * scale), Image.NEAREST)


CASES = [
    ("70k", 70_000),
    ("32.5k", 32_500),
    ("27.1k", 27_100),          # the read the old OCR turned into 271000
    ("59.1k", 59_100),
    ("1.2m", 1_200_000),
    ("49.6m", 49_600_000),      # the lost-suffix guess used to call this 49.6k
    ("$1.05m", 1_050_000),
    ("1,234k", 1_234_000),
    ("999k", 999_000),
    # The capture box usually covers the whole tooltip, not just the price
    # line, and can catch several listings at once - take the cheapest.
    ("Netherite Sword\nPrice: 27.1k\nSeller: Notch", 27_100),
    ("84.2k\n79.9k\n112k", 79_900),
]


PARSE_CASES = [
    ("27.1k", 27_100),
    ("$1.2m", 1_200_000),
    ("Price: 84.2k", 84_200),
    # An unreadable digit must not become a price: matching only the tail
    # of '2?.1k' would report 1k and sell the item for nothing.
    ("2?.1k", None),
    ("27.1?", None),
    ("Flight Duration: 3", None),   # a bare number is not a price
    ("", None),
]


def main():
    failures = 0

    for text, expected in PARSE_CASES:
        got = ocr.parse_price(text)
        ok = got == expected
        failures += not ok
        print(f"parse {text!r:<22} -> {got} {'ok' if ok else f'FAIL (want {expected})'}")
    print()

    for scale in (1, 2, 3, 4):
        for text, expected in CASES:
            img = render(text, scale)
            got_text = ocr.read_region_text(img)
            got = ocr.parse_price(got_text)
            ok = got == expected
            failures += not ok
            print(f"scale={scale} {text:<8} -> {got_text!r:<12} "
                  f"{got} {'ok' if ok else f'FAIL (want {expected})'}")

    sample = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples", "15.8K.png")
    if os.path.exists(sample):
        img = Image.open(sample)
        got_text = ocr.read_region_text(img)
        got = ocr.parse_price(got_text)
        ok = got == 15_800
        failures += not ok
        print(f"\nreal capture  -> {got_text!r} {got} {'ok' if ok else 'FAIL (want 15800)'}")

    print("\nFAILURES:", failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
