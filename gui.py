"""
gui.py
The main application window. Modern look via customtkinter.
Includes the click-to-set-pixel feature: each pixel location has
a "Set" button; click it, then click the spot in-game, and the
coordinate gets saved automatically.
"""

import threading

import customtkinter as ctk
import keyboard  # global F8 hotkey

import config
import capture
import macro

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("DonutSMP AH Macro [build r6-debug]")
        self.geometry("480x640")
        self.resizable(False, False)

        self.settings = config.load_settings()
        self.running = False
        self.active_listener = None  # holds the pynput listener while capturing

        self._build_layout()
        self._register_hotkey()

    # ------------------------------------------------------------------
    # LAYOUT
    # ------------------------------------------------------------------
    def _build_layout(self):
        pad = {"padx": 12, "pady": 6}

        ctk.CTkLabel(self, text="DonutSMP AH Macro",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(15, 10))

        # ---- Basic settings frame ----
        settings_frame = ctk.CTkFrame(self)
        settings_frame.pack(fill="x", padx=15, pady=5)

        ctk.CTkLabel(settings_frame, text="Sell Price:").grid(row=0, column=0, sticky="w", **pad)
        self.sell_price_var = ctk.StringVar(value=str(self.settings.get("sell_price", "32k")))
        ctk.CTkEntry(settings_frame, textvariable=self.sell_price_var, width=140).grid(
            row=0, column=1, sticky="w", **pad)

        ctk.CTkLabel(settings_frame, text="Undercut Amount:").grid(row=1, column=0, sticky="w", **pad)
        self.undercut_var = ctk.StringVar(value=str(self.settings.get("undercut_amount", 1000)))
        ctk.CTkEntry(settings_frame, textvariable=self.undercut_var, width=140).grid(
            row=1, column=1, sticky="w", **pad)

        self.keep_cycling_var = ctk.BooleanVar(value=self.settings.get("keep_cycling", False))
        ctk.CTkCheckBox(settings_frame, text="Keep Cycling", variable=self.keep_cycling_var).grid(
            row=2, column=0, columnspan=2, sticky="w", **pad)

        self.order_full_var = ctk.BooleanVar(value=self.settings.get("order_full", True))
        ctk.CTkCheckBox(settings_frame, text="Order Full", variable=self.order_full_var).grid(
            row=3, column=0, columnspan=2, sticky="w", **pad)

        self.use_ocr_var = ctk.BooleanVar(value=self.settings.get("use_ocr_undercut", False))
        ctk.CTkCheckBox(settings_frame, text="Auto-Undercut via OCR",
                         variable=self.use_ocr_var,
                         command=self._toggle_undercut_fields).grid(
            row=4, column=0, columnspan=2, sticky="w", **pad)

        ctk.CTkLabel(settings_frame, text="Undercut Mode:").grid(row=5, column=0, sticky="w", **pad)
        self.undercut_mode_var = ctk.StringVar(value=self.settings.get("undercut_mode", "fixed"))
        self.undercut_mode_menu = ctk.CTkOptionMenu(
            settings_frame, values=["fixed", "percent"], variable=self.undercut_mode_var,
            width=140, command=lambda _: self._toggle_undercut_fields())
        self.undercut_mode_menu.grid(row=5, column=1, sticky="w", **pad)

        ctk.CTkLabel(settings_frame, text="Undercut Amount:").grid(row=6, column=0, sticky="w", **pad)
        self.undercut_amount_var = ctk.StringVar(value=str(self.settings.get("undercut_amount", 1000)))
        self.undercut_amount_entry = ctk.CTkEntry(settings_frame, textvariable=self.undercut_amount_var, width=140)
        self.undercut_amount_entry.grid(row=6, column=1, sticky="w", **pad)

        ctk.CTkLabel(settings_frame, text="Undercut Percent (%):").grid(row=7, column=0, sticky="w", **pad)
        self.undercut_percent_var = ctk.StringVar(value=str(self.settings.get("undercut_percent", 2.0)))
        self.undercut_percent_entry = ctk.CTkEntry(settings_frame, textvariable=self.undercut_percent_var, width=140)
        self.undercut_percent_entry.grid(row=7, column=1, sticky="w", **pad)

        ctk.CTkLabel(settings_frame, text="Min Threshold (wait if under):").grid(row=8, column=0, sticky="w", **pad)
        self.min_price_var = ctk.StringVar(value=str(self.settings.get("min_price", 100)))
        ctk.CTkEntry(settings_frame, textvariable=self.min_price_var, width=140).grid(
            row=8, column=1, sticky="w", **pad)

        ctk.CTkLabel(settings_frame, text="Max Price Cap (0 = no cap):").grid(row=9, column=0, sticky="w", **pad)
        self.max_price_var = ctk.StringVar(value=str(self.settings.get("max_price", 0)))
        ctk.CTkEntry(settings_frame, textvariable=self.max_price_var, width=140).grid(
            row=9, column=1, sticky="w", **pad)

        ctk.CTkButton(settings_frame, text="Save Settings", command=self.save_settings).grid(
            row=10, column=0, columnspan=2, pady=(4, 8))

        # ---- Pixel locations frame (scrollable) ----
        ctk.CTkLabel(self, text="Pixel Locations", font=ctk.CTkFont(size=15, weight="bold")).pack(
            pady=(10, 2))

        pixel_frame = ctk.CTkScrollableFrame(self, height=260)
        pixel_frame.pack(fill="both", expand=True, padx=15, pady=5)

        self.pixel_value_labels = {}

        for pdef in config.PIXEL_DEFINITIONS:
            row = ctk.CTkFrame(pixel_frame, fg_color="transparent")
            row.pack(fill="x", pady=3)

            ctk.CTkLabel(row, text=pdef["label"], width=170, anchor="w").pack(side="left", padx=(0, 5))

            value_text = self._format_pixel_value(pdef["key"])
            value_label = ctk.CTkLabel(row, text=value_text, width=130, anchor="w",
                                        text_color=("gray10", "gray80"))
            value_label.pack(side="left", padx=(0, 5))
            self.pixel_value_labels[pdef["key"]] = value_label

            set_btn = ctk.CTkButton(row, text="Set", width=60,
                                     command=lambda p=pdef: self.start_capture(p))
            set_btn.pack(side="left")

        # ---- Status + controls ----
        self.status_var = ctk.StringVar(value="Status: STOPPED")
        ctk.CTkLabel(self, textvariable=self.status_var,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 5))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=5)

        ctk.CTkButton(btn_frame, text="START", width=100, fg_color="#2fa572",
                      command=self.start_macro).grid(row=0, column=0, padx=8)
        ctk.CTkButton(btn_frame, text="STOP", width=100, fg_color="#c0392b",
                      command=self.stop_macro).grid(row=0, column=1, padx=8)

        ctk.CTkLabel(self, text="F8 = Start / Stop", text_color="gray").pack(pady=(4, 10))

        self._toggle_undercut_fields()

    def _toggle_undercut_fields(self):
        """Greys out the amount/percent field that isn't relevant to the current mode."""
        mode = self.undercut_mode_var.get()
        if mode == "percent":
            self.undercut_percent_entry.configure(state="normal")
            self.undercut_amount_entry.configure(state="disabled")
        else:
            self.undercut_amount_entry.configure(state="normal")
            self.undercut_percent_entry.configure(state="disabled")

    # ------------------------------------------------------------------
    # PIXEL CAPTURE
    # ------------------------------------------------------------------
    def _format_pixel_value(self, key):
        value = config.get_pixel(self.settings, key)
        if value is None:
            return "Not Set"
        if len(value) == 2:
            return f"({value[0]}, {value[1]})"
        return f"({value[0]},{value[1]}) - ({value[2]},{value[3]})"

    def start_capture(self, pdef):
        # Prevent starting a second capture while one is already active
        if self.active_listener is not None:
            return

        self.status_var.set(f"Status: Setting '{pdef['label']}'...")
        # Give the user a moment to click into the game window
        self.withdraw()  # hide the GUI so it doesn't block the click target

        def on_status(msg):
            pass  # window is hidden during capture; status not visible anyway

        def finish_point(x, y):
            self._save_pixel(pdef["key"], [x, y])

        def finish_region(x1, y1, x2, y2):
            self._save_pixel(pdef["key"], [x1, y1, x2, y2])

        if pdef["type"] == "region":
            self.active_listener = capture.capture_region(
                lambda x1, y1, x2, y2: self.after(0, finish_region, x1, y1, x2, y2),
                on_status=on_status)
        else:
            self.active_listener = capture.capture_point(
                lambda x, y: self.after(0, finish_point, x, y),
                on_status=on_status)

    def _save_pixel(self, key, value):
        config.set_pixel(self.settings, key, value)
        self.active_listener = None
        self.deiconify()  # show the GUI again
        self.pixel_value_labels[key].configure(text=self._format_pixel_value(key))
        self.status_var.set("Status: STOPPED" if not self.running else "Status: RUNNING")

    # ------------------------------------------------------------------
    # SETTINGS
    # ------------------------------------------------------------------
    def save_settings(self):
        self.settings["sell_price"] = self.sell_price_var.get()
        self.settings["keep_cycling"] = bool(self.keep_cycling_var.get())
        self.settings["order_full"] = bool(self.order_full_var.get())
        self.settings["use_ocr_undercut"] = bool(self.use_ocr_var.get())
        self.settings["undercut_mode"] = self.undercut_mode_var.get()
        self.settings["undercut_amount"] = self._safe_int(self.undercut_amount_var.get(), 1000)
        self.settings["undercut_percent"] = self._safe_float(self.undercut_percent_var.get(), 2.0)
        self.settings["min_price"] = self._safe_int(self.min_price_var.get(), 100)
        self.settings["max_price"] = self._safe_int(self.max_price_var.get(), 0)
        config.save_settings(self.settings)
        self.status_var.set("Settings Saved")
        self.after(1000, lambda: self.status_var.set(
            "Status: RUNNING" if self.running else "Status: STOPPED"))

    @staticmethod
    def _safe_int(value, fallback):
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _safe_float(value, fallback):
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    # ------------------------------------------------------------------
    # MACRO START/STOP
    # ------------------------------------------------------------------
    def start_macro(self):
        if self.running:
            return

        # Basic sanity checks before launching
        if not self.settings.get("sell_price") and not self.use_ocr_var.get():
            self.status_var.set("Error: Set a sell price or enable OCR undercut")
            return

        self.save_settings()
        self.running = True
        self.status_var.set("Status: RUNNING")

        self.macro_thread = threading.Thread(
            target=macro.run,
            args=(self.settings, self.is_running),
            kwargs={"on_status": self._thread_safe_status, "on_error": self._thread_safe_error},
            daemon=True,
        )
        self.macro_thread.start()

    def stop_macro(self):
        self.running = False
        self.status_var.set("Status: STOPPED")

    def _thread_safe_status(self, text):
        # macro.run() runs in a background thread; Tk widgets must only
        # be touched from the main thread, so hop back via .after()
        self.after(0, lambda: self.status_var.set(text))

    def _thread_safe_error(self, message):
        def show():
            self.status_var.set("Status: ERROR")
            self.running = False
            error_win = ctk.CTkToplevel(self)
            error_win.title("Macro Error")
            error_win.geometry("360x140")
            ctk.CTkLabel(error_win, text=message, wraplength=320).pack(padx=15, pady=15)
            ctk.CTkButton(error_win, text="OK", command=error_win.destroy).pack(pady=5)
        self.after(0, show)

    def toggle_macro(self):
        if self.running:
            self.stop_macro()
        else:
            self.start_macro()

    def is_running(self):
        return self.running

    # ------------------------------------------------------------------
    # HOTKEY
    # ------------------------------------------------------------------
    def _register_hotkey(self):
        keyboard.add_hotkey("F8", lambda: self.after(0, self.toggle_macro))


if __name__ == "__main__":
    app = App()
    app.mainloop()
