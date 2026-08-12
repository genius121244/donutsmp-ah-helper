"""
slots.py
Turns the configured boxes plus the empty-slot reference images into the
answer the macro needs: which hotbar slots hold something, which order
slots still have items, and how many pickups are required.

The hotbar is the source of truth for how many items are needed - never a
counter the macro keeps itself. The user can put items in the hotbar by
hand before starting, or take some out mid-run, and a counter would then
be quietly wrong for the rest of the session.
"""

import config
import detect
import screen

SLOT_COUNT = 9


class SlotReadError(RuntimeError):
    """Raised when slot state can't be established (missing config, or a
    slot whose difference lands between the two thresholds)."""


def _thresholds(settings):
    detection = settings.get("detection", {})
    return (
        float(detection.get("empty_slot_tolerance", 12.0)),
        float(detection.get("occupied_slot_min_difference", 18.0)),
    )


def hotbar_regions(settings, item=None):
    """The nine hotbar boxes, from the individual slots or the strip."""
    return _regions(settings, item, "hotbar_slot_{}", "hotbar_strip", "hotbar")


def order_regions(settings, item=None):
    """The nine order GUI boxes, from the individual slots or the strip."""
    return _regions(settings, item,
                   ["order_slot_{}_region", "last_order_slot_{}_region", "last_orders_slot_{}_region"],
                   ["order_strip", "last_order_strip", "last_orders_strip"],
                   "order")


def _regions(settings, item, slot_keys, strip_keys, label):
    slot_keys = [slot_keys] if isinstance(slot_keys, str) else list(slot_keys)
    strip_keys = [strip_keys] if isinstance(strip_keys, str) else list(strip_keys)

    individual = []
    for key in slot_keys:
        values = [config.get_region(settings, key.format(i), item) for i in range(1, SLOT_COUNT + 1)]
        if all(values):
            return [tuple(r) for r in values]
        individual.append(values)

    for key in strip_keys:
        strip = config.get_region(settings, key, item)
        if strip:
            return detect.split_strip(tuple(strip), SLOT_COUNT)

    best_missing = []
    for values in individual:
        best_missing.extend(i for i, r in enumerate(values, 1) if not r)
    missing = sorted(set(best_missing))
    strip_hint = strip_keys[0] if strip_keys else ""
    raise SlotReadError(
        f"{label} slots are not configured (missing {missing}). Set the "
        f"'{strip_hint}' box, or all nine individual boxes, in the Pixel/OCR tab."
    )


def read_states(settings, regions, template_key):
    """[EMPTY|OCCUPIED|UNKNOWN] x9 for the given boxes."""
    path = config.get_template_path(settings, template_key)
    if not path:
        raise SlotReadError(
            f"No '{template_key}' reference image set. Capture one in the "
            f"Pixel/OCR tab (a screenshot of a single EMPTY slot)."
        )
    template = detect.load_template(path)
    empty_tol, occupied_min = _thresholds(settings)

    images = screen.grab_many(regions)
    return [
        detect.classify(image, template, empty_tol, occupied_min)[0]
        for image in images
    ]


def read_hotbar(settings, item=None):
    return read_states(settings, hotbar_regions(settings, item), "empty_hotbar_slot")


def read_order(settings, item=None):
    order_template = None
    for key in ("empty_order_slot", "empty_last_order_slot", "empty_last_orders_slot"):
        if config.get_template_path(settings, key):
            order_template = key
            break
    if order_template is None:
        order_template = "empty_order_slot"
    return read_states(settings, order_regions(settings, item), order_template)


# ----------------------------------------------------------------------
# Pure helpers - no screen access, so the state machine's arithmetic is
# testable without Minecraft running.
# ----------------------------------------------------------------------

def count(states, wanted):
    return sum(1 for state in states if state == wanted)


def empty_indexes(states):
    """0-based positions of the empty slots."""
    return [i for i, state in enumerate(states) if state == detect.EMPTY]


def occupied_slots(states):
    """1-based slot numbers that hold something."""
    return [i + 1 for i, state in enumerate(states) if state == detect.OCCUPIED]


def has_unknown(states):
    return detect.UNKNOWN in states


def pickups_needed(hotbar_states, batch_size):
    """How many items to take from the order to reach `batch_size`.

    Counts what the hotbar is missing, not what the macro thinks it took:
    with 4 slots full and a batch size of 9, that's 5 - whether those 4
    were placed by the macro or by hand.
    """
    batch_size = max(0, min(int(batch_size), SLOT_COUNT))
    occupied = count(hotbar_states, detect.OCCUPIED)
    return max(0, batch_size - occupied)


def plan_pickups(hotbar_states, order_states, batch_size):
    """(order slot numbers to take, whether the order ran short).

    Order slots are consumed strictly in order, 1 -> 9, never skipping
    ahead. If the order holds fewer items than the batch needs, take what
    is there and report the shortfall so the caller can sell a smaller
    final batch instead of waiting for a full one.
    """
    needed = pickups_needed(hotbar_states, batch_size)
    available = occupied_slots(order_states)
    take = available[:needed]
    return take, len(take) < needed
