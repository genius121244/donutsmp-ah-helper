"""
ui/tab_ahflip.py
Item configurations: the list on the left, the selected item's flip
settings on the right.

Nothing here knows about rockets. An item is a name plus its batch size,
undercut rule and price limits, so a second item is a copy with different
numbers rather than a code change.
"""

import customtkinter as ctk

import config
from applog import log
from ui import theme


class AHFlipTab:
    def __init__(self, parent, app):
        self.app = app
        self.parent = parent
        self.selected_name = None
        self._fields = {}
        self._build()
        self.refresh()

    def _build(self):
        container = ctk.CTkFrame(self.parent, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=14, pady=14)

        # -- left: item list ------------------------------------------------
        left = theme.card(container, width=250)
        left.pack(side="left", fill="y", padx=(0, 12))
        left.pack_propagate(False)

        theme.heading(left, "Items", 15).pack(anchor="w", padx=14, pady=(14, 6))
        self.item_list = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.item_list.pack(fill="both", expand=True, padx=8)
        theme.enable_mousewheel_scroll(self.item_list)

        buttons = ctk.CTkFrame(left, fg_color="transparent")
        buttons.pack(fill="x", padx=10, pady=10)
        theme.primary_button(buttons, "New", self.create_item, width=70).pack(side="left", padx=2)
        theme.subtle_button(buttons, "Duplicate", self.duplicate_item, width=90).pack(side="left", padx=2)
        ctk.CTkButton(buttons, text="Delete", width=70, fg_color=theme.RED,
                      hover_color=theme.RED_HOVER,
                      command=self.delete_item).pack(side="left", padx=2)

        # -- right: selected item -------------------------------------------
        right = theme.card(container)
        right.pack(side="left", fill="both", expand=True)

        header = ctk.CTkFrame(right, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(14, 4))
        self.title_label = theme.heading(header, "No item selected", 16)
        self.title_label.pack(side="left")
        self.active_badge = ctk.CTkLabel(header, text="", font=theme.font(11, "bold"),
                                         text_color=theme.GREEN)
        self.active_badge.pack(side="right")

        self.form = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.form.pack(fill="both", expand=True, padx=8, pady=(0, 10))
        theme.enable_mousewheel_scroll(self.form)

        self._add_entry("name", "Item name",
                        "Just a label for you - it doesn't have to match the "
                        "in-game item name.")
        self._add_entry("batch_size", "Batch size (1-9)",
                        "How many hotbar slots to fill before selling.")
        self._add_switch("enabled", "Enabled")
        self._add_switch("use_ocr_undercut", "Undercut using the price read from /shop")
        self._add_option("undercut_mode", "Undercut mode", ["fixed", "percent"])
        self._add_entry("undercut_amount", "Undercut amount",
                        "Used in fixed mode: listing = market price - this.")
        self._add_entry("undercut_percent", "Undercut percent",
                        "Used in percent mode.")
        self._add_entry("min_price", "Minimum price (floor)",
                        "Never list below this. If undercutting would go under "
                        "it, the macro waits for the market to move instead.")
        self._add_entry("max_price", "Maximum price (cap, 0 = none)",
                        "If undercutting would land above this, list at the cap.")
        self._add_entry("sell_price", "Fallback fixed price",
                        "Used when undercutting is off, or when the market "
                        "price can't be read.")

        theme.primary_button(self.form, "Set as active item",
                             self.set_active).pack(anchor="w", padx=8, pady=(12, 4))
        theme.caption(self.form,
                      "Pixel positions and OCR boxes are shared between items "
                      "by default. Per-item overrides can be set in the "
                      "Pixel / OCR tab.").pack(anchor="w", padx=8, pady=(0, 10))

    # -- form builders ---------------------------------------------------

    def _row(self, label, help_text=None):
        frame = ctk.CTkFrame(self.form, fg_color="transparent")
        frame.pack(fill="x", padx=8, pady=(8, 0))
        ctk.CTkLabel(frame, text=label, width=250, anchor="w",
                     font=theme.font(12)).pack(side="left")
        if help_text:
            theme.caption(self.form, help_text).pack(anchor="w", padx=8)
        return frame

    def _add_entry(self, key, label, help_text=None):
        frame = self._row(label, help_text)
        var = ctk.StringVar()
        entry = ctk.CTkEntry(frame, textvariable=var, width=170)
        entry.pack(side="left")
        var.trace_add("write", lambda *_: self._on_change(key, var.get()))
        self._fields[key] = var

    def _add_switch(self, key, label):
        frame = self._row(label)
        var = ctk.BooleanVar()
        ctk.CTkSwitch(frame, text="", variable=var,
                      command=lambda: self._on_change(key, var.get())).pack(side="left")
        self._fields[key] = var

    def _add_option(self, key, label, values):
        frame = self._row(label)
        var = ctk.StringVar()
        ctk.CTkOptionMenu(frame, values=values, variable=var, width=170,
                          command=lambda _: self._on_change(key, var.get())).pack(side="left")
        self._fields[key] = var

    # -- data ------------------------------------------------------------

    def _item(self):
        for item in self.app.settings.get("items", []):
            if item.get("name") == self.selected_name:
                return item
        return None

    def _on_change(self, key, value):
        item = self._item()
        if item is None or self._loading:
            return

        if key == "name":
            value = str(value).strip()
            if not value or value == item["name"]:
                return
            was_active = self.app.settings.get("active_item") == item["name"]
            item["name"] = value
            self.selected_name = value
            if was_active:
                self.app.settings["active_item"] = value
        elif key in ("batch_size", "undercut_amount", "min_price", "max_price"):
            try:
                item[key] = max(0, int(str(value).strip() or 0))
            except ValueError:
                return  # mid-typing; keep the last good value
            if key == "batch_size":
                item[key] = max(1, min(9, item[key]))
        elif key == "undercut_percent":
            try:
                item[key] = float(str(value).strip() or 0)
            except ValueError:
                return
        elif key in ("enabled", "use_ocr_undercut"):
            item[key] = bool(value)
        else:
            item[key] = value

        self.app.save_settings()
        self._refresh_list()

    def create_item(self):
        item = config.add_item(self.app.settings)
        if len(self.app.settings["items"]) == 1:
            self.app.settings["active_item"] = item["name"]
        self.selected_name = item["name"]
        log.info(f"Created item '{item['name']}'")
        self.app.notify_settings_changed()
        self.refresh()

    def duplicate_item(self):
        source = self._item()
        if source is None:
            return
        item = config.add_item(self.app.settings, source=source)
        self.selected_name = item["name"]
        log.info(f"Duplicated '{source['name']}' as '{item['name']}'")
        self.app.notify_settings_changed()
        self.refresh()

    def delete_item(self):
        item = self._item()
        if item is None:
            return
        config.delete_item(self.app.settings, item["name"])
        log.info(f"Deleted item '{item['name']}'")
        self.selected_name = None
        self.app.notify_settings_changed()
        self.refresh()

    def set_active(self):
        item = self._item()
        if item is None:
            return
        config.set_active_item(self.app.settings, item["name"])
        log.info(f"Active item is now '{item['name']}'")
        self.app.notify_settings_changed()
        self.refresh()

    # -- rendering -------------------------------------------------------

    _loading = False

    def _refresh_list(self):
        for child in self.item_list.winfo_children():
            child.destroy()

        items = self.app.settings.get("items", [])
        active = self.app.settings.get("active_item")

        if not items:
            theme.caption(self.item_list, "No items yet - press New.").pack(pady=10)
            return

        for item in items:
            name = item.get("name", "?")
            selected = name == self.selected_name
            label = f"{name}{'  •' if name == active else ''}"
            button = ctk.CTkButton(
                self.item_list, text=label, anchor="w", height=32,
                fg_color=theme.ACCENT if selected else theme.PANEL_LIGHT,
                hover_color=theme.ACCENT_HOVER if selected else theme.BORDER,
                text_color=theme.TEXT if item.get("enabled", True) else theme.TEXT_MUTED,
                command=lambda n=name: self.select(n),
            )
            button.pack(fill="x", pady=2)

    def select(self, name):
        self.selected_name = name
        self.refresh()

    def refresh(self):
        items = self.app.settings.get("items", [])
        if self.selected_name not in [i.get("name") for i in items]:
            self.selected_name = items[0]["name"] if items else None

        self._refresh_list()
        item = self._item()

        self._loading = True
        try:
            if item is None:
                self.title_label.configure(text="No item selected")
                self.active_badge.configure(text="")
                for var in self._fields.values():
                    var.set("" if isinstance(var, ctk.StringVar) else False)
                return

            self.title_label.configure(text=item.get("name", "?"))
            is_active = self.app.settings.get("active_item") == item.get("name")
            self.active_badge.configure(text="ACTIVE" if is_active else "")

            for key, var in self._fields.items():
                value = item.get(key, "")
                if isinstance(var, ctk.BooleanVar):
                    var.set(bool(value))
                else:
                    var.set(str(value))
        finally:
            self._loading = False
