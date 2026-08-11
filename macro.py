"""
macro.py
Ports the original AHK click/type sequence to Python (pyautogui),
reading pixel locations from settings.json instead of hardcoded
coordinates, and optionally computing the sell price from OCR
(reads the lowest listed price, then undercuts it) instead of
using a fixed sell price every time.

This is meant to be run in a background thread from gui.py so the
GUI stays responsive. Call `run(settings, is_running)` where
is_running is a zero-arg callable returning True/False (so the
loop can be stopped cleanly from the Stop button / F8).
"""

import random
import time

import pyautogui

import config
import ocr

pyautogui.FAILSAFE = True  # moving mouse to a screen corner aborts pyautogui immediately

# =========================
# DELAY SETTINGS (ms) — same values as the original AHK script
# =========================
CMD_MIN, CMD_MAX = 300, 450
ENTER_MIN, ENTER_MAX = 800, 1200
MOUSE_MIN, MOUSE_MAX = 150, 250
BEFORE_CLICK_MIN, BEFORE_CLICK_MAX = 300, 500
AFTER_CLICK_MIN, AFTER_CLICK_MAX = 450, 700
MENU_MIN, MENU_MAX = 550, 850
BEFORE_SHIFT_MIN, BEFORE_SHIFT_MAX = 250, 400
SHIFT_MIN, SHIFT_MAX = 120, 200
SLOT_MIN, SLOT_MAX = 350, 550
SELL_MIN, SELL_MAX = 650, 950
SCROLL_MIN, SCROLL_MAX = 400, 600
CYCLE_MIN, CYCLE_MAX = 900, 1400
HOVER_MIN, HOVER_MAX = 500, 800  # time to let the tooltip render before OCR reads it
WATCH_MIN, WATCH_MAX = 1500, 2500  # how often to re-check price while waiting for it to clear the threshold


def _wait(min_ms, max_ms):
    time.sleep(random.uniform(min_ms, max_ms) / 1000)


def _require_pixel(settings, key):
    value = config.get_pixel(settings, key)
    if value is None:
        raise RuntimeError(f"Pixel location '{key}' is not set. Set it in the GUI first.")
    return value


def safe_click(x, y, is_running):
    if not is_running():
        return
    pyautogui.moveTo(x, y, duration=0)
    _wait(MOUSE_MIN, MOUSE_MAX)
    if not is_running():
        return
    _wait(BEFORE_CLICK_MIN, BEFORE_CLICK_MAX)
    if not is_running():
        return
    pyautogui.click()
    _wait(AFTER_CLICK_MIN, AFTER_CLICK_MAX)


def shift_click(x, y, is_running):
    if not is_running():
        return
    pyautogui.moveTo(x, y, duration=0)
    _wait(MOUSE_MIN, MOUSE_MAX)
    if not is_running():
        return
    _wait(BEFORE_SHIFT_MIN, BEFORE_SHIFT_MAX)
    if not is_running():
        return
    pyautogui.keyDown("shift")
    _wait(SHIFT_MIN, SHIFT_MAX)
    if not is_running():
        pyautogui.keyUp("shift")
        return
    pyautogui.click()
    _wait(SLOT_MIN, SLOT_MAX)
    if not is_running():
        pyautogui.keyUp("shift")
        return
    pyautogui.keyUp("shift")
    _wait(SHIFT_MIN, SHIFT_MAX)
    if not is_running():
        return
    _wait(SLOT_MIN, SLOT_MAX)


def send_text(text, is_running):
    if not is_running():
        return
    pyautogui.write(text, interval=0.03)


def hover_only(x, y, is_running):
    """Moves the mouse to a spot WITHOUT clicking — used to trigger a
    tooltip (e.g. hovering an item in /shop to reveal its price)."""
    if not is_running():
        return
    pyautogui.moveTo(x, y, duration=0)
    _wait(MOUSE_MIN, MOUSE_MAX)


def select_hotbar_slot(slot, is_running):
    """Selects a hotbar slot by pressing the number key 1-9."""
    if not is_running():
        return
    if 1 <= slot <= 9:
        pyautogui.press(str(slot))
        _wait(MOUSE_MIN, MOUSE_MAX)


def open_shop(is_running):
    if not is_running():
        return
    send_text("/", is_running)
    _wait(CMD_MIN, CMD_MAX)
    if not is_running():
        return
    send_text("shop", is_running)
    _wait(CMD_MIN, CMD_MAX)
    if not is_running():
        return
    pyautogui.press("enter")
    _wait(ENTER_MIN, ENTER_MAX)


def close_shop(is_running):
    if not is_running():
        return
    pyautogui.press("esc")
    _wait(MENU_MIN, MENU_MAX)


def read_shop_price(settings, is_running):
    if not is_running():
        return None

    hover_point = _require_pixel(settings, "shop_hover_item")
    region = _require_pixel(settings, "price_tooltip_region")

    hover_only(hover_point[0], hover_point[1], is_running)
    if not is_running():
        return None

    _wait(HOVER_MIN, HOVER_MAX)
    if not is_running():
        return None

    return ocr.get_lowest_price(tuple(region))


def check_shop_lowest_price(settings, is_running):
    """
    Opens /shop, hovers (no click) over the configured item to reveal
    its price tooltip, OCRs the tooltip region, then closes the shop
    menu again. Returns the parsed lowest price as an int, or None if
    OCR couldn't read anything.
    """
    if not is_running():
        return None

    hover_point = _require_pixel(settings, "shop_hover_item")
    region = _require_pixel(settings, "price_tooltip_region")

    send_text("/", is_running)
    _wait(CMD_MIN, CMD_MAX)
    if not is_running():
        return None

    send_text("shop", is_running)
    _wait(CMD_MIN, CMD_MAX)
    if not is_running():
        return None

    pyautogui.press("enter")
    _wait(ENTER_MIN, ENTER_MAX)
    if not is_running():
        return None

    # Hover only — clicking would buy/select the item instead of just reading its price
    hover_only(hover_point[0], hover_point[1], is_running)
    if not is_running():
        return None

    # Give the tooltip time to actually render before screenshotting it
    _wait(HOVER_MIN, HOVER_MAX)
    if not is_running():
        return None

    lowest_price = ocr.get_lowest_price(tuple(region))

    # Close the shop menu before moving on to /order
    pyautogui.press("esc")
    _wait(MENU_MIN, MENU_MAX)

    return lowest_price


def determine_sell_price(settings, is_running, on_status=None):
    """
    Returns the price string to type into `/ah sell <price>` for
    ONE sell action. If OCR undercutting is enabled, re-opens /shop
    and re-reads the price fresh every time it's called.

    Two special cases:
    - MAX PRICE CAP: if the undercut price would exceed max_price,
      sell at max_price immediately — no waiting, just cap and go.
    - MIN PRICE THRESHOLD: if the undercut price would fall below
      min_price (meaning you can't undercut and still stay above
      your floor), don't sell yet — keep re-checking the shop price
      every couple seconds until the market moves enough that
      undercutting stays above the threshold.

    Returns None only if the macro was stopped while watching.
    Falls back to the fixed sell_price setting if OCR is disabled
    or fails to read a number.
    """
    if not settings.get("use_ocr_undercut", False):
        return str(settings.get("sell_price", "32k"))

    max_price = settings.get("max_price", 0)  # 0 = no cap
    min_price = settings.get("min_price", 100)
    mode = settings.get("undercut_mode", "fixed")
    amount = settings.get("undercut_amount", 1000)
    percent = settings.get("undercut_percent", 2.0)

    while is_running():
        open_shop(is_running)
        if not is_running():
            return None

        lowest = read_shop_price(settings, is_running)
        if not is_running():
            return None

        if lowest is None:
            close_shop(is_running)
            print("[PRICE CHECK] OCR could not read a valid price (missing k/m suffix or no match). "
                  f"Falling back to fixed sell price: {settings.get('sell_price', '32k')}")
            return str(settings.get("sell_price", "32k"))

        if mode == "percent":
            raw_price = lowest - (lowest * (percent / 100))
        else:
            raw_price = lowest - amount
        raw_price = int(raw_price)

        print(f"[PRICE CHECK] OCR read lowest={lowest} | mode={mode} | "
              f"raw undercut result={raw_price} | min_price={min_price} | max_price={max_price}")

        # Cap: computed price is above the ceiling — sell at the cap right away, no watching
        if max_price and max_price > 0 and raw_price > max_price:
            print(f"[DECISION] {raw_price} is above max_price cap ({max_price}) -> selling at cap, no wait.")
            close_shop(is_running)
            return ocr.format_price(max_price)

        # Threshold: computed price would fall below the floor — stay in /shop and keep watching.
        if raw_price < min_price:
            print(f"[DECISION] {raw_price} is below min_price threshold ({min_price}) -> WATCHING, will re-check.")
            if on_status:
                on_status(f"Status: WATCHING (under {min_price} threshold)")

            while is_running():
                _wait(WATCH_MIN, WATCH_MAX)
                lowest = read_shop_price(settings, is_running)
                if not is_running():
                    return None
                if lowest is None:
                    continue

                if mode == "percent":
                    raw_price = lowest - (lowest * (percent / 100))
                else:
                    raw_price = lowest - amount
                raw_price = int(raw_price)

                if raw_price < min_price:
                    print(f"[DECISION] {raw_price} is still below min_price threshold ({min_price}) -> continue watching.")
                    continue

                print(f"[DECISION] {raw_price} now clears threshold -> selling at {ocr.format_price(raw_price)}")
                if max_price and max_price > 0 and raw_price > max_price:
                    print(f"[DECISION] {raw_price} is above max_price cap ({max_price}) -> selling at cap, no wait.")
                    close_shop(is_running)
                    return ocr.format_price(max_price)

                close_shop(is_running)
                return ocr.format_price(raw_price)

        print(f"[DECISION] {raw_price} clears threshold -> selling at {ocr.format_price(raw_price)}")
        close_shop(is_running)
        return ocr.format_price(raw_price)

    return None


def do_cycle(settings, is_running, on_status=None):
    """Runs one full order + 9-sell cycle. Returns normally, or early if stopped."""

    if not is_running():
        return

    # ---- OPEN /ORDER ----
    send_text("/", is_running)
    _wait(CMD_MIN, CMD_MAX)
    if not is_running():
        return

    send_text("order", is_running)
    _wait(CMD_MIN, CMD_MAX)
    if not is_running():
        return

    pyautogui.press("enter")
    _wait(ENTER_MIN, ENTER_MAX)
    if not is_running():
        return

    # ---- ORDER MENU NAVIGATION ----
    x, y = _require_pixel(settings, "order_menu_click1")
    safe_click(x, y, is_running)
    if not is_running():
        return
    _wait(MENU_MIN, MENU_MAX)
    if not is_running():
        return

    x, y = _require_pixel(settings, "order_menu_click2")
    safe_click(x, y, is_running)
    if not is_running():
        return
    _wait(MENU_MIN, MENU_MAX)
    if not is_running():
        return

    if settings.get("order_full", True):
        x, y = _require_pixel(settings, "order_full_click")
    else:
        x, y = _require_pixel(settings, "order_partial_click")
    safe_click(x, y, is_running)
    if not is_running():
        return
    _wait(MENU_MIN, MENU_MAX)
    if not is_running():
        return

    # ---- SHIFT CLICK 9 SLOTS ----
    for i in range(1, 10):
        x, y = _require_pixel(settings, f"inventory_slot_{i}")
        shift_click(x, y, is_running)
        if not is_running():
            return

    _wait(MENU_MIN, MENU_MAX)
    if not is_running():
        return

    # ---- CLOSE MENU ----
    _wait(BEFORE_CLICK_MIN, BEFORE_CLICK_MAX)
    if not is_running():
        return
    pyautogui.press("esc")
    _wait(MENU_MIN, MENU_MAX)
    if not is_running():
        return

    # Make sure the sell slot starts at hotbar 1 before the first sell.
    select_hotbar_slot(1, is_running)

    # ---- 9 AH SELL CYCLE ----
    for i in range(1, 10):
        if not is_running():
            return

        # Fresh price check before EVERY sell — slower, but reacts to
        # the market changing mid-cycle instead of using a stale price.
        # May return None if stopped while watching for the threshold.
        sell_price = determine_sell_price(settings, is_running, on_status=on_status)
        if not is_running() or sell_price is None:
            return

        if on_status:
            on_status("Status: RUNNING")

        send_text("/", is_running)
        _wait(CMD_MIN, CMD_MAX)
        if not is_running():
            return

        send_text(f"ah sell {sell_price}", is_running)
        _wait(CMD_MIN, CMD_MAX)
        if not is_running():
            return

        pyautogui.press("enter")
        _wait(ENTER_MIN, ENTER_MAX)
        if not is_running():
            return

        _wait(SELL_MIN, SELL_MAX)
        if not is_running():
            return

        _wait(SCROLL_MIN, SCROLL_MAX)
        if not is_running():
            return

        next_slot = 1 if i == 9 else i + 1
        select_hotbar_slot(next_slot, is_running)
        _wait(SCROLL_MIN, SCROLL_MAX)
        if not is_running():
            return


def run(settings, is_running, on_status=None, on_error=None):
    """
    Main entry point, meant to be called from a background thread.
    Loops cycles while keep_cycling is enabled and is_running() is True.
    """
    try:
        while is_running():
            do_cycle(settings, is_running, on_status=on_status)

            if not is_running():
                break

            if settings.get("keep_cycling", False):
                if on_status:
                    on_status("Status: NEXT CYCLE")
                _wait(CYCLE_MIN, CYCLE_MAX)
            else:
                break

        if on_status:
            on_status("Status: READY" if is_running() else "Status: STOPPED")

    except Exception as e:
        if on_error:
            on_error(str(e))
        if on_status:
            on_status("Status: ERROR")
