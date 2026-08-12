"""
ui/theme.py
Colours, fonts and a few shared widget helpers.

Dark grey rather than black: pure black next to bright text is harsh to
read for hours, and greys give room for a visual hierarchy (window <
panel < input) that a flat black doesn't.
"""

import tkinter as tk
import customtkinter as ctk

BG = "#1e1f22"          # window
PANEL = "#26282c"       # cards / frames
PANEL_LIGHT = "#2f3237"  # inputs, hover
BORDER = "#3a3d43"

TEXT = "#e8eaed"
TEXT_MUTED = "#9aa0a6"

ACCENT = "#4c8dff"
ACCENT_HOVER = "#3b7ae4"
GREEN = "#2fa572"
GREEN_HOVER = "#268a5f"
YELLOW = "#e0a800"
RED = "#c0392b"
RED_HOVER = "#a3301f"

LEVEL_COLOURS = {
    "INFO": TEXT_MUTED,
    "SUCCESS": GREEN,
    "WARNING": YELLOW,
    "ERROR": RED,
}

STATUS_COLOURS = {
    "STOPPED": TEXT_MUTED,
    "IDLE": TEXT_MUTED,
    "ERROR": RED,
    "ORDER_EMPTY": GREEN,
    "PAUSED": YELLOW,
    "WATCHING": YELLOW,
}


# The size the layout was drawn at, and the smallest it can be squeezed to
# before cards start clipping. On a 1366x768 laptop the design height plus
# the taskbar doesn't fit, which is what the scaling below is for.
DESIGN_SIZE = (1080, 760)
MIN_SIZE = (940, 660)

# Room left for the taskbar and the window's own title bar.
_SCREEN_MARGIN = (40, 90)

SCALE_LIMITS = (0.6, 1.4)


def apply():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")


def fit_scale(screen_w, screen_h, requested=0):
    """How much to shrink the interface by, 1.0 being the design size.

    `requested` is the user's override; 0 means work it out from the screen.
    Auto only ever shrinks - on a big monitor the layout stays as drawn
    rather than being blown up to fill it.
    """
    low, high = SCALE_LIMITS
    if requested:
        return round(max(low, min(high, float(requested))), 2)

    # Fit the design size, not the minimum size: the point is for the whole
    # layout to be visible on a laptop screen, not merely for the window to
    # open. 1366x768 clears the minimum at full size and still cuts the
    # bottom off the cards.
    usable_w = screen_w - _SCREEN_MARGIN[0]
    usable_h = screen_h - _SCREEN_MARGIN[1]
    scale = min(usable_w / DESIGN_SIZE[0], usable_h / DESIGN_SIZE[1], 1.0)
    return round(max(low, scale), 2)


def window_size(screen_w, screen_h, scale):
    """Starting window size in real pixels, never bigger than the screen.

    Below the floor scale the window can still be taller than the screen;
    clamping here means the buttons at the bottom stay reachable instead of
    sitting under the taskbar.
    """
    width = min(int(DESIGN_SIZE[0] * scale), screen_w - _SCREEN_MARGIN[0])
    height = min(int(DESIGN_SIZE[1] * scale), screen_h - _SCREEN_MARGIN[1])
    return max(width, 400), max(height, 300)


def min_window_size(screen_w, screen_h, scale):
    width = min(int(MIN_SIZE[0] * scale), screen_w - _SCREEN_MARGIN[0])
    height = min(int(MIN_SIZE[1] * scale), screen_h - _SCREEN_MARGIN[1])
    return max(width, 400), max(height, 300)


def font(size=13, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def heading(parent, text, size=16):
    return ctk.CTkLabel(parent, text=text, font=font(size, "bold"), text_color=TEXT)


def caption(parent, text):
    return ctk.CTkLabel(parent, text=text, font=font(11), text_color=TEXT_MUTED,
                        justify="left", anchor="w")


def card(parent, **kwargs):
    kwargs.setdefault("fg_color", PANEL)
    kwargs.setdefault("corner_radius", 10)
    kwargs.setdefault("border_width", 1)
    kwargs.setdefault("border_color", BORDER)
    return ctk.CTkFrame(parent, **kwargs)


def primary_button(parent, text, command, **kwargs):
    kwargs.setdefault("fg_color", ACCENT)
    kwargs.setdefault("hover_color", ACCENT_HOVER)
    return ctk.CTkButton(parent, text=text, command=command, **kwargs)


def subtle_button(parent, text, command, **kwargs):
    kwargs.setdefault("fg_color", PANEL_LIGHT)
    kwargs.setdefault("hover_color", BORDER)
    kwargs.setdefault("text_color", TEXT)
    return ctk.CTkButton(parent, text=text, command=command, **kwargs)


def enable_mousewheel_scroll(frame):
    """Enable mouse-wheel scrolling for a CTkScrollableFrame.

    The exact internal canvas name varies across customtkinter versions,
    so we search recursively for any widget that supports yview_scroll.
    """
    def _find_scrolling_widget(widget):
        if hasattr(widget, "yview_scroll"):
            return widget
        for child in widget.winfo_children():
            found = _find_scrolling_widget(child)
            if found:
                return found
        return None

    canvas = getattr(frame, "_canvas", None) or getattr(frame, "canvas", None)
    if canvas is None:
        canvas = _find_scrolling_widget(frame)
    if canvas is None:
        return

    def _on_wheel(event):
        delta = 0
        if hasattr(event, "delta") and event.delta:
            delta = -1 if event.delta > 0 else 1
        elif getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        if delta:
            canvas.yview_scroll(delta, "units")
            return "break"

    def _bind_wheel(_event=None):
        frame.bind_all("<MouseWheel>", _on_wheel)
        frame.bind_all("<Button-4>", _on_wheel)
        frame.bind_all("<Button-5>", _on_wheel)

    def _unbind_wheel(_event=None):
        frame.unbind_all("<MouseWheel>")
        frame.unbind_all("<Button-4>")
        frame.unbind_all("<Button-5>")

    frame.bind("<Enter>", lambda e: frame.focus_set())
    frame.bind("<Enter>", _bind_wheel)
    frame.bind("<Leave>", _unbind_wheel)
    canvas.bind("<MouseWheel>", _on_wheel)
    canvas.bind("<Button-4>", _on_wheel)
    canvas.bind("<Button-5>", _on_wheel)


def status_colour(state):
    return STATUS_COLOURS.get(state, ACCENT)
