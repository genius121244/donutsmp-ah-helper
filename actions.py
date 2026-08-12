"""
actions.py
Every keyboard/mouse action the macro performs, and nothing else.

Same sequences and same delays as the original AHK script (they're tuned
to how fast the server actually responds), just with the timings read from
settings so they can be adjusted without editing code, and with the stop
check moved into one place.

Stopping: `is_running()` is checked before and after each step, so pressing
Stop takes effect within one action instead of at the end of the cycle.
Actions raise Stopped, which the engine catches - that beats returning a
flag from every call and hoping each caller checks it.
"""

import random
import time

import pyautogui

import config

pyautogui.FAILSAFE = True  # slamming the mouse into a screen corner aborts everything


class Stopped(Exception):
    """The user stopped the macro mid-action."""


class Actions:
    def __init__(self, settings, is_running, item=None):
        self.settings = settings
        self.is_running = is_running
        self.item = item

    # -- primitives ------------------------------------------------------

    def check(self):
        if not self.is_running():
            raise Stopped()

    def wait(self, key):
        """Sleep for the configured (min, max) range, in small slices so a
        stop during a 2.5s watch delay is noticed immediately."""
        low, high = config.timing(self.settings, key)
        deadline = time.time() + random.uniform(low, high) / 1000
        while time.time() < deadline:
            self.check()
            time.sleep(min(0.05, max(0.0, deadline - time.time())))

    def move(self, x, y):
        self.check()
        pyautogui.moveTo(x, y, duration=0)
        self.wait("mouse_move")

    def click(self, x, y):
        self.move(x, y)
        self.wait("before_click")
        self.check()
        pyautogui.click()
        self.wait("after_click")

    def shift_click(self, x, y):
        """Shift-click, used to move a whole stack in one action."""
        self.move(x, y)
        self.wait("before_shift")
        self.check()
        pyautogui.keyDown("shift")
        try:
            self.wait("shift")
            pyautogui.click()
            self.wait("slot")
        finally:
            # Leaving shift stuck down would make the player sneak and turn
            # every later click into a stack-move, so release it even when
            # the stop check fires mid-click.
            pyautogui.keyUp("shift")
        self.wait("shift")

    def hover(self, x, y):
        """Move without clicking - a tooltip only renders while hovering,
        and clicking the item in /shop would buy it."""
        self.move(x, y)

    def press(self, key):
        self.check()
        pyautogui.press(key)

    def type_text(self, text):
        self.check()
        pyautogui.write(text, interval=0.03)

    # -- game-level actions ----------------------------------------------

    def send_command(self, command):
        """Type '/<command>' into chat and send it."""
        self.type_text("/")
        self.wait("command")
        self.type_text(command)
        self.wait("command")
        self.press("enter")
        self.wait("enter")

    def close_menu(self):
        self.press("esc")
        self.wait("menu")

    def select_hotbar_slot(self, slot):
        if 1 <= slot <= 9:
            self.press(str(slot))
            self.wait("mouse_move")

    def click_point(self, key):
        x, y = self.require_point(key)
        self.click(x, y)
        self.wait("menu")

    def require_point(self, key):
        point = config.get_point(self.settings, key, self.item)
        if point is None:
            raise RuntimeError(
                f"Click point '{key}' is not set. Set it in the Pixel/OCR tab."
            )
        return point

    def require_region(self, key):
        region = config.get_region(self.settings, key, self.item)
        if region is None:
            raise RuntimeError(
                f"Box '{key}' is not set. Set it in the Pixel/OCR tab."
            )
        return tuple(region)
