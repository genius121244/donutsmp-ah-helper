"""
ui/theme.py
Colours, fonts and a few shared widget helpers.

Dark grey rather than black: pure black next to bright text is harsh to
read for hours, and greys give room for a visual hierarchy (window <
panel < input) that a flat black doesn't.
"""

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


def apply():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")


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


def status_colour(state):
    return STATUS_COLOURS.get(state, ACCENT)
