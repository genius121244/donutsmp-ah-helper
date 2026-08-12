"""
ui/tab_keybinds.py
Click a field, press anything, that becomes the binding.

Any key or mouse button works - the binding is whatever was physically
pressed, so there's no dropdown of "supported" keys to be missing from.
Duplicates are flagged rather than silently accepted, because two actions
on one key means one of them never fires.
"""

import customtkinter as ctk

import keybinds
from applog import log
from ui import theme


class KeybindsTab:
    def __init__(self, parent, app):
        self.app = app
        self.parent = parent
        self.capture = None
        self.buttons = {}
        self._build()
        self.refresh()

    def _build(self):
        card = theme.card(self.parent)
        card.pack(fill="both", expand=True, padx=14, pady=14)

        theme.heading(card, "Keybinds", 16).pack(anchor="w", padx=16, pady=(16, 2))
        theme.caption(card,
                      "Click a binding, then press a key or mouse button. "
                      "Esc clears it. Left click can't be bound - it's needed "
                      "to work the interface.").pack(anchor="w", padx=16)

        import config
        for definition in config.KEYBIND_DEFINITIONS:
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=6)

            ctk.CTkLabel(row, text=definition["label"], width=220, anchor="w",
                         font=theme.font(13)).pack(side="left")

            button = theme.subtle_button(
                row, "-", width=170,
                command=lambda k=definition["key"]: self.start_capture(k))
            button.pack(side="left")
            self.buttons[definition["key"]] = button

            theme.subtle_button(
                row, "Clear", width=70,
                command=lambda k=definition["key"]: self.clear(k)).pack(side="left", padx=8)

        self.conflict_label = ctk.CTkLabel(card, text="", text_color=theme.YELLOW,
                                           font=theme.font(12), anchor="w")
        self.conflict_label.pack(fill="x", padx=16, pady=(12, 16))

    # -- actions ---------------------------------------------------------

    def start_capture(self, action):
        if self.capture is not None:
            self.capture.stop()
        self.buttons[action].configure(text="Press a key or mouse button...",
                                       fg_color=theme.ACCENT)

        def captured(binding):
            # Fires from the listener thread; hop back before touching Tk.
            self.parent.after(0, self._apply_binding, action, binding)

        self.capture = keybinds.BindingCapture(captured)
        self.capture.start()

    def _apply_binding(self, action, binding):
        self.capture = None
        self.app.settings.setdefault("keybinds", {})[action] = binding
        self.app.save_settings()
        self.app.refresh_keybinds()
        log.info(f"Keybind '{action}' set to {keybinds.describe(binding)}")
        self.refresh()

    def clear(self, action):
        self.app.settings.setdefault("keybinds", {})[action] = None
        self.app.save_settings()
        self.app.refresh_keybinds()
        self.refresh()

    def refresh(self):
        bindings = self.app.settings.get("keybinds", {})
        clashing = keybinds.conflicts(bindings)

        for action, button in self.buttons.items():
            binding = bindings.get(action)
            in_conflict = binding in clashing
            button.configure(
                text=keybinds.describe(binding),
                fg_color=theme.YELLOW if in_conflict else theme.PANEL_LIGHT,
                text_color="#1e1f22" if in_conflict else theme.TEXT,
            )

        if clashing:
            described = "; ".join(
                f"{keybinds.describe(binding)} -> {', '.join(actions)}"
                for binding, actions in clashing.items())
            self.conflict_label.configure(
                text=f"Conflict: {described}. Only one of them will fire.")
        else:
            self.conflict_label.configure(text="")
