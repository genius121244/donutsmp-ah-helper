"""
ui/tab_logs.py
The live log on the left, Discord settings on the right.

Log lines are colour-coded by level so a warning or error stands out in a
long overnight run without having to read every line.
"""

import os
import time

import customtkinter as ctk

import applog
import config
from applog import log
from ui import theme
from webhook import Webhook


class LogsTab:
    def __init__(self, parent, app):
        self.app = app
        self.parent = parent
        self.event_vars = {}
        self._build()
        self.refresh()

    def _build(self):
        container = ctk.CTkFrame(self.parent, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=14, pady=14)

        # -- logs -----------------------------------------------------------
        left = theme.card(container)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        header = ctk.CTkFrame(left, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(14, 4))
        theme.heading(header, "Live log", 15).pack(side="left")
        theme.subtle_button(header, "Clear", self.clear, width=70).pack(side="right", padx=3)
        theme.subtle_button(header, "Export", self.export, width=70).pack(side="right", padx=3)

        self.text = ctk.CTkTextbox(left, fg_color="#141518", font=("Courier", 11),
                                   wrap="none")
        self.text.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        for level, colour in theme.LEVEL_COLOURS.items():
            self.text.tag_config(level, foreground=colour)
        self.text.configure(state="disabled")

        # -- webhook --------------------------------------------------------
        right = theme.card(container, width=330)
        right.pack(side="left", fill="y")
        right.pack_propagate(False)

        theme.heading(right, "Discord webhook", 15).pack(anchor="w", padx=14, pady=(14, 2))
        theme.caption(right, "Create one in Server Settings > Integrations > "
                             "Webhooks, then paste the URL here.").pack(
            anchor="w", padx=14)

        self.url_var = ctk.StringVar()
        ctk.CTkEntry(right, textvariable=self.url_var,
                     placeholder_text="https://discord.com/api/webhooks/...").pack(
            fill="x", padx=14, pady=8)
        self.url_var.trace_add("write", lambda *_: self._save_url())

        self.enabled_var = ctk.BooleanVar()
        ctk.CTkSwitch(right, text="Send notifications", variable=self.enabled_var,
                      command=self._save_enabled).pack(anchor="w", padx=14, pady=4)

        row = ctk.CTkFrame(right, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=4)
        theme.primary_button(row, "Send test message", self.test_webhook).pack(side="left")
        self.webhook_status = ctk.CTkLabel(row, text="", font=theme.font(11),
                                           text_color=theme.TEXT_MUTED)
        self.webhook_status.pack(side="left", padx=8)

        ctk.CTkLabel(right, text="EVENTS", font=theme.font(10, "bold"),
                     text_color=theme.TEXT_MUTED, anchor="w").pack(
            fill="x", padx=14, pady=(12, 2))
        for event in config.WEBHOOK_EVENTS:
            var = ctk.BooleanVar()
            ctk.CTkCheckBox(right, text=event["label"], variable=var,
                            font=theme.font(12), checkbox_width=18, checkbox_height=18,
                            command=lambda k=event["key"], v=var: self._save_event(k, v)).pack(
                anchor="w", padx=16, pady=3)
            self.event_vars[event["key"]] = var

        interval_row = ctk.CTkFrame(right, fg_color="transparent")
        interval_row.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(interval_row, text="Summary every (minutes)",
                     font=theme.font(12)).pack(side="left")
        self.interval_var = ctk.StringVar()
        ctk.CTkEntry(interval_row, textvariable=self.interval_var, width=70).pack(side="right")
        self.interval_var.trace_add("write", lambda *_: self._save_interval())

        theme.caption(right,
                      "Per-batch messages are deliberately not sent - an "
                      "overnight run would be hundreds of pings. Set 0 to turn "
                      "summaries off entirely.").pack(anchor="w", padx=14, pady=(0, 14))

    # -- log view --------------------------------------------------------

    def append(self, entry):
        self.text.configure(state="normal")
        at_bottom = self.text.yview()[1] > 0.999
        self.text.insert("end", entry.format() + "\n", entry.level)
        if at_bottom:
            # Only follow when already at the bottom, so scrolling back to
            # read something isn't yanked away by the next line.
            self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self):
        applog.log.clear()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def export(self):
        path = os.path.join(
            os.path.dirname(config.CONFIG_PATH),
            f"log-{time.strftime('%Y%m%d-%H%M%S')}.txt")
        applog.log.export(path)
        log.success(f"Log exported to {path}")

    # -- webhook settings ------------------------------------------------

    def _webhook(self):
        return self.app.settings.setdefault("webhook", {})

    def _save_url(self):
        self._webhook()["url"] = self.url_var.get().strip()
        self.app.save_settings()

    def _save_enabled(self):
        self._webhook()["enabled"] = bool(self.enabled_var.get())
        self.app.save_settings()

    def _save_event(self, key, var):
        self._webhook().setdefault("events", {})[key] = bool(var.get())
        self.app.save_settings()

    def _save_interval(self):
        try:
            self._webhook()["summary_interval_minutes"] = max(
                0, int(self.interval_var.get() or 0))
        except ValueError:
            return
        self.app.save_settings()

    def test_webhook(self):
        self.webhook_status.configure(text="Sending...", text_color=theme.TEXT_MUTED)

        def run():
            ok = Webhook(self.app.settings).test()
            self.parent.after(0, lambda: self.webhook_status.configure(
                text="Delivered" if ok else "Failed - check the URL",
                text_color=theme.GREEN if ok else theme.RED))

        import threading
        threading.Thread(target=run, daemon=True).start()

    def refresh(self):
        webhook = self._webhook()
        self.url_var.set(webhook.get("url", ""))
        self.enabled_var.set(bool(webhook.get("enabled", False)))
        self.interval_var.set(str(webhook.get("summary_interval_minutes", 60)))
        events = webhook.get("events", {})
        for key, var in self.event_vars.items():
            var.set(bool(events.get(key, True)))
