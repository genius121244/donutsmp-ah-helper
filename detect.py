"""
detect.py
Decides whether an inventory slot is empty or occupied by comparing it to
a reference screenshot of an empty slot.

Why not read the stack count: those digits are 6px tall, often overlap the
item sprite, and are absent entirely for a single item. Comparing the slot
to a picture of an empty slot needs no text at all, and the question the
macro actually asks is only ever "is there something in here".

The comparison is tolerant, not exact. Minecraft's slot background is a
translucent grey drawn over whatever is behind the GUI, so the same empty
slot differs by a few units between screenshots; and if the box is a pixel
or two off the slot it will clip a border. Mean absolute difference over
the box handles both, while an item sprite - which changes hundreds of
pixels by a lot - lands far outside the tolerance.

A slot whose difference falls between the two thresholds is UNKNOWN, not a
guess: the state machine stops rather than shift-clicking blind.
"""

import numpy as np
from PIL import Image

EMPTY = "empty"
OCCUPIED = "occupied"
UNKNOWN = "unknown"


def load_template(path):
    """Reference screenshot as an RGB PIL Image."""
    return Image.open(path).convert("RGB")


def difference(slot_image, template):
    """Mean absolute per-channel difference (0-255) between a slot and the
    reference. The template is resized to the slot so a reference captured
    at a different GUI scale still works."""
    slot = slot_image.convert("RGB")
    if template.size != slot.size:
        # NEAREST, not a smoothing filter: Minecraft's GUI is pixel art
        # scaled by whole numbers, so smoothing would invent edge colours
        # that aren't on screen and inflate the difference.
        template = template.resize(slot.size, Image.NEAREST)
    a = np.asarray(slot, dtype=np.int16)
    b = np.asarray(template, dtype=np.int16)
    return float(np.abs(a - b).mean())


def classify(slot_image, template, empty_tolerance=12.0, occupied_min_difference=18.0):
    """EMPTY / OCCUPIED / UNKNOWN for one slot, plus the raw difference."""
    diff = difference(slot_image, template)
    if diff <= empty_tolerance:
        return EMPTY, diff
    if diff >= occupied_min_difference:
        return OCCUPIED, diff
    return UNKNOWN, diff


def classify_all(slot_images, template, empty_tolerance=12.0, occupied_min_difference=18.0):
    """[(state, difference), ...] for a list of slot images."""
    return [
        classify(image, template, empty_tolerance, occupied_min_difference)
        for image in slot_images
    ]


def split_strip(region, count=9):
    """Split one wide box into `count` equal boxes, left to right.

    Lets the user drag a single box around the whole hotbar instead of
    setting nine of them; the slots are evenly spaced, so this is exact
    apart from rounding.
    """
    x1, y1, x2, y2 = region
    width = (x2 - x1) / count
    return [
        (int(round(x1 + i * width)), y1, int(round(x1 + (i + 1) * width)), y2)
        for i in range(count)
    ]
