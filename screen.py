"""
screen.py
The only place the screen is captured.

Everything else asks for a region, so grabbing can be optimised (and
mocked in tests) in one spot. mss opens a display connection per call,
which is slow when the state machine checks nine hotbar slots after every
single pickup, so the connection is kept alive and reused.
"""

import threading

import mss
from PIL import Image, ImageGrab

_local = threading.local()

# mss is the fast path but needs a display it can talk to; where it can't
# (some Linux setups) Pillow still works, and a slower screenshot beats no
# screenshot at all.
_use_mss = True


def _sct():
    """One mss instance per thread - they are not thread-safe to share."""
    if getattr(_local, "sct", None) is None:
        _local.sct = mss.mss()
    return _local.sct


def grab(region, pad=0):
    """Screenshot (x1, y1, x2, y2) as a PIL Image."""
    global _use_mss
    x1, y1, x2, y2 = region
    if pad:
        x1, y1, x2, y2 = x1 - pad, y1 - pad, x2 + pad, y2 + pad
    width, height = max(1, x2 - x1), max(1, y2 - y1)

    if _use_mss:
        try:
            shot = _sct().grab({"left": x1, "top": y1,
                                "width": width, "height": height})
            return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        except Exception:
            _use_mss = False
            _local.sct = None

    return ImageGrab.grab(bbox=(x1, y1, x1 + width, y1 + height)).convert("RGB")


def grab_many(regions, pad=0):
    """Screenshot several boxes at once.

    The nine hotbar slots sit in one strip, so a single grab of their
    bounding box and nine crops is one screen read instead of nine - which
    is what keeps per-pickup verification cheap enough to run every time.
    """
    regions = list(regions)
    if not regions:
        return []
    if len(regions) == 1:
        return [grab(regions[0], pad=pad)]

    left = min(r[0] for r in regions) - pad
    top = min(r[1] for r in regions) - pad
    right = max(r[2] for r in regions) + pad
    bottom = max(r[3] for r in regions) + pad

    combined = grab((left, top, right, bottom))
    return [
        combined.crop((r[0] - pad - left, r[1] - pad - top,
                       r[2] + pad - left, r[3] + pad - top))
        for r in regions
    ]


def screen_size():
    if _use_mss:
        try:
            monitor = _sct().monitors[0]
            return monitor["width"], monitor["height"]
        except Exception:
            pass
    return ImageGrab.grab().size


def grab_screen():
    """The whole desktop, used for the preview in the Pixel/OCR tab."""
    if _use_mss:
        try:
            monitor = _sct().monitors[0]
            return grab((monitor["left"], monitor["top"],
                         monitor["left"] + monitor["width"],
                         monitor["top"] + monitor["height"]))
        except Exception:
            pass
    return ImageGrab.grab().convert("RGB")
