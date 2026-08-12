"""
ui/app.py
The main window: owns the settings, the macro thread and the hotkeys, and
hands all three to the tabs.

Threading rule for everything under ui/: the macro runs on a background
thread and logs from there, so anything that touches a widget goes through
`self.after(0, ...)`. Tk crashes in confusing ways if that's skipped.
"""

import threading

import customtkinter as ctk

import config
import engine
import keybinds
import updater
from applog import log
from ui import theme
from version import VERSION
from ui.tab_ahflip import AHFlipTab
from ui.tab_dashboard import DashboardTab
from ui.tab_keybinds import KeybindsTab
from ui.tab_logs import LogsTab
from ui.tab_pixelocr import PixelOCRTab
from ui.tab_settings import SettingsTab

TABS = ["Dashboard", "AH Flip", "Pixel / OCR", "Keybinds", "Logs / Webhook", "Settings"]


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        theme.apply()

        self.title(f"DonutSMP AH Macro {VERSION}")
        self.geometry("1080x760")
        self.minsize(940, 660)
        self.configure(fg_color=theme.BG)

        self.settings = config.load_settings()
        self.running = False
        self.paused = False
        self.macro_thread = None
        # Not `self.state`: Tk's own window.state() method lives there.
        self.macro_state = "STOPPED"
        self.stats = None

        self._build_layout()

        self.keybind_manager = keybinds.KeybindManager(self.settings, {
            "toggle": lambda: self.after(0, self.toggle_macro),
            "pause": lambda: self.after(0, self.toggle_pause),
            "emergency_stop": lambda: self.after(0, self.emergency_stop),
            "capture": lambda: self.after(0, self.capture_screen),
        })
        self.refresh_keybinds()

        log.subscribe(self._on_log)
        log.info(f"Application started (version {VERSION})")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if (self.settings.get("general") or {}).get("check_updates_on_start", True):
            updater.check_async(lambda u: self.after(0, self.offer_update, u))

    # -- layout ----------------------------------------------------------

    def _build_layout(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(14, 4))

        theme.heading(header, "DonutSMP AH Macro", 20).pack(side="left")
        ctk.CTkLabel(header, text=f"  v{VERSION}", font=theme.font(11),
                     text_color=theme.TEXT_MUTED).pack(side="left", pady=(6, 0))

        self.header_status = ctk.CTkLabel(header, text="STOPPED",
                                          font=theme.font(14, "bold"),
                                          text_color=theme.TEXT_MUTED)
        self.header_status.pack(side="right")
        ctk.CTkLabel(header, text="Status  ", font=theme.font(12),
                     text_color=theme.TEXT_MUTED).pack(side="right")

        self.tabview = ctk.CTkTabview(
            self, fg_color=theme.PANEL, segmented_button_fg_color=theme.PANEL_LIGHT,
            segmented_button_selected_color=theme.ACCENT,
            segmented_button_selected_hover_color=theme.ACCENT_HOVER,
            corner_radius=10,
        )
        self.tabview.pack(fill="both", expand=True, padx=18, pady=(4, 16))

        for name in TABS:
            self.tabview.add(name)

        self.dashboard = DashboardTab(self.tabview.tab("Dashboard"), self)
        self.ahflip = AHFlipTab(self.tabview.tab("AH Flip"), self)
        self.pixelocr = PixelOCRTab(self.tabview.tab("Pixel / OCR"), self)
        self.keybinds_tab = KeybindsTab(self.tabview.tab("Keybinds"), self)
        self.logs = LogsTab(self.tabview.tab("Logs / Webhook"), self)
        self.settings_tab = SettingsTab(self.tabview.tab("Settings"), self)

        self.tabs = [self.dashboard, self.ahflip, self.pixelocr,
                     self.keybinds_tab, self.logs, self.settings_tab]

    # -- shared helpers for tabs ------------------------------------------

    def save_settings(self):
        """Persist immediately. Called after every edit rather than behind a
        Save button, so a crash or a forced quit can't lose coordinates the
        user just spent time setting."""
        config.save_settings(self.settings)

    def active_item(self):
        return config.active_item(self.settings)

    def notify_settings_changed(self, source=None):
        """Tell every tab to re-read the settings (item renamed, keybind
        changed, ...) so two tabs can't show different values."""
        self.save_settings()
        for tab in self.tabs:
            if tab is not source and hasattr(tab, "refresh"):
                tab.refresh()

    def refresh_keybinds(self):
        self.keybind_manager.settings = self.settings
        self.keybind_manager.apply()

    def capture_screen(self):
        """Grab the screen for the editor. Bound to a hotkey so it can be
        pressed while Minecraft is still in front - the window is only
        raised afterwards, once the screenshot is already taken."""
        self.pixelocr.capture_now()
        self.tabview.set("Pixel / OCR")
        self.lift()
        self.focus_force()

    # -- updates -----------------------------------------------------------

    def offer_update(self, update):
        """Ask before downloading. Never automatic: the update restarts the
        program, and doing that on its own would kill a run mid-batch."""
        window = ctk.CTkToplevel(self)
        window.title("Update available")
        window.geometry("460x300")
        window.configure(fg_color=theme.BG)
        window.transient(self)

        theme.heading(window, f"Version {update.version} is available", 16).pack(
            padx=20, pady=(20, 4), anchor="w")
        ctk.CTkLabel(window, text=f"You have {VERSION}.", font=theme.font(12),
                     text_color=theme.TEXT_MUTED).pack(padx=20, anchor="w")

        notes = ctk.CTkTextbox(window, height=120, fg_color=theme.PANEL_LIGHT,
                               font=theme.font(11))
        notes.pack(fill="x", padx=20, pady=12)
        notes.insert("1.0", update.notes.strip() or "No release notes.")
        notes.configure(state="disabled")

        status = theme.caption(window, "")
        status.pack(padx=20, anchor="w")

        buttons = ctk.CTkFrame(window, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=14)
        theme.subtle_button(buttons, "Not now", window.destroy,
                            width=100).pack(side="right", padx=4)
        install = theme.primary_button(
            buttons, "Update and restart", lambda: None, width=170)
        install.pack(side="right", padx=4)

        def run_update():
            install.configure(state="disabled")
            status.configure(text="Downloading...")

            def say(text):
                self.after(0, lambda: status.configure(text=text))

            def worker():
                try:
                    path = updater.download(
                        update,
                        on_progress=lambda f: say(f"Downloading... {int(f * 100)}%"))
                except Exception as e:
                    say(f"Download failed: {e}")
                    self.after(0, lambda: install.configure(state="normal"))
                    log.error(f"Update download failed: {e}")
                    return
                self.after(0, finish, path)

            threading.Thread(target=worker, daemon=True).start()

        def finish(path):
            self.running = False
            if updater.apply_and_restart(path):
                self.save_settings()
                self.destroy()
            else:
                status.configure(text=f"Downloaded to {path} - "
                                      f"running from source, so swap it yourself.")
                install.configure(state="normal")

        install.configure(command=run_update)

    # -- macro control -----------------------------------------------------

    def start_macro(self):
        if self.running:
            return
        item = self.active_item()
        if item is None:
            log.error("No item configured - add one in the AH Flip tab first")
            return

        self.save_settings()
        self.running = True
        self.paused = False
        self._set_state("STARTING")

        self.macro_thread = threading.Thread(
            target=engine.run,
            args=(self.settings, self.is_running),
            kwargs={
                "is_paused": self.is_paused,
                "on_state": self._on_state,
                "on_stats": self._on_stats,
                "on_error": self._on_error,
            },
            daemon=True,
        )
        self.macro_thread.start()

    def stop_macro(self):
        if not self.running:
            return
        self.running = False
        self.paused = False
        log.info("Stop requested")
        self._set_state("STOPPED")

    def toggle_macro(self):
        self.stop_macro() if self.running else self.start_macro()

    def toggle_pause(self):
        if not self.running:
            return
        self.paused = not self.paused
        log.info("Paused" if self.paused else "Resumed")
        self._set_state("PAUSED" if self.paused else self.macro_state)

    def emergency_stop(self):
        """Hard stop from a hotkey: drops the macro immediately and says so
        on Discord, so an overnight run that had to be killed is visible."""
        if not self.running:
            return
        log.warning("EMERGENCY STOP")
        self.running = False
        self.paused = False
        self._set_state("STOPPED")
        try:
            from webhook import Webhook
            Webhook(self.settings).emergency_stop("Manual emergency stop hotkey")
        except Exception as e:
            log.warning(f"Could not send emergency stop webhook: {e}")

    def is_running(self):
        return self.running

    def is_paused(self):
        return self.paused

    # -- engine callbacks (background thread) ------------------------------

    def _on_state(self, state):
        self.after(0, self._set_state, state)

    def _on_stats(self, stats):
        self.after(0, self._apply_stats, stats)

    def _on_error(self, message):
        self.after(0, self._show_error, message)

    def _on_log(self, entry):
        self.after(0, self.logs.append, entry)

    # -- UI updates (main thread) ------------------------------------------

    def _set_state(self, state):
        if state in ("STOPPED", "ERROR", "ORDER_EMPTY"):
            self.running = False
        self.macro_state = state
        display = "PAUSED" if self.paused and self.running else state
        self.header_status.configure(text=display,
                                     text_color=theme.status_colour(display))
        self.dashboard.set_state(display)

    def _apply_stats(self, stats):
        self.stats = stats
        self.dashboard.set_stats(stats)

    def _show_error(self, message):
        self._set_state("ERROR")
        window = ctk.CTkToplevel(self)
        window.title("Macro Error")
        window.geometry("420x180")
        window.configure(fg_color=theme.BG)
        ctk.CTkLabel(window, text=message, wraplength=380,
                     justify="left").pack(padx=18, pady=18)
        theme.primary_button(window, "OK", window.destroy).pack(pady=6)

    def _on_close(self):
        self.running = False
        self.keybind_manager.clear()
        self.save_settings()
        self.destroy()
