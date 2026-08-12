"""
ocr.py
Screenshots the price-tooltip region, reads the number off it, and turns it
into a plain integer so we can do math on it (undercut by a fixed amount or
a percentage).

This no longer uses Tesseract. Minecraft draws text by blitting fixed glyph
bitmaps out of the resource pack's ascii.png and scaling them by an integer
GUI scale, so what's on screen is literally the atlas pixels, enlarged. That
makes reading it an exact dictionary lookup instead of a recognition
problem, and removes every failure mode the OCR path was fighting:

  - "27.1k" read as "271k" (the decimal is a 2x2 blob Tesseract discards as
    noise) - the dot is now just another glyph in the table
  - a lost or misread k/m suffix turning 49.6k into 49.6m (1000x error)
  - 1/7, 5/S, 0/O confusion at 8px
  - the drop shadow fattening strokes and shifting the threshold sweet spot

It's also exact rather than probabilistic, so the seven-threshold sweep, the
two page-segmentation modes, the majority vote, the decimal-recovery pass
and the decimal-drop override are all gone: a glyph either matches the
font's bitmap or it doesn't. Anything unmatched comes back as '?' and the
price is rejected, so the macro skips the cycle instead of selling at a
made-up price.

No external binary to install anymore - just pip install -r requirements.txt.
"""

import os
import re
import tempfile
import time

import numpy as np

import mcfont
import screen

# Pixels at least this bright (in every channel) count as text. Minecraft's
# drop shadow is drawn at 25% brightness, so any cutoff well above that
# separates glyph from shadow cleanly - there is no sweet spot to tune.
WHITE_CUTOFF = 170
# Fallback for coloured price text (green/gold/red), where a channel can be
# dark: accept anything bright in its brightest channel instead.
COLOUR_CUTOFF = 140

_TABLES = None
_ATLAS_PATH = None


def _tables():
    """Glyph tables from the bundled resource pack atlas, built once."""
    global _TABLES, _ATLAS_PATH
    if _TABLES is None:
        _ATLAS_PATH = mcfont.find_atlas()
        if _ATLAS_PATH is None:
            raise FileNotFoundError(
                "No font atlas found. Keep the resource pack's "
                "Font+/assets/minecraft/textures/font/ascii.png next to the "
                "macro (or drop a plain ascii.png in this folder)."
            )
        _TABLES = mcfont.build_tables(_ATLAS_PATH)
        print(f"[FONT] loaded glyph atlas {_ATLAS_PATH} "
              f"(reductions: {sorted(_TABLES)})")
    return _TABLES


def screenshot_region(region, pad=2):
    """region = (x1, y1, x2, y2). Pads a couple px on every side so a tight
    manual crop doesn't clip characters. Returns a PIL Image."""
    return screen.grab(region, pad=pad)


# --- Reading -----------------------------------------------------------


def _masks(image):
    """The candidate text masks, best-guess first."""
    arr = np.asarray(image.convert("RGB")).astype(np.int16)
    yield "white", arr.min(axis=2) >= WHITE_CUTOFF
    yield "colour", arr.max(axis=2) >= COLOUR_CUTOFF


def _detect_scale(mask):
    """The GUI scale, inferred from the narrowest horizontal run of ink.

    Every stroke in the font is a whole number of texture pixels wide, so
    once blown up by the (always integer) GUI scale, the narrowest run on
    screen is a multiple of that scale. Taking the minimum recovers it -
    and if the narrowest stroke happens to be 2 texture px, we overshoot by
    2x, which is why _read_mask also tries the halves.
    """
    runs = []
    for row in mask:
        idx = np.flatnonzero(np.diff(np.concatenate(([0], row.view(np.int8), [0]))))
        runs.extend((idx[1::2] - idx[::2]).tolist())
    return max(1, min(runs)) if runs else 1


def _split_lines(mask, min_blank_rows=1):
    """Split a region into text lines on fully blank rows."""
    rows = mask.any(axis=1)
    lines, start, blanks = [], None, 0
    for y, filled in enumerate(rows):
        if filled:
            if start is None:
                start = y
            blanks = 0
        elif start is not None:
            blanks += 1
            if blanks >= min_blank_rows:
                lines.append(mask[start:y - blanks + 1])
                start = None
    if start is not None:
        lines.append(mask[start:])
    return [line for line in lines if line.any()]


def _split_glyphs(line):
    """(bitmap, gap_before, top) per glyph, each tight-cropped in both axes.
    `top` is the glyph's distance below the top of the line, which is what
    tells a comma from an apostrophe."""
    cols = line.any(axis=0)
    glyphs, x, gap, width = [], 0, 0, line.shape[1]
    while x < width:
        if not cols[x]:
            gap += 1
            x += 1
            continue
        start = x
        while x < width and cols[x]:
            x += 1
        cell = line[:, start:x]
        rows = np.flatnonzero(cell.any(axis=1))
        glyphs.append((cell[rows.min():rows.max() + 1], gap, int(rows.min())))
        gap = 0
    return glyphs


def _decode_line(line, table):
    """Read one line of a mask already reduced to atlas resolution.

    Glyph height is measured from the top of the line, which matches the
    top of the glyph cell as long as something on the line reaches full
    height - true of any line with a digit or a capital, so always true of
    a price. For the odd line that doesn't (all lowercase, say), the whole
    line reads one or two rows too high, so we try the small shifts and
    keep whichever reads the most glyphs.
    """
    glyphs = _split_glyphs(line)
    if not glyphs:
        return "", 0
    # A space is much wider than the 1px advance between glyphs.
    height = max(g.shape[0] for g, _, _ in glyphs)
    space_gap = max(3, round(height * 0.6))

    best = ("", -1)
    for shift in range(0, 3):
        out, matched = [], 0
        for bitmap, gap, top in glyphs:
            if out and gap >= space_gap:
                out.append(" ")
            char = table.get(mcfont.key(bitmap, top + shift))
            if char is None:
                out.append("?")
            else:
                out.append(char)
                matched += 1
        if matched > best[1]:
            best = ("".join(out), matched)
    return best


def _read_mask(mask):
    """Best (text, matched_glyph_count) over every plausible scale/table."""
    if not mask.any():
        return "", 0

    detected = _detect_scale(mask)
    scales = []
    scale = detected
    while scale >= 1:
        scales.append(scale)
        if scale % 2:
            break
        scale //= 2

    # Reduction blocks have to line up with the glyph grid, and the text's
    # own origin is the only reference point we have for where that grid
    # starts - so crop to the first ink pixel before reducing.
    ys, xs = np.nonzero(mask)
    aligned = mask[ys.min():, xs.min():]

    best = ("", 0)
    for scale in scales:
        reduced = mcfont.reduce_bitmap(aligned, scale)
        if reduced is None or not reduced.any():
            continue
        for table in _tables().values():
            texts, matched = [], 0
            for line in _split_lines(reduced):
                text, hits = _decode_line(line, table)
                texts.append(text)
                matched += hits
            if matched > best[1]:
                best = ("\n".join(texts), matched)
    return best


def read_region_text(image):
    """All text in a captured region, one line per line on screen.
    Unrecognised glyphs come through as '?'."""
    best = ("", 0)
    for _name, mask in _masks(image):
        result = _read_mask(mask)
        if result[1] > best[1]:
            best = result
    return best[0]


def read_text(region):
    """Grabs the region and reads it. Kept for debugging/manual use."""
    return read_region_text(screenshot_region(region))


# --- Parsing -----------------------------------------------------------

_SUFFIX = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
# Prices are always shorthand with a k/m suffix on this server, e.g.
# '$59.1k'. '?' can never appear inside a match, so a partially unreadable
# line can't produce a price.
_PRICE_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*([kmb])\b")

MAX_SANE_PRICE = 100_000_000


def _line_prices(line):
    """Every price on one line, as ints. A price touching an unreadable
    glyph is dropped: '2?.1k' could be any of ten values, and matching just
    the readable part would report 1k."""
    line = line.lower()
    prices = []
    for match in _PRICE_RE.finditer(line):
        before = line[match.start() - 1] if match.start() else ""
        after = line[match.end()] if match.end() < len(line) else ""
        if "?" in (before, after):
            print(f"[READ] dropping {match.group(0)!r} - unreadable glyph next to it")
            continue
        number, suffix = match.groups()
        try:
            value = float(number.replace(",", "")) * _SUFFIX[suffix]
        except ValueError:
            continue
        if 0 < value <= MAX_SANE_PRICE:
            prices.append(int(value))
    return prices


def parse_price(text):
    """
    Turns read text like '32.5k', '$1.2m', '70k' into a plain int.
    Returns None if nothing usable was found - the macro then skips the
    cycle rather than selling at a made-up price.
    """
    prices = []
    for line in text.splitlines():
        prices.extend(_line_prices(line))
    if not prices:
        return None
    # Several prices in one tooltip means the region covers more than the
    # price line; the listing we care about is the cheapest.
    return min(prices)


# Balances are written in full ('$12,345,678'), not shorthand, so they need
# their own pattern - parse_price deliberately refuses a bare number, since
# a price missing its k would be a 1000x mistake.
_MONEY_RE = re.compile(r"(?<![\d.])\$?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([kmb])?")

MAX_SANE_MONEY = 1_000_000_000_000


def parse_money(text):
    """Reads a balance off already-read text. Returns an int, or None.

    Takes the largest number on the line rather than the smallest: the
    money box can catch a nearby '+1.2k' change indicator, and the balance
    is the bigger of the two.
    """
    values = []
    for line in text.splitlines():
        line = line.lower()
        for match in _MONEY_RE.finditer(line):
            before = line[match.start() - 1] if match.start() else ""
            after = line[match.end()] if match.end() < len(line) else ""
            if "?" in (before, after):
                continue
            number, suffix = match.groups()
            try:
                value = float(number.replace(",", "")) * _SUFFIX.get(suffix or "", 1)
            except ValueError:
                continue
            if 0 < value <= MAX_SANE_MONEY:
                values.append(int(value))
    return max(values) if values else None


def get_money(region):
    """Full pipeline for the balance box. Returns int or None."""
    image = screenshot_region(region)
    text = read_region_text(image)
    money = parse_money(text)
    if money is None:
        _save_debug_snapshot(image, "nomoney")
    return money


def format_price(value):
    """Turns an int back into a short string like '31k' or '1.2m' for typing into chat."""
    if value >= 1_000_000:
        formatted = value / 1_000_000
        return f"{formatted:.2f}".rstrip("0").rstrip(".") + "m"
    if value >= 1_000:
        formatted = value / 1_000
        return f"{formatted:.2f}".rstrip("0").rstrip(".") + "k"
    return str(value)


# --- Debug snapshots ---------------------------------------------------
# Every get_lowest_price() call saves the exact region it captured into this
# folder, named with the outcome, so you can scroll through and see at a
# glance whether a read looks right - and, when it's wrong or empty, whether
# the region is even pointed at the price.

_DEBUG_MAX_FILES = 200


def _debug_dir():
    base = os.environ.get("APPDATA") or tempfile.gettempdir()
    path = os.path.join(base, "DonutAHMacro", "ocr_debug")
    os.makedirs(path, exist_ok=True)
    return path


def _save_debug_snapshot(image, status):
    """Saves `image` as ocr_debug/<timestamp>_<status>.png. Never raises -
    a debug save failing shouldn't stop the macro from selling."""
    try:
        debug_dir = _debug_dir()
        timestamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int((time.time() % 1) * 1000):03d}"
        safe_status = re.sub(r"[^a-zA-Z0-9_-]", "", status) or "unknown"
        filename = f"{timestamp}_{safe_status}.png"
        image.save(os.path.join(debug_dir, filename))
        print(f"[READ DEBUG IMAGE] {os.path.join(debug_dir, filename)}")

        pngs = sorted(f for f in os.listdir(debug_dir) if f.lower().endswith(".png"))
        if len(pngs) > _DEBUG_MAX_FILES:
            for old in pngs[: len(pngs) - _DEBUG_MAX_FILES]:
                try:
                    os.remove(os.path.join(debug_dir, old))
                except OSError:
                    pass
    except OSError as e:
        print(f"[READ DEBUG SAVE FAILED] {e}")


def get_lowest_price(region):
    """Full pipeline: screenshot -> glyph match -> parse. Returns int or None."""
    image = screenshot_region(region)
    text = read_region_text(image)
    print(f"[READ TEXT] {text!r}")

    price = parse_price(text)
    if price is None:
        print("[READ] no trustworthy price in this capture")
        _save_debug_snapshot(image, "noprice")
        return None

    print(f"[READ FINAL] price={price}")
    _save_debug_snapshot(image, f"price-{price}")
    return price
