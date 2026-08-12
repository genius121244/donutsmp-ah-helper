"""
webhook.py
Discord notifications.

Deliberately quiet: per-batch messages would be hundreds of pings on an
overnight run, so batches only ever show up inside the periodic summary
(default hourly). The events worth waking up for - the order running out,
a detection failure, an emergency stop - are sent immediately.

Uses urllib from the standard library, so no extra dependency, and every
send is best-effort: Discord being down or the URL being wrong must never
take the macro down with it.
"""

import json
import threading
import time
import urllib.error
import urllib.request

from applog import log

COLOURS = {
    "info": 0x5865F2,
    "success": 0x2FA572,
    "warning": 0xE0A800,
    "error": 0xC0392B,
}

_TIMEOUT = 10


def _post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": "DonutAHMacro"},
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        return response.status


def build_embed(title, fields, colour="info", description=None, footer=None):
    """A Discord embed payload. Fields are (name, value) pairs; empty values
    are dropped so an unknown balance doesn't show as a blank row."""
    embed = {
        "title": title,
        "color": COLOURS.get(colour, COLOURS["info"]),
        "fields": [
            {"name": str(name), "value": str(value), "inline": True}
            for name, value in fields
            if value not in (None, "")
        ],
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
    }
    if description:
        embed["description"] = description
    if footer:
        embed["footer"] = {"text": footer}
    return {"embeds": [embed]}


def format_duration(seconds):
    seconds = int(max(0, seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


class Webhook:
    """Sends events for one session, honouring the user's toggles."""

    def __init__(self, settings):
        self.settings = settings

    @property
    def _config(self):
        return self.settings.get("webhook", {}) or {}

    @property
    def url(self):
        return (self._config.get("url") or "").strip()

    @property
    def enabled(self):
        return bool(self._config.get("enabled")) and self.url.startswith("http")

    def event_enabled(self, event):
        return bool((self._config.get("events") or {}).get(event, True))

    def summary_interval_seconds(self):
        """0 disables periodic summaries."""
        return max(0, int(self._config.get("summary_interval_minutes", 60) or 0)) * 60

    def send(self, event, payload, blocking=False):
        """Fire and forget unless `blocking` (used by the Test button, which
        wants to report the actual result). Returns True if it was sent."""
        if not self.enabled or not self.event_enabled(event):
            return False
        if blocking:
            return self._send_now(payload)
        threading.Thread(target=self._send_now, args=(payload,), daemon=True).start()
        return True

    def _send_now(self, payload):
        try:
            _post(self.url, payload)
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as e:
            log.warning(f"Discord webhook failed: {e}")
            return False

    # -- concrete events -------------------------------------------------

    def macro_started(self, item_name, batch_size):
        return self.send("macro_started", build_embed(
            "Macro started",
            [("Item", item_name), ("Batch size", batch_size)],
            colour="success",
        ))

    def macro_stopped(self, reason, stats=None):
        fields = [("Reason", reason)]
        if stats:
            fields += stats.summary_fields()
        return self.send("macro_stopped", build_embed(
            "Macro stopped", fields, colour="info"))

    def emergency_stop(self, reason):
        return self.send("emergency_stop", build_embed(
            "Emergency stop", [("Reason", reason)], colour="error"))

    def detection_error(self, message):
        return self.send("detection_error", build_embed(
            "Detection error", [("Detail", message)], colour="error"))

    def unexpected_state(self, message):
        return self.send("unexpected_state", build_embed(
            "Unexpected state - macro stopped safely",
            [("Detail", message)], colour="error"))

    def order_emptied(self, stats):
        return self.send("order_emptied", build_embed(
            "Order completed",
            [("Item", stats.item_name),
             ("Items sold", stats.items_sold),
             ("Batches", stats.batches),
             ("Runtime", format_duration(stats.runtime())),
             ("Money", stats.money_string()),
             ("Revenue", stats.revenue_string())],
            colour="success",
            description="The order is empty - macro stopped.",
        ))

    def session_summary(self, stats):
        return self.send("session_summary", build_embed(
            "Session summary", stats.summary_fields(), colour="info",
            footer="Periodic summary"))

    def test(self):
        """Ignores the per-event toggles; the Test button should always try."""
        if not self.url.startswith("http"):
            return False
        return self._send_now(build_embed(
            "Test message",
            [("Status", "Webhook is working")],
            colour="success",
            description="Sent from the DonutSMP AH macro.",
        ))
