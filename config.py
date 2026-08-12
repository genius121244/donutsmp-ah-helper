"""
config.py
Loads/saves every persistent setting to a single JSON file, and defines
the shape of that file.

IMPORTANT: this is stored in %APPDATA% (a stable per-user Windows folder),
NOT next to the script. That's on purpose - if it lived next to the
script, every time you download an updated version and extract it to a
new/different folder, your saved pixel locations would be lost and you'd
have to redo them. Storing it in %APPDATA% means updates never touch it.

Settings are one nested dict with a `version` field. `load_settings()`
migrates older files forward (see `_migrate`), so upgrading never loses
the coordinates you spent time setting.

Layout
------
points        single (x, y) click targets, shared by every item
regions       (x1, y1, x2, y2) boxes: hotbar/order slots, OCR areas
hover_points  where to park the mouse before an OCR read (see ocr_hover)
templates     file paths of reference screenshots (empty slot images)
items         per-item flip configuration; the active one drives the macro
keybinds      action -> key/mouse binding
webhook       Discord URL, per-event toggles, summary interval
detection     match tolerances
timing        every delay the macro uses, in milliseconds
general       retry limits and fail-safe behaviour
"""

import copy
import json
import os
import shutil
import zipfile

_APP_DIR_NAME = "DonutAHMacro"

if os.name == "nt" and os.environ.get("APPDATA"):
    _CONFIG_DIR = os.path.join(os.environ["APPDATA"], _APP_DIR_NAME)
else:
    # Non-Windows fallback (e.g. testing on Mac/Linux): use home folder instead
    _CONFIG_DIR = os.path.join(os.path.expanduser("~"), f".{_APP_DIR_NAME}")

os.makedirs(_CONFIG_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(_CONFIG_DIR, "settings.json")
TEMPLATE_DIR = os.path.join(_CONFIG_DIR, "templates")

SETTINGS_VERSION = 2

# ----------------------------------------------------------------------
# What the user can configure, described once so the UI can build itself.
# ----------------------------------------------------------------------

# Single click targets.
POINT_DEFINITIONS = [
    {"key": "order_menu_click1", "label": "Order Menu - Click 1",
     "help": "First click after /order opens."},
    {"key": "order_menu_click2", "label": "Order Menu - Click 2",
     "help": "Second click, opens the order itself."},
    {"key": "shop_hover_item", "label": "Shop - Item to Hover",
     "help": "Item in /shop whose tooltip shows the market price."},
]
# Order GUI slots are shift-clicked one at a time, slot 1 first.
POINT_DEFINITIONS += [
    {"key": f"order_slot_{i}", "label": f"Order Slot {i} (click point)",
     "help": f"Where to shift-click to take order slot {i}."}
    for i in range(1, 10)
]

# Boxes. Hotbar/order slot boxes are only used for empty/occupied detection;
# the OCR boxes are the only ones text is actually read from.
REGION_DEFINITIONS = [
    {"key": "price_tooltip_region", "label": "Price Tooltip (OCR)", "ocr": True,
     "help": "Box around the market price in the /shop tooltip."},
    {"key": "money_region", "label": "Money (OCR)", "ocr": True,
     "help": "Box around your balance, read during the selling phase."},
    {"key": "order_partial_region", "label": "Order Partial Option (match box)", "ocr": False,
     "help": "Screenshot box for the partial-order button; matched against its saved reference."},
    {"key": "order_full_region", "label": "Order Full Option (match box)", "ocr": False,
     "help": "Screenshot box for the full-order button; matched against its saved reference."},
]
REGION_DEFINITIONS += [
    {"key": "hotbar_strip", "label": "Hotbar (all 9 slots)", "ocr": False,
     "help": "One box around the whole hotbar; split into 9 automatically. "
             "Set this OR the individual slots below."},
    {"key": "order_strip", "label": "Order Row (all 9 slots)", "ocr": False,
     "help": "One box around the order GUI's slot row, split into 9."},
]
REGION_DEFINITIONS += [
    {"key": f"hotbar_slot_{i}", "label": f"Hotbar Slot {i}", "ocr": False,
     "help": f"Box around hotbar slot {i}, for empty/occupied detection."}
    for i in range(1, 10)
]
REGION_DEFINITIONS += [
    {"key": f"order_slot_{i}_region", "label": f"Order Slot {i} (detect box)", "ocr": False,
     "help": f"Box around order GUI slot {i}, for empty/occupied detection."}
    for i in range(1, 10)
]

# An OCR read can need the mouse parked somewhere first (a tooltip only
# appears while hovering). Kept separate from the box being read.
HOVER_DEFINITIONS = [
    {"key": "price_tooltip_region", "label": "Price Tooltip - Hover Point",
     "help": "Mouse goes here, then the price box is captured."},
    {"key": "money_region", "label": "Money - Hover Point",
     "help": "Optional. Leave unset if your balance is always on screen."},
]

TEMPLATE_DEFINITIONS = [
    {"key": "empty_hotbar_slot", "label": "Empty Hotbar Slot",
     "help": "Screenshot of one EMPTY hotbar slot."},
    {"key": "empty_order_slot", "label": "Empty Order Slot",
     "help": "Screenshot of one EMPTY order GUI slot."},
    {"key": "order_menu_ref", "label": "Order Menu Reference",
     "help": "Saved image used to pick the matching partial/full button from the two match boxes."},
]

KEYBIND_DEFINITIONS = [
    {"key": "toggle", "label": "Start / Stop", "default": "f8"},
    {"key": "pause", "label": "Pause / Resume", "default": "f9"},
    {"key": "emergency_stop", "label": "Emergency Stop", "default": "f10"},
    # Pressed from inside Minecraft, so the capture happens without having
    # to alt-tab out first - alt-tabbing is what changes the screen you
    # were trying to photograph.
    {"key": "capture", "label": "Capture Screen (Pixel/OCR)", "default": "f7"},
]

WEBHOOK_EVENTS = [
    {"key": "macro_started", "label": "Macro started", "default": True},
    {"key": "macro_stopped", "label": "Macro stopped", "default": True},
    {"key": "order_emptied", "label": "Order emptied", "default": True},
    {"key": "detection_error", "label": "OCR / detection error", "default": True},
    {"key": "unexpected_state", "label": "Unexpected state", "default": True},
    {"key": "emergency_stop", "label": "Manual emergency stop", "default": True},
    {"key": "session_summary", "label": "Periodic session summary", "default": True},
]

# Same delays the original AHK script used, in milliseconds, as (min, max)
# pairs - the macro sleeps a random duration in the range so the timing
# isn't robotically identical every cycle.
DEFAULT_TIMING = {
    "command": [300, 450],
    "enter": [800, 1200],
    "mouse_move": [150, 250],
    "before_click": [300, 500],
    "after_click": [450, 700],
    "menu": [550, 850],
    "before_shift": [250, 400],
    "shift": [120, 200],
    "slot": [350, 550],
    "sell": [650, 950],
    "scroll": [400, 600],
    "cycle": [900, 1400],
    "hover": [500, 800],
    "watch": [1500, 2500],
    # How long to wait for the inventory to visibly update after a
    # shift-click before re-checking the hotbar. Deliberately short: it's
    # paid once per pickup, so a generous value here noticeably slows the
    # whole macro down.
    "inventory_settle": [180, 260],
}

DEFAULT_ITEM = {
    "name": "New Item",
    "enabled": True,
    "batch_size": 9,
    "use_ocr_undercut": True,
    "undercut_mode": "fixed",       # "fixed" or "percent"
    "undercut_amount": 1000,
    "undercut_percent": 2.0,
    "min_price": 100,               # never list below this
    "max_price": 0,                 # 0 = no cap
    "sell_price": "32k",            # used when OCR undercutting is off
    "order_full": True,
    # Per-item overrides. Empty means "use the shared value".
    "points": {},
    "regions": {},
    "hover_points": {},
}

DEFAULT_SETTINGS = {
    "version": SETTINGS_VERSION,
    "points": {},
    "regions": {},
    "hover_points": {},
    "templates": {},
    "items": [],
    "active_item": None,
    "keybinds": {k["key"]: k["default"] for k in KEYBIND_DEFINITIONS},
    "webhook": {
        "url": "",
        "enabled": False,
        "events": {e["key"]: e["default"] for e in WEBHOOK_EVENTS},
        "summary_interval_minutes": 60,
    },
    "detection": {
        # Mean per-channel difference (0-255) still counted as a match.
        # Minecraft's slot background shifts slightly with GUI scale and
        # the inventory's translucent overlay, so exact equality is too
        # strict; 12 tolerates that without matching an actual item.
        "empty_slot_tolerance": 12.0,
        # An occupied slot has to differ from the reference by at least
        # this much before we call it occupied. Between the two values we
        # refuse to guess and treat the state as unknown.
        "occupied_slot_min_difference": 18.0,
    },
    "timing": copy.deepcopy(DEFAULT_TIMING),
    "general": {
        "pickup_retry_limit": 3,
        "sell_verify_retry_limit": 2,
        # Re-read the market before every single listing rather than once
        # per batch. Slower (one /shop trip per item) but it reacts to the
        # market moving mid-batch, which is how the macro has always run.
        "price_check_per_sell": True,
        "stop_on_unexpected_state": True,
        "start_minimized": False,
        "keep_cycling": True,
        "check_updates_on_start": True,
    },
}


# ----------------------------------------------------------------------
# Load / save
# ----------------------------------------------------------------------

def _deep_merge(defaults, data):
    """defaults overlaid with data, recursing into dicts (not lists)."""
    out = copy.deepcopy(defaults)
    for key, value in (data or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _migrate(data):
    """Bring a settings file from any older layout up to the current one.

    v1 stored a flat dict: sell_price/undercut_amount/... at the top level
    plus a single "pixels" map of key -> [x, y] or [x1, y1, x2, y2]. Those
    values become the first item and the shared point/region maps, so an
    upgrade keeps every coordinate the user already set.
    """
    if data.get("version") == SETTINGS_VERSION:
        return data
    if "version" in data and data["version"] > SETTINGS_VERSION:
        return data  # newer file, leave it alone rather than mangling it

    pixels = data.get("pixels", {}) or {}
    points, regions = {}, {}
    for key, value in pixels.items():
        if not isinstance(value, (list, tuple)):
            continue
        if len(value) == 2:
            points[key] = list(value)
        elif len(value) == 4:
            regions[key] = list(value)

    item = copy.deepcopy(DEFAULT_ITEM)
    item.update({
        "name": data.get("item_name", "Item 1"),
        "batch_size": 9,
        "use_ocr_undercut": bool(data.get("use_ocr_undercut", True)),
        "undercut_mode": data.get("undercut_mode", "fixed"),
        "undercut_amount": data.get("undercut_amount", 1000),
        "undercut_percent": data.get("undercut_percent", 2.0),
        "min_price": data.get("min_price", 100),
        "max_price": data.get("max_price", 0),
        "sell_price": str(data.get("sell_price", "32k")),
        "order_full": bool(data.get("order_full", True)),
    })

    migrated = copy.deepcopy(DEFAULT_SETTINGS)
    migrated["points"] = points
    migrated["regions"] = regions
    migrated["items"] = [item]
    migrated["active_item"] = item["name"]
    migrated["general"]["keep_cycling"] = bool(data.get("keep_cycling", True))
    return migrated


def _fresh():
    """First run: start with one item so the AH Flip tab has something to
    edit instead of an empty list the user has to guess their way out of."""
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    add_item(settings, "Firework Rocket")
    settings["active_item"] = item_names(settings)[0]
    return settings


def load_settings():
    if not os.path.exists(CONFIG_PATH):
        return _fresh()
    try:
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _fresh()
    settings = _deep_merge(DEFAULT_SETTINGS, _migrate(data))
    if not settings.get("items"):
        add_item(settings, "Firework Rocket")
    if settings.get("active_item") not in item_names(settings):
        settings["active_item"] = item_names(settings)[0]
    return settings


def save_settings(settings):
    settings["version"] = SETTINGS_VERSION
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(settings, f, indent=2)
    # Atomic replace: a crash mid-write can't leave a half-written file
    # that would silently reset every coordinate on next launch.
    os.replace(tmp, CONFIG_PATH)


# ----------------------------------------------------------------------
# Accessors
# ----------------------------------------------------------------------

def active_item(settings):
    """The item config the macro should run, or None if there are none."""
    items = settings.get("items") or []
    if not items:
        return None
    name = settings.get("active_item")
    for item in items:
        if item.get("name") == name:
            return item
    return items[0]


def set_active_item(settings, name):
    settings["active_item"] = name


def item_names(settings):
    return [item.get("name", "?") for item in settings.get("items", [])]


def add_item(settings, name=None, source=None):
    """Create an item (optionally duplicating `source`) and return it."""
    base = copy.deepcopy(source) if source else copy.deepcopy(DEFAULT_ITEM)
    existing = set(item_names(settings))
    wanted = name or base.get("name", "New Item")
    unique, n = wanted, 2
    while unique in existing:
        unique = f"{wanted} ({n})"
        n += 1
    base["name"] = unique
    settings.setdefault("items", []).append(base)
    return base


def delete_item(settings, name):
    settings["items"] = [i for i in settings.get("items", []) if i.get("name") != name]
    if settings.get("active_item") == name:
        settings["active_item"] = item_names(settings)[0] if settings.get("items") else None


def get_point(settings, key, item=None):
    """(x, y) for a click target: the item's override, else the shared one."""
    if item:
        value = (item.get("points") or {}).get(key)
        if value:
            return list(value)
    value = (settings.get("points") or {}).get(key)
    return list(value) if value else None


def set_point(settings, key, value, item=None):
    target = item.setdefault("points", {}) if item else settings.setdefault("points", {})
    target[key] = list(value)


def get_region(settings, key, item=None):
    """(x1, y1, x2, y2) for a box: the item's override, else the shared one."""
    if item:
        value = (item.get("regions") or {}).get(key)
        if value:
            return list(value)
    value = (settings.get("regions") or {}).get(key)
    return list(value) if value else None


def set_region(settings, key, value, item=None):
    target = item.setdefault("regions", {}) if item else settings.setdefault("regions", {})
    target[key] = list(value)


def get_hover_point(settings, key, item=None):
    """Where to park the mouse before reading the OCR box `key`, if anywhere."""
    if item:
        value = (item.get("hover_points") or {}).get(key)
        if value:
            return list(value)
    value = (settings.get("hover_points") or {}).get(key)
    return list(value) if value else None


def set_hover_point(settings, key, value, item=None):
    target = item.setdefault("hover_points", {}) if item else settings.setdefault("hover_points", {})
    target[key] = list(value)


def get_template_path(settings, key):
    path = (settings.get("templates") or {}).get(key)
    return path if path and os.path.exists(path) else None


def set_template_path(settings, key, path):
    settings.setdefault("templates", {})[key] = path


def timing(settings, key):
    """(min_ms, max_ms) for a delay, falling back to the shipped default."""
    value = (settings.get("timing") or {}).get(key) or DEFAULT_TIMING.get(key, [0, 0])
    return int(value[0]), int(value[1])


# ----------------------------------------------------------------------
# Sharing a setup with someone else
# ----------------------------------------------------------------------

BUNDLE_SETTINGS_NAME = "settings.json"
BUNDLE_TEMPLATE_DIR = "templates"


def export_bundle(settings, path):
    """Write a .zip holding the settings plus every reference image.

    The reference images have to travel with the file: `templates` stores
    absolute paths, and someone else's machine has no C:\\Users\\you. Inside
    the zip they are stored relative, and `import_bundle` rewrites them to
    wherever they land on the receiving machine.
    """
    data = copy.deepcopy(settings)
    templates = data.get("templates") or {}
    packed = {}

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for key, source in templates.items():
            if not source or not os.path.exists(source):
                continue
            name = f"{BUNDLE_TEMPLATE_DIR}/{key}{os.path.splitext(source)[1] or '.png'}"
            bundle.write(source, name)
            packed[key] = name
        data["templates"] = packed
        bundle.writestr(BUNDLE_SETTINGS_NAME, json.dumps(data, indent=2))

    return path


def import_bundle(path):
    """Load a bundle written by `export_bundle` and return the settings.

    Nothing is saved here - the caller decides. Template images are copied
    into this machine's template folder and the paths repointed at them.
    """
    with zipfile.ZipFile(path) as bundle:
        names = set(bundle.namelist())
        if BUNDLE_SETTINGS_NAME not in names:
            raise ValueError("That zip has no settings.json in it - it isn't "
                             "a config export.")
        data = json.loads(bundle.read(BUNDLE_SETTINGS_NAME).decode("utf-8"))

        os.makedirs(TEMPLATE_DIR, exist_ok=True)
        rewritten = {}
        for key, name in (data.get("templates") or {}).items():
            # Only ever read the entry this settings file points at, and
            # write it under a name we chose: a zip can otherwise carry
            # paths like ../../ and land a file wherever it likes.
            if not name or name not in names:
                continue
            target = os.path.join(TEMPLATE_DIR,
                                  f"{key}{os.path.splitext(name)[1] or '.png'}")
            with bundle.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            rewritten[key] = target
        data["templates"] = rewritten

    settings = _deep_merge(DEFAULT_SETTINGS, _migrate(data))
    if not settings.get("items"):
        add_item(settings, "Firework Rocket")
    if settings.get("active_item") not in item_names(settings):
        settings["active_item"] = item_names(settings)[0]
    return settings
