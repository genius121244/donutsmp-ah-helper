"""
mcfont.py
Reads Minecraft's bitmap font straight off the resource pack's ascii.png
atlas and turns it into a lookup table of exact glyph bitmaps.

Why this exists instead of Tesseract: the game draws text by blitting fixed
glyph bitmaps from this very atlas and scaling them by an integer GUI scale.
So the pixels on screen are the atlas pixels, just bigger. Recognising them
is a dictionary lookup, not a machine-learning problem — which is why the
old OCR path needed seven thresholds, two page-segmentation modes, a
majority vote and a hand-written decimal-recovery pass and still got
"27.1k" wrong as "271k".

The atlas is a 16x16 grid of glyph cells, indexed by codepage-437 byte, so
cell (code // 16, code % 16) holds character `chr(code)`. Vanilla ships a
128x128 atlas (8x8 cells); high-res packs like Font+ ship 256x256 (16x16
cells) or larger. Either works: what matters is the glyph's *shape*, so we
build a table per power-of-two reduction of the cell and let the reader pick
whichever one the on-screen text actually matches.
"""

import os

import numpy as np
from PIL import Image

# Searched in order, first hit wins. The pack folder comes first so the
# user's own font is preferred over any vanilla atlas lying around.
FONT_SEARCH_PATHS = (
    os.path.join("Font+", "assets", "minecraft", "textures", "font", "ascii.png"),
    os.path.join("assets", "minecraft", "textures", "font", "ascii.png"),
    "ascii.png",
)

# Printable ASCII, not just digits and suffixes: the capture box normally
# covers the whole tooltip, so the item name and seller have to be readable
# too, otherwise they come out as '?' next to the price. Lookalikes ('O' vs
# '0', 'l' vs '1') aren't a risk here the way they are for OCR - their
# bitmaps genuinely differ, so they cannot be confused.
CHARSET = "".join(chr(c) for c in range(0x21, 0x7F))

_GRID = 16


def _rank(ch):
    """Tie-break order for identical glyphs: digits, then letters, then the
    rest."""
    if ch.isdigit():
        return 0
    if ch.isalpha():
        return 1
    return 2


def find_atlas(base_dir=None):
    """Absolute path of the font atlas, or None if no atlas is bundled."""
    base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
    for rel in FONT_SEARCH_PATHS:
        path = os.path.join(base_dir, rel)
        if os.path.exists(path):
            return path
    return None


def _atlas_mask(path):
    """Boolean array of the atlas: True where a glyph has ink."""
    img = Image.open(path).convert("RGBA")
    arr = np.asarray(img)
    # Glyph pixels are opaque white; the rest of the cell is transparent.
    # Some packs use a black-but-opaque background, so require brightness too.
    return (arr[:, :, 3] > 128) & (arr[:, :, :3].max(axis=2) > 64)


def _tight(bitmap):
    """(trimmed bitmap, rows of blank space above it), or None if blank."""
    rows = np.nonzero(bitmap.any(axis=1))[0]
    cols = np.nonzero(bitmap.any(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    return bitmap[rows.min():rows.max() + 1, cols.min():cols.max() + 1], int(rows.min())


def reduce_bitmap(bitmap, factor):
    """Downscale a boolean bitmap by an integer factor (majority per block)."""
    if factor == 1:
        return bitmap
    h = (bitmap.shape[0] // factor) * factor
    w = (bitmap.shape[1] // factor) * factor
    if h == 0 or w == 0:
        return None
    block = bitmap[:h, :w].reshape(h // factor, factor, w // factor, factor)
    return block.mean(axis=(1, 3)) > 0.5


def key(bitmap, top):
    """Hashable form of a glyph: its bitmap plus how far below the top of
    the line it sits, e.g. "6@##|##" for a period.

    Height matters because several glyphs are the same shape at different
    heights - a comma is an apostrophe pushed to the baseline, a period is
    the bottom half of a colon. Keying on shape alone makes them collide
    and both get dropped, and losing ',' would break prices like 1,234k.
    """
    shape = "|".join("".join("#" if v else "." for v in row) for row in bitmap)
    return f"{top}@{shape}"


def build_tables(atlas_path, charset=CHARSET):
    """
    {reduction_factor: {glyph_key: character}} for every power-of-two
    reduction of the atlas cell.

    A pack whose cells are 16px (Font+) renders at 8 logical px in game, so
    on screen its glyphs are the cell reduced by 2 and then multiplied by
    the GUI scale. Rather than hard-coding that relationship (which changes
    with pack resolution and Minecraft version), we build every reduction
    and let read time pick the one that matches.
    """
    mask = _atlas_mask(atlas_path)
    cell = mask.shape[0] // _GRID

    tables = {}
    factor = 1
    while factor <= cell // 4:
        table = {}
        for ch in charset:
            code = ord(ch)
            row, col = divmod(code, _GRID)
            glyph = mask[row * cell:(row + 1) * cell, col * cell:(col + 1) * cell]
            small = reduce_bitmap(glyph, factor)
            if small is None:
                continue
            tight = _tight(small)
            if tight is None:
                continue
            # A collision means two characters are drawn with the exact same
            # pixels, so no reader could tell them apart either - resolve it
            # to whichever is likelier in a tooltip (in Font+ this is only
            # 'l' vs '|'). Prices never hinge on such a pair; if one ever
            # did, it would still be a legible digit, not a wrong number.
            k = key(*tight)
            if _rank(ch) < _rank(table.get(k, ch)):
                table[k] = ch
            else:
                table.setdefault(k, ch)
        tables[factor] = table
        factor *= 2
    return tables
