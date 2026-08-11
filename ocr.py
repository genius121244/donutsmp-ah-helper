"""
ocr.py
Screenshots the price-tooltip region, reads the number off it with
Tesseract, and turns it into a plain integer so we can do math on it
(undercut by a fixed amount or a percentage).

Requires the actual Tesseract binary installed separately from pip,
not just the pytesseract wrapper:
  Windows installer: https://github.com/UB-Mannheim/tesseract/wiki
After installing, if it's not on PATH, set the path manually, e.g.:
  pytesseract.pytesseract.tesseract_cmd = "C:/Program Files/Tesseract-OCR/tesseract.exe"
"""

import os
import re
import tempfile
import time
import mss
import numpy as np
from scipy import ndimage
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract

# Auto-point pytesseract at the default Windows install location if it's
# there and not already on PATH. If you installed it somewhere else,
# change this path to match.
_DEFAULT_WIN_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.name == "nt" and os.path.exists(_DEFAULT_WIN_PATH):
    pytesseract.pytesseract.tesseract_cmd = _DEFAULT_WIN_PATH


def screenshot_region(region, pad=2):
    """region = (x1, y1, x2, y2). Pads a couple px on every side so a tight
    manual crop doesn't clip characters. Kept small on purpose: on a crop
    this tiny (tens of px), a bigger pad pulls in enough background/border
    to skew autocontrast and threshold cutoffs across the whole image,
    which made things worse in testing, not better. Returns a PIL Image."""
    x1, y1, x2, y2 = region
    x1, y1, x2, y2 = x1 - pad, y1 - pad, x2 + pad, y2 + pad
    with mss.mss() as sct:
        monitor = {"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1}
        shot = sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def _enhanced_gray(image, threshold=120):
    gray = image.convert("L")
    gray = ImageOps.autocontrast(gray)
    gray = gray.filter(ImageFilter.SHARPEN)
    gray = gray.point(lambda x: 0 if x < threshold else 255, "L")
    return gray


def _ocr_image(image, psm=6):
    return pytesseract.image_to_string(
        image,
        config=f"--psm {psm} -c tessedit_char_whitelist=0123456789kmKM.$"
    )


def _recover_lost_decimal(gray_image, text):
    """Tesseract's recognition step silently drops the decimal point on
    this font: it's a tiny 24x24 blob against ~120-wide digit strokes,
    small enough that the LSTM step discards it as noise before it ever
    becomes a character candidate - confirmed by checking image_to_boxes,
    which has zero record of it either, even though the pixels are
    unmistakably a dot in the actual image (verified against real capture
    screenshots). Trusting Tesseract's own box edges to find the gap
    doesn't work either: its boxes include sloppy padding that can
    swallow the dot's pixels into the *next* character's reported box.
    So this looks at the pixels directly: connected-component blobs,
    filtered to the digit-height band (excludes unrelated tooltip text
    above/below), projected onto columns to merge each digit's multiple
    sub-strokes into one contiguous run per character. A run that's much
    narrower than the others AND sits low against the baseline (rather
    than spanning the full digit height) is the decimal point. Its
    left-to-right rank among the other runs gives the exact digit
    position to insert '.' at.

    Returns text unchanged if there's already a '.', no digits, or if
    anything about the run count doesn't line up cleanly with the
    recognized characters - this only fires when it can double-check
    itself, it never forces an insertion."""
    if "." in text or not re.search(r"\d", text):
        return text

    arr = np.array(gray_image) > 127
    labeled, _n = ndimage.label(arr)
    objs = ndimage.find_objects(labeled)
    blobs = [(sl[1].start, sl[0].start, sl[1].stop, sl[0].stop) for sl in objs if sl]
    if not blobs:
        return text

    heights = [(y1 - y0) for x0, y0, x1, y1 in blobs]
    max_h = max(heights)
    tall = [b for b, h in zip(blobs, heights) if h >= max_h * 0.6]
    if not tall:
        return text
    y0_band = min(b[1] for b in tall)
    y1_band = max(b[3] for b in tall)
    band_h = y1_band - y0_band
    if band_h <= 0:
        return text

    col_occupied = arr[y0_band:y1_band, :].any(axis=0)
    runs = []
    in_run = False
    start = 0
    for x, occ in enumerate(col_occupied):
        if occ and not in_run:
            start = x
            in_run = True
        elif not occ and in_run:
            runs.append((start, x))
            in_run = False
    if in_run:
        runs.append((start, len(col_occupied)))

    runs = [r for r in runs if r[1] - r[0] >= 8]  # drop noise specks
    if len(runs) < 2:
        return text

    widths = [r[1] - r[0] for r in runs]
    avg_w = sum(widths) / len(widths)

    dot_run = None
    for r in runs:
        w = r[1] - r[0]
        sub = arr[y0_band:y1_band, r[0]:r[1]]
        rows = np.where(sub.any(axis=1))[0]
        if len(rows) == 0:
            continue
        top = rows.min()
        if w < avg_w * 0.5 and top > band_h * 0.5:
            dot_run = r
            break
    if dot_run is None:
        return text

    other_runs = [r for r in runs if r != dot_run]
    digit_match = re.search(r"\d+", text)
    if not digit_match:
        return text
    digits = digit_match.group(0)

    recognized_chars = re.sub(r"[^0-9a-z]", "", text)
    if len(other_runs) != len(recognized_chars):
        # Run count doesn't line up with what Tesseract recognized -
        # something's off, don't guess where the dot goes.
        return text

    count_left = sum(1 for r in other_runs if r[1] <= dot_run[0])
    if count_left <= 0 or count_left >= len(digits):
        return text

    new_digits = digits[:count_left] + "." + digits[count_left:]
    result = text[:digit_match.start()] + new_digits + text[digit_match.end():]
    print(f"[OCR DECIMAL RECOVERY] {text!r} -> {result!r}")
    return result


# Thresholds tried for binarizing each preprocessed variant. A single fixed
# cutoff can flatten antialiasing on small blocky game fonts just enough to
# turn one digit into a visually similar one (2/3, 5/6, 8/9 are the usual
# offenders). Trying several cutoffs gives independent "opinions" instead of
# one potentially-wrong reading.
#
# NOTE: the previous version of this also tried a green-color-mask variant
# and a "bottom half only" crop, on the theory the whole price (incl. the
# 'K'/'M' suffix) was green and might be sitting low in the region. Checked
# both against real captures and both were actively wrong: the price digits
# render white/light, not green - only the '$' icon is green, so the mask
# variants were OCRing a dollar-sign silhouette every single time (which
# Tesseract tends to misread as '3'). And the bottom-45%-only crop was
# slicing straight through the vertical middle of the digits, keeping only
# their bottom halves. Both were guaranteed-bad attempts diluting the vote
# alongside the ones that actually worked, so they've been removed rather
# than kept "just in case" - a wider spread of thresholds on the full,
# uncropped grayscale image is what actually reads correctly.
_THRESHOLDS = (80, 100, 110, 120, 130, 140, 160)


def _build_attempts(image):
    """Builds the full list of (label, preprocessed_image, psm) OCR attempts
    for a screenshot: full-image grayscale at several thresholds, each tried
    with two page-segmentation modes since PSM 6 (uniform block) and PSM 7
    (single line) occasionally disagree on tight single-line captures."""
    attempts = []
    for threshold in _THRESHOLDS:
        gray = _enhanced_gray(image, threshold=threshold)
        attempts.append((f"gray_t{threshold}_psm6", gray, 6))
        attempts.append((f"gray_t{threshold}_psm7", gray, 7))
    return attempts


def _run_attempts(image):
    """OCRs every preprocessing variant of an already-captured region image,
    returning a list of (label, cleaned_text, score) for every attempt that
    produced something."""
    # Upscaled 6x rather than 4x - thin diagonal strokes (like the 'k'/'m'
    # suffix) survive a bigger blow-up noticeably better on small blocky
    # game fonts, where they were previously blurring away to nothing.
    image = image.resize((image.width * 6, image.height * 6), Image.LANCZOS)

    attempts = _build_attempts(image)
    results = []

    for label, img, psm in attempts:
        if img.getbbox() is None:
            print(f"[OCR SKIP] {label} is empty")
            continue

        # TEMP DEBUG: dump exactly what Tesseract is fed for each variant.
        # We've made two blind guesses in a row (upscale factor, region
        # padding) and the second one made things worse - so before
        # changing anything else, look in ocr_debug/preproc_* and check:
        # is the K/M suffix actually visible as a distinct shape in these
        # images? If yes, it's a Tesseract config problem. If no (it's
        # smeared into the digit or into the background), it's a
        # preprocessing/threshold problem. Remove this block once you've
        # looked.
        try:
            img.save(os.path.join(_debug_dir(), f"preproc_{label}.png"))
        except OSError:
            pass

        text = _ocr_image(img, psm=psm)
        text = text.lower()
        text = _recover_lost_decimal(img, text)
        text = text.replace("kk", "k").replace("mm", "m").replace("km", "k")
        text = re.sub(r"[^0-9a-z\.\s,]", " ", text)
        text = text.strip()
        print(f"[OCR RAW TEXT {label.upper()}] {text!r}")

        score = len(re.findall(r"[0-9]", text)) + (10 if re.search(r"[km]", text) else 0)
        results.append((label, text, score))

    return results


def read_text(region):
    """Grabs the region and OCRs it, returning the single best-scoring raw
    text. Kept for debugging/manual use; get_lowest_price() no longer relies
    on this since a single reading can misread a digit."""
    image = screenshot_region(region)
    results = _run_attempts(image)
    if not results:
        return ""
    label, text, score = max(results, key=lambda r: r[2])
    return text


# --- Debug snapshots ---------------------------------------------------
# Every get_lowest_price() call saves the exact region it captured into this
# folder, named with the outcome, so you can scroll through and see at a
# glance whether a read looks right - and, when it's wrong or empty, whether
# the region is even pointed at the price (rather than digging through
# console logs). Old snapshots are pruned so this doesn't grow forever.

_DEBUG_MAX_FILES = 200


def _debug_dir():
    base = os.environ.get("APPDATA") or tempfile.gettempdir()
    path = os.path.join(base, "DonutAHMacro", "ocr_debug")
    os.makedirs(path, exist_ok=True)
    return path


def _save_debug_snapshot(image, status):
    """Saves `image` (the raw captured region) as
    ocr_debug/<timestamp>_<status>.png, e.g. '..._price-67000.png' or
    '..._noprice.png'. Never raises - a debug save failing shouldn't stop
    the macro from selling."""
    try:
        debug_dir = _debug_dir()
        timestamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int((time.time() % 1) * 1000):03d}"
        safe_status = re.sub(r"[^a-zA-Z0-9_-]", "", status) or "unknown"
        filename = f"{timestamp}_{safe_status}.png"
        image.save(os.path.join(debug_dir, filename))
        print(f"[OCR DEBUG IMAGE] {os.path.join(debug_dir, filename)}")

        pngs = sorted(f for f in os.listdir(debug_dir) if f.lower().endswith(".png"))
        if len(pngs) > _DEBUG_MAX_FILES:
            for old in pngs[: len(pngs) - _DEBUG_MAX_FILES]:
                try:
                    os.remove(os.path.join(debug_dir, old))
                except OSError:
                    pass
    except OSError as e:
        print(f"[OCR DEBUG SAVE FAILED] {e}")


def _parse_price_impl(text):
    """
    Core parser. Returns (price_int, confidence) or (None, 0).

    confidence reflects how directly the match came from a clean 'number+k/m'
    on a single line (line_score, which rewards a line that's *just* the
    price and nothing else) versus a lower-trust heuristic reconstruction
    where the digits and suffix were found separately and stitched together,
    or a suffix-lost guess (see below). A clean line match is much more
    likely to actually be the price line rather than another line of the
    tooltip (item name, flight duration, etc.) that happened to contain a
    number.
    """
    text = text.lower().replace("$", "").strip()
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    print(f"[OCR NORMALIZED TEXT] {text!r}")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidates = []

    def line_score(line):
        score = 0
        if re.search(r"[km]", line):
            score += 10
        if re.fullmatch(r"[0-9\.,\s]*[km]", line):
            score += 20
        if re.search(r"[a-zA-Z]{2,}", line):
            score -= 5
        score += len(re.findall(r"\d", line))
        # A decimal point that survived OCR is strong positive evidence:
        # Tesseract silently DROPPING a decimal (27.1k -> 271k) is a known,
        # common failure mode on this font (see _recover_lost_decimal), but
        # a decimal being falsely INSERTED where there wasn't one is not
        # something this font's OCR tends to do. So when two readings of
        # the same tooltip disagree only on whether a '.' is present, the
        # one that has it is almost always the correct one, and should win
        # the vote instead of tying with (and sometimes losing to) the
        # decimal-dropped misread.
        if "." in line:
            score += 8
        return score

    def parse_line(line):
        match = re.search(r"([0-9]+(?:[\.,][0-9]+)*(?:\s+[0-9]+(?:[\.,][0-9]+)*)*)\s*(k|m)\b", line)
        if not match:
            return None

        raw_num_str = match.group(1)
        num_str = re.sub(r"[\s,]", "", raw_num_str).replace(",", ".")
        try:
            number = float(num_str)
        except ValueError:
            return None

        suffix = match.group(2)
        had_decimal = "." in raw_num_str
        return number, suffix, line, had_decimal

    for line in lines:
        parsed = parse_line(line)
        if parsed:
            number, suffix, match_line, had_decimal = parsed
            candidates.append((line_score(line), number, suffix, match_line, had_decimal))

    confidence = 0
    decimal_present = False
    if candidates:
        candidates.sort(key=lambda item: (item[0], len(item[3])), reverse=True)
        score, number, suffix, match_line, decimal_present = candidates[0]
        confidence = score
        print(f"[OCR LINE MATCH] {match_line!r} -> number={number}, suffix={suffix}, score={score}")
    else:
        numbers = re.findall(r"[0-9]+(?:[\.,][0-9]+)?", text)
        suffixes = re.findall(r"[km]", text)
        if not numbers:
            return None, 0, False

        if suffixes:
            number = float(numbers[-1].replace(",", "."))
            suffix = suffixes[-1]
            decimal_present = "." in numbers[-1]
            # Low, fixed confidence: digits and suffix were found separately
            # in the text rather than matched together on one clean line, so
            # this is a reconstruction, not a direct read.
            confidence = 3
            print(f"[OCR HEURISTIC] number={number}, suffix={suffix}, extracted_numbers={numbers}, extracted_suffixes={suffixes}")
        else:
            # No k/m suffix found anywhere in this reading. Every genuine
            # price on this server has one, so on its own a bare number is
            # more likely stray text (e.g. "Flight Duration: 3") than a
            # price with a lost suffix - EXCEPT when the number itself has
            # a decimal point. This server never shows a plain decimal
            # price outside k/m shorthand (there's no fractional currency),
            # so something like "49.6" with no suffix anywhere is almost
            # certainly a lost/unrecognized 'k' or 'm', not a coincidence.
            #
            # We can't tell k from m once the suffix itself is gone, so we
            # default to 'k' (by far the more common case) and mark this
            # as a low-confidence guess. NOTE: if your items can plausibly
            # sell in the millions, this guess can be wrong by a factor of
            # 1000 (e.g. a lost 49.6m read as 49.6k). If that's a real risk
            # for you, don't rely on this fallback alone - tell me and I'll
            # add a value-range sanity check or an OCR pass that isolates
            # just the suffix character instead of guessing.
            decimal_numbers = [n for n in numbers if "." in n]
            if decimal_numbers:
                number = float(decimal_numbers[-1].replace(",", "."))
                suffix = "k"
                confidence = 1
                decimal_present = True  # this branch only fires when a decimal was found
                print(f"[OCR HEURISTIC - LOST SUFFIX] number={number}, assuming 'k' (no suffix found, decimal present, numbers={numbers})")
            else:
                print(f"[OCR HEURISTIC SKIP] no k/m suffix found anywhere, refusing to guess (numbers={numbers})")
                return None, 0, False

    if suffix == "k":
        number *= 1_000
    elif suffix == "m":
        number *= 1_000_000

    # Safety clamp for obviously bad OCR results.
    if number > 100_000_000:
        print(f"[OCR SAFETY] parsed value {number} exceeds 100m, rejecting as invalid.")
        return None, 0, False

    return int(number), confidence, decimal_present


def parse_price(text):
    """
    Turns OCR text like '32.5k', '1.2m', '$32k', '70k' into a plain int.
    Returns None if nothing usable was found.

    IMPORTANT: on this server, every listed price is shown as shorthand
    with a k/m suffix (e.g. 70k, 59.1k). The parser is more tolerant of
    OCR noise where the suffix and digits may be split across multiple
    lines or partially recognized, and will guess a lost 'k' suffix when
    a decimal number is found with no suffix anywhere (see
    _parse_price_impl), but otherwise refuses to invent a suffix out of
    thin air.
    """
    price, _confidence, _decimal_present = _parse_price_impl(text)
    return price


def format_price(value):
    """Turns an int back into a short string like '31k' or '1.2m' for typing into chat."""
    if value >= 1_000_000:
        formatted = value / 1_000_000
        return f"{formatted:.2f}".rstrip("0").rstrip(".") + "m"
    if value >= 1_000:
        formatted = value / 1_000
        return f"{formatted:.2f}".rstrip("0").rstrip(".") + "k"
    return str(value)


def get_lowest_price(region):
    """Full pipeline: screenshot -> OCR (several preprocessing variants) ->
    parse each independently -> majority vote. Returns int or None.

    A single OCR pass can misread one digit for a similar-looking one (e.g.
    2 read as 3) under Minecraft's small blocky font, which silently produces
    a wrong price. Since each variant is thresholded/cropped independently,
    a one-off misread on one variant usually isn't repeated by the others,
    so voting on the parsed *numbers* (not just picking the "best" raw text)
    is much more reliable than trusting a single reading.

    Votes are weighted by parse confidence (a clean single-line 'number+k/m'
    match counts far more than a heuristic reconstruction or a lost-suffix
    guess), not by raw OCR digit count. This matters when the capture region
    includes other lines of the tooltip (item name, flight duration, etc.)
    alongside the price - those extra lines can produce several noisy
    low-confidence reconstructions that would otherwise outvote the one
    attempt that read the price cleanly.

    Every call saves a snapshot of exactly what it captured to the
    ocr_debug/ folder (see _debug_dir()), named with the outcome, so you can
    check whether the region is actually pointed at the price.
    """
    raw_image = screenshot_region(region)
    results = _run_attempts(raw_image)

    votes = {}
    for label, text, _raw_score in results:
        price, confidence, decimal_present = _parse_price_impl(text)
        if price is None or confidence <= 0:
            continue
        entry = votes.setdefault(price, {"count": 0, "confidence": 0, "labels": [], "has_decimal": False})
        entry["count"] += 1
        entry["confidence"] += confidence
        entry["labels"].append(label)
        if decimal_present:
            entry["has_decimal"] = True

    if not votes:
        print("[OCR VOTE] no attempt produced a parseable price")
        _save_debug_snapshot(raw_image, "noprice")
        return None

    print(f"[OCR VOTE] {votes}")
    best_price = max(votes.items(), key=lambda kv: (kv[1]["confidence"], kv[1]["count"]))[0]

    # DECIMAL-DROP OVERRIDE: a decimal point is a tiny blob that's easy for
    # Tesseract to lose at most thresholds but easy to keep at a few — so
    # a decimal-dropped misread (e.g. 271k) can out-vote the one or two
    # variants that correctly kept it (27.1k) on sheer count alone, even
    # though "kept the decimal" is much stronger evidence of being correct
    # than "how many thresholds happened to agree." So: if the winning
    # price has ZERO readings with a genuine decimal anywhere, but exactly
    # value/10 (or value/100) DOES have decimal-confirmed readings, trust
    # the decimal evidence over the raw vote count and switch to it.
    if not votes[best_price]["has_decimal"]:
        for factor in (10, 100):
            if best_price % factor == 0:
                candidate = best_price // factor
                if candidate in votes and votes[candidate]["has_decimal"]:
                    print(f"[OCR OVERRIDE] {best_price} never had a confirmed decimal reading, but "
                          f"{candidate} (={best_price}/{factor}) does -> switching to {candidate} "
                          f"as the trustworthy decimal-preserved reading.")
                    best_price = candidate
                    break

    print(f"[OCR FINAL] chosen price={best_price}")
    _save_debug_snapshot(raw_image, f"price-{best_price}")
    return best_price
