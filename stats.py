"""
stats.py
Running totals for one session, shared by the Dashboard and the Discord
summaries so both always show the same numbers.

Revenue is deliberately called revenue, not profit: it's the balance read
at the end of a selling phase minus the balance read at the start, which
is money received. Turning that into profit needs what the order cost to
buy, and the macro never sees that, so it isn't claimed.
"""

import threading
import time


def format_money(value):
    return f"${value:,}" if value is not None else None


class SessionStats:
    def __init__(self, item_name=""):
        self._lock = threading.Lock()
        self.item_name = item_name
        self.started_at = time.time()
        self.batches = 0
        self.items_sold = 0
        self.money_start = None      # first balance read this session
        self.money_current = None
        self.market_price = None
        self.listing_price = None
        self.order_state = "unknown"
        self.phase = "IDLE"

    def runtime(self):
        return time.time() - self.started_at

    def record_batch(self, items):
        with self._lock:
            self.batches += 1
            self.items_sold += items

    def record_money(self, value):
        if value is None:
            return
        with self._lock:
            if self.money_start is None:
                self.money_start = value
            self.money_current = value

    def revenue(self):
        if self.money_start is None or self.money_current is None:
            return None
        return self.money_current - self.money_start

    def money_string(self):
        return format_money(self.money_current)

    def revenue_string(self):
        revenue = self.revenue()
        return format_money(revenue) if revenue is not None else None

    def summary_fields(self):
        from webhook import format_duration  # local import: avoids a cycle
        return [
            ("Item", self.item_name),
            ("Runtime", format_duration(self.runtime())),
            ("Batches", self.batches),
            ("Items sold", self.items_sold),
            ("Money", self.money_string()),
            ("Revenue", self.revenue_string()),
            ("Market price", format_money(self.market_price)),
            ("Listing price", format_money(self.listing_price)),
            ("Order", self.order_state),
        ]
