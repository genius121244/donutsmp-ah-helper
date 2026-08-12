"""
ui/tab_settings.py
Detection thresholds, timings, retries and config file management.

These are the knobs that only need touching when something behaves oddly -
the day-to-day settings live in AH Flip and Pixel / OCR, so they aren't
buried here.
"""

import os
import shutil
import threading
import time

import customtkinter as ctk
from tkinter import filedialog

import config
import fontpack
import updater
from applog import log
from ui import theme
from version import VERSION

TIMING_LABELS = {
    "command": "Typing a command",
    "enter": "After pressing Enter",
    "mouse_move": "After moving the mouse",
    "before_click": "Before a click",
    "after_click": "After a click",
    "menu": "After a menu opens/closes",
    "before_shift": "Before a shift-click",
    "shift": "Holding shift",
    "slot": "After a slot click",
    "sell": "After /ah sell",
    "scroll": "Between hotbar slots",
    "cycle": "Between cycles",
    "hover": "Tooltip render time",
    "watch": "Between price re-checks while waiting",
    "inventory_settle": "Inventory update before re-checking slots",
}


class SettingsTab:
    def __init__(self, parent, app):
        self.app = app
        self.parent = parent
        self.vars = {}
        self._loading = False
        self._build()
        self.refresh()

    def _build(self):
        scroll = ctk.CTkScrollableFrame(self.parent, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=14, pady=14)
        theme.enable_mousewheel_scroll(scroll)

        # -- detection -------------------------------------------------------
        detection = theme.card(scroll)
        detection.pack(fill="x", pady=(0, 12))
        theme.heading(detection, "Detection", 15).pack(anchor="w", padx=16, pady=(14, 2))
        theme.caption(detection,
                      "How different a slot may look from the empty-slot "
                      "reference and still count as empty. Anything between "
                      "the two numbers is treated as unreadable and stops the "
                      "macro instead of being guessed at.").pack(
            anchor="w", padx=16, pady=(0, 4))
        self._number(detection, ("detection", "empty_slot_tolerance"),
                     "Empty if difference is at most", float)
        self._number(detection, ("detection", "occupied_slot_min_difference"),
                     "Occupied if difference is at least", float)

        # -- behaviour -------------------------------------------------------
        general = theme.card(scroll)
        general.pack(fill="x", pady=(0, 12))
        theme.heading(general, "Behaviour", 15).pack(anchor="w", padx=16, pady=(14, 2))
        self._number(general, ("general", "pickup_retry_limit"),
                     "Pickup retries before stopping", int)
        self._number(general, ("general", "sell_verify_retry_limit"),
                     "Sell retries before stopping", int)
        self._switch(general, ("general", "keep_cycling"),
                     "Keep cycling until the order is empty")
        self._switch(general, ("general", "price_check_per_sell"),
                     "Re-check the market price before every listing")
        self._switch(general, ("general", "stop_on_unexpected_state"),
                     "Stop on any unverified step (recommended)")

        # -- timings ---------------------------------------------------------
        timings = theme.card(scroll)
        timings.pack(fill="x", pady=(0, 12))
        theme.heading(timings, "Timing (milliseconds)", 15).pack(
            anchor="w", padx=16, pady=(14, 2))
        theme.caption(timings,
                      "Each delay is a random value between min and max, so "
                      "the timing isn't identical every cycle. Raise these if "
                      "the server lags; lowering them too far makes clicks "
                      "land before the GUI has opened.").pack(
            anchor="w", padx=16, pady=(0, 4))
        for key, label in TIMING_LABELS.items():
            self._range(timings, key, label)

        # -- updates ---------------------------------------------------------
        updates = theme.card(scroll)
        updates.pack(fill="x", pady=(0, 12))
        theme.heading(updates, "Updates", 15).pack(anchor="w", padx=16, pady=(14, 2))
        theme.caption(updates,
                      f"You are on version {VERSION}. New builds are picked up "
                      f"from the GitHub releases page; your settings live "
                      f"outside the program, so updating never touches "
                      f"them.").pack(anchor="w", padx=16)

        update_row = ctk.CTkFrame(updates, fg_color="transparent")
        update_row.pack(fill="x", padx=16, pady=10)
        self.update_button = theme.subtle_button(
            update_row, "Check for updates", self.check_updates, width=150)
        self.update_button.pack(side="left", padx=(0, 8))
        self.update_status = theme.caption(update_row, "")
        self.update_status.pack(side="left")

        self._switch(updates, ("general", "check_updates_on_start"),
                     "Check for updates when the app starts")
        ctk.CTkLabel(updates, text="").pack(pady=2)

        # -- resource pack ----------------------------------------------------
        pack = theme.card(scroll)
        pack.pack(fill="x", pady=(0, 12))
        theme.heading(pack, "Minecraft font pack", 15).pack(
            anchor="w", padx=16, pady=(14, 2))
        theme.caption(pack,
                      "The price reader only matches text drawn with this pack, "
                      "so install it and\nturn it on in Minecraft (Options - "
                      "Resource Packs) before running the macro.\nInstalls to:\n"
                      f"{fontpack.resourcepacks_dir()}").pack(anchor="w", padx=16)

        pack_row = ctk.CTkFrame(pack, fg_color="transparent")
        pack_row.pack(fill="x", padx=16, pady=10)
        theme.subtle_button(pack_row, "Install into Minecraft",
                            self.install_font_pack, width=170).pack(side="left",
                                                                    padx=(0, 8))
        self.pack_status = theme.caption(pack_row, "")
        self.pack_status.pack(side="left")

        # -- config ----------------------------------------------------------
        files = theme.card(scroll)
        files.pack(fill="x")
        theme.heading(files, "Configuration", 15).pack(anchor="w", padx=16, pady=(14, 2))
        theme.caption(files, f"Saved automatically to:\n{config.CONFIG_PATH}").pack(
            anchor="w", padx=16)
        row = ctk.CTkFrame(files, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=12)
        theme.subtle_button(row, "Back up now", self.backup, width=130).pack(side="left", padx=3)
        theme.subtle_button(row, "Open folder", self.open_folder, width=130).pack(side="left", padx=3)
        ctk.CTkButton(row, text="Reset timings", width=130, fg_color=theme.RED,
                      hover_color=theme.RED_HOVER,
                      command=self.reset_timings).pack(side="left", padx=3)

        theme.caption(files,
                      "Share your whole setup as one file (settings + reference "
                      "images).\nOnly lines up on a machine with the same screen "
                      "resolution and\nMinecraft GUI scale - otherwise the boxes "
                      "land in the wrong place.").pack(anchor="w", padx=16)
        share = ctk.CTkFrame(files, fg_color="transparent")
        share.pack(fill="x", padx=16, pady=(6, 0))
        theme.subtle_button(share, "Export config", self.export_config,
                            width=130).pack(side="left", padx=3)
        theme.subtle_button(share, "Import config", self.import_config,
                            width=130).pack(side="left", padx=3)

        self.status = theme.caption(files, "")
        self.status.pack(anchor="w", padx=16, pady=(6, 14))

    # -- field builders --------------------------------------------------

    def _labelled_row(self, parent, label):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row, text=label, width=300, anchor="w",
                     font=theme.font(12)).pack(side="left")
        return row

    def _number(self, parent, path, label, cast):
        row = self._labelled_row(parent, label)
        var = ctk.StringVar()
        ctk.CTkEntry(row, textvariable=var, width=100).pack(side="left")
        var.trace_add("write", lambda *_: self._save_number(path, var, cast))
        self.vars[path] = var

    def _switch(self, parent, path, label):
        row = self._labelled_row(parent, label)
        var = ctk.BooleanVar()
        ctk.CTkSwitch(row, text="", variable=var,
                      command=lambda: self._save_switch(path, var)).pack(side="left")
        self.vars[path] = var

    def _range(self, parent, key, label):
        row = self._labelled_row(parent, label)
        low, high = ctk.StringVar(), ctk.StringVar()
        ctk.CTkEntry(row, textvariable=low, width=80).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(row, text="to", font=theme.font(11),
                     text_color=theme.TEXT_MUTED).pack(side="left", padx=4)
        ctk.CTkEntry(row, textvariable=high, width=80).pack(side="left", padx=6)
        low.trace_add("write", lambda *_: self._save_range(key, low, high))
        high.trace_add("write", lambda *_: self._save_range(key, low, high))
        self.vars[("timing", key)] = (low, high)

    # -- persistence -----------------------------------------------------

    def _save_number(self, path, var, cast):
        if self._loading:
            return
        try:
            value = cast(var.get())
        except (TypeError, ValueError):
            return
        self.app.settings.setdefault(path[0], {})[path[1]] = value
        self.app.save_settings()

    def _save_switch(self, path, var):
        if self._loading:
            return
        self.app.settings.setdefault(path[0], {})[path[1]] = bool(var.get())
        self.app.save_settings()

    def _save_range(self, key, low, high):
        if self._loading:
            return
        try:
            low_value, high_value = int(low.get()), int(high.get())
        except (TypeError, ValueError):
            return
        if low_value < 0 or high_value < low_value:
            return  # inverted range would make random.uniform misbehave
        self.app.settings.setdefault("timing", {})[key] = [low_value, high_value]
        self.app.save_settings()

    # -- buttons ---------------------------------------------------------

    def backup(self):
        self.app.save_settings()
        target = config.CONFIG_PATH.replace(
            ".json", f"-backup-{time.strftime('%Y%m%d-%H%M%S')}.json")
        shutil.copy2(config.CONFIG_PATH, target)
        self.status.configure(text=f"Backed up to {os.path.basename(target)}")
        log.success(f"Settings backed up to {target}")

    def install_font_pack(self):
        try:
            target = fontpack.install()
        except (FileNotFoundError, OSError, shutil.Error) as e:
            self.pack_status.configure(text=str(e))
            log.error(f"Font pack install failed: {e}")
            return
        self.pack_status.configure(
            text="Installed - enable 'Font+' in Minecraft's resource packs")
        log.success(f"Font pack installed to {target}")

    def export_config(self):
        """Everything needed to reproduce this setup, in one zip."""
        self.app.save_settings()
        path = filedialog.asksaveasfilename(
            title="Export config", defaultextension=".zip",
            initialfile=f"donut-ah-config-{time.strftime('%Y%m%d')}.zip",
            filetypes=[("Config bundle", "*.zip")])
        if not path:
            return
        try:
            config.export_bundle(self.app.settings, path)
        except OSError as e:
            self.status.configure(text=f"Could not export: {e}")
            log.error(f"Config export failed: {e}")
            return
        self.status.configure(text=f"Exported to {os.path.basename(path)}")
        log.success(f"Config exported to {path}")

    def import_config(self):
        """Replace everything with someone else's setup.

        A backup is taken first, unprompted: this overwrites every
        coordinate, and there is no undo otherwise.
        """
        path = filedialog.askopenfilename(
            title="Import config", filetypes=[("Config bundle", "*.zip")])
        if not path:
            return
        try:
            imported = config.import_bundle(path)
        except (OSError, ValueError, KeyError) as e:
            self.status.configure(text=f"Could not import: {e}")
            log.error(f"Config import failed: {e}")
            return

        self.backup()
        self.app.replace_settings(imported)
        self.status.configure(text=f"Imported {os.path.basename(path)} "
                                   f"(your old config was backed up first)")
        log.success(f"Config imported from {path}")

    def open_folder(self):
        folder = os.path.dirname(config.CONFIG_PATH)
        try:
            os.startfile(folder)  # Windows only; the macro's actual platform
        except AttributeError:
            self.status.configure(text=folder)

    # -- updates ---------------------------------------------------------

    def check_updates(self):
        self.update_button.configure(state="disabled")
        self.update_status.configure(text="Checking...")

        def done(update):
            self.parent.after(0, self._show_update, update)

        def run():
            done(updater.check())

        threading.Thread(target=run, daemon=True).start()

    def _show_update(self, update):
        self.update_button.configure(state="normal")
        if update is None:
            self.update_status.configure(text=f"{VERSION} is the latest version.")
            return
        self.update_status.configure(text=f"Version {update.version} available.")
        self.app.offer_update(update)

    def reset_timings(self):
        self.app.settings["timing"] = dict(config.DEFAULT_TIMING)
        self.app.save_settings()
        self.refresh()
        self.status.configure(text="Timings reset to defaults")

    def refresh(self):
        self._loading = True
        try:
            for path, var in self.vars.items():
                section, key = path
                value = (self.app.settings.get(section) or {}).get(key)
                if isinstance(var, tuple):
                    low, high = value or config.DEFAULT_TIMING.get(key, [0, 0])
                    var[0].set(str(low))
                    var[1].set(str(high))
                elif isinstance(var, ctk.BooleanVar):
                    var.set(bool(value))
                else:
                    var.set("" if value is None else str(value))
        finally:
            self._loading = False

        self.pack_status.configure(
            text="Already installed" if fontpack.is_installed() else "")
