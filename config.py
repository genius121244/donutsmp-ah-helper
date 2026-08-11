"""
config.py
Handles loading/saving all persistent settings (sell price, checkboxes,
and pixel locations) to a single JSON file.

IMPORTANT: this is stored in %APPDATA% (a stable per-user Windows folder),
NOT next to the script. That's on purpose — if it lived next to the
script, every time you download an updated version and extract it to a
new/different folder, your saved pixel locations would be lost and you'd
have to redo them. Storing it in %APPDATA% means updates never touch it.
"""

import json
import os

_APP_DIR_NAME = "DonutAHMacro"

if os.name == "nt" and os.environ.get("APPDATA"):
    _CONFIG_DIR = os.path.join(os.environ["APPDATA"], _APP_DIR_NAME)
else:
    # Non-Windows fallback (e.g. testing on Mac/Linux): use home folder instead
    _CONFIG_DIR = os.path.join(os.path.expanduser("~"), f".{_APP_DIR_NAME}")

os.makedirs(_CONFIG_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(_CONFIG_DIR, "settings.json")

# Every pixel/region the macro needs, with a friendly display name.
# "point" = single (x, y) click location
# "region" = box (x1, y1, x2, y2), used for OCR screenshotting
PIXEL_DEFINITIONS = [
    {"key": "order_menu_click1", "label": "Order Menu - Click 1", "type": "point"},
    {"key": "order_menu_click2", "label": "Order Menu - Click 2", "type": "point"},
    {"key": "order_full_click", "label": "Order Full Option", "type": "point"},
    {"key": "order_partial_click", "label": "Order Partial Option", "type": "point"},
    {"key": "inventory_slot_1", "label": "Inventory Slot 1", "type": "point"},
    {"key": "inventory_slot_2", "label": "Inventory Slot 2", "type": "point"},
    {"key": "inventory_slot_3", "label": "Inventory Slot 3", "type": "point"},
    {"key": "inventory_slot_4", "label": "Inventory Slot 4", "type": "point"},
    {"key": "inventory_slot_5", "label": "Inventory Slot 5", "type": "point"},
    {"key": "inventory_slot_6", "label": "Inventory Slot 6", "type": "point"},
    {"key": "inventory_slot_7", "label": "Inventory Slot 7", "type": "point"},
    {"key": "inventory_slot_8", "label": "Inventory Slot 8", "type": "point"},
    {"key": "inventory_slot_9", "label": "Inventory Slot 9", "type": "point"},
    {"key": "price_tooltip_region", "label": "Price Tooltip Region (drag box)", "type": "region"},
    {"key": "shop_hover_item", "label": "Shop - Item to Hover", "type": "point"},
]

DEFAULT_SETTINGS = {
    "sell_price": "32k",
    "keep_cycling": False,
    "order_full": True,
    "undercut_mode": "fixed",     # "fixed" or "percent"
    "undercut_amount": 1000,      # used when undercut_mode == "fixed"
    "undercut_percent": 2.0,      # used when undercut_mode == "percent"
    "use_ocr_undercut": False,    # if True, price is computed from OCR each cycle
    "min_price": 100,             # threshold floor — if undercutting would go below this, WAIT instead of selling
    "max_price": 0,               # cap — if undercutting would go above this, sell at the cap immediately (0 = no cap)
    "pixels": {}  # filled in as: key -> [x, y] or key -> [x1, y1, x2, y2]
}


def load_settings():
    if not os.path.exists(CONFIG_PATH):
        return dict(DEFAULT_SETTINGS)

    try:
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_SETTINGS)

    # Make sure any missing keys fall back to defaults (handles upgrades)
    merged = dict(DEFAULT_SETTINGS)
    merged.update(data)
    if "pixels" not in merged or not isinstance(merged["pixels"], dict):
        merged["pixels"] = {}
    return merged


def save_settings(settings):
    with open(CONFIG_PATH, "w") as f:
        json.dump(settings, f, indent=2)


def get_pixel(settings, key):
    """Returns the saved coordinates for a pixel key, or None if not set."""
    return settings.get("pixels", {}).get(key)


def set_pixel(settings, key, value):
    """value is [x, y] for a point, or [x1, y1, x2, y2] for a region."""
    settings.setdefault("pixels", {})[key] = value
    save_settings(settings)
