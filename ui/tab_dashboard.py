"""
ui/tab_dashboard.py
What the macro is doing right now, at a glance, plus start/pause/stop.

Everything shown here comes from SessionStats, which the engine pushes on
every state change - so the panel can't drift out of sync with what the
macro actually believes.
"""

import customtkinter as ctk

import stats as stats_module
from ui import theme
from webhook import format_duration


class DashboardTab:
    def __init__(self, parent, app):
        self.app = app
        self.parent = parent
        self._value_labels = {}
        self._build()
        self._tick()

    def _build(self):
        status_card = theme.card(self.parent)
        status_card.pack(fill="x", padx=14, pady=(14, 8))

        row = ctk.CTkFrame(status_card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=14)

        self.state_dot = ctk.CTkLabel(row, text="●", font=theme.font(26),
                                      text_color=theme.TEXT_MUTED)
        self.state_dot.pack(side="left", padx=(0, 10))

        text_column = ctk.CTkFrame(row, fg_color="transparent")
        text_column.pack(side="left", fill="x", expand=True)
        self.state_label = ctk.CTkLabel(text_column, text="STOPPED",
                                        font=theme.font(20, "bold"), anchor="w")
        self.state_label.pack(fill="x")
        self.phase_label = ctk.CTkLabel(text_column, text="Idle", anchor="w",
                                        font=theme.font(12),
                                        text_color=theme.TEXT_MUTED)
        self.phase_label.pack(fill="x")

        buttons = ctk.CTkFrame(row, fg_color="transparent")
        buttons.pack(side="right")
        ctk.CTkButton(buttons, text="START", width=96, fg_color=theme.GREEN,
                      hover_color=theme.GREEN_HOVER,
                      command=self.app.start_macro).pack(side="left", padx=4)
        self.pause_button = theme.subtle_button(buttons, "PAUSE", self.app.toggle_pause,
                                                width=96)
        self.pause_button.pack(side="left", padx=4)
        ctk.CTkButton(buttons, text="STOP", width=96, fg_color=theme.RED,
                      hover_color=theme.RED_HOVER,
                      command=self.app.stop_macro).pack(side="left", padx=4)

        grid_card = theme.card(self.parent)
        grid_card.pack(fill="both", expand=True, padx=14, pady=8)

        fields = [
            ("item", "Current item"), ("phase", "Current phase"),
            ("market", "Market price"), ("listing", "Listing price"),
            ("money", "Money"), ("revenue", "Session revenue"),
            ("order", "Order status"), ("batches", "Batches processed"),
            ("items", "Items sold"), ("runtime", "Session runtime"),
        ]
        for index, (key, label) in enumerate(fields):
            column, line = index % 2, index // 2
            cell = ctk.CTkFrame(grid_card, fg_color="transparent")
            cell.grid(row=line, column=column, sticky="ew", padx=18, pady=9)
            grid_card.grid_columnconfigure(column, weight=1)
            ctk.CTkLabel(cell, text=label.upper(), font=theme.font(10, "bold"),
                         text_color=theme.TEXT_MUTED, anchor="w").pack(fill="x")
            value = ctk.CTkLabel(cell, text="-", font=theme.font(16), anchor="w")
            value.pack(fill="x")
            self._value_labels[key] = value

        theme.caption(
            grid_card,
            "Revenue is money received during selling (balance after - balance "
            "before), not profit: the macro never sees what the order cost you.",
        ).grid(row=99, column=0, columnspan=2, sticky="w", padx=18, pady=(4, 14))

    # -- updates ---------------------------------------------------------

    def set_state(self, state):
        self.state_label.configure(text=state, text_color=theme.status_colour(state))
        self.state_dot.configure(text_color=theme.status_colour(state))
        self.pause_button.configure(text="RESUME" if state == "PAUSED" else "PAUSE")
        self._value_labels["phase"].configure(text=state.replace("_", " ").title())

    def set_stats(self, stats):
        self._value_labels["item"].configure(text=stats.item_name or "-")
        self._value_labels["market"].configure(
            text=stats_module.format_money(stats.market_price) or "-")
        self._value_labels["listing"].configure(
            text=stats_module.format_money(stats.listing_price) or "-")
        self._value_labels["money"].configure(text=stats.money_string() or "-")
        self._value_labels["revenue"].configure(text=stats.revenue_string() or "-")
        self._value_labels["order"].configure(text=stats.order_state)
        self._value_labels["batches"].configure(text=str(stats.batches))
        self._value_labels["items"].configure(text=str(stats.items_sold))

    def refresh(self):
        item = self.app.active_item()
        self._value_labels["item"].configure(text=item.get("name") if item else "-")

    def _tick(self):
        """Runtime is the one value that changes without the engine doing
        anything, so it ticks on its own."""
        stats = self.app.stats
        if stats is not None:
            self._value_labels["runtime"].configure(
                text=format_duration(stats.runtime()))
        self.parent.after(1000, self._tick)
