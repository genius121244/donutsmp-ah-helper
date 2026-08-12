"""
ui/tab_pixelocr.py
Where every coordinate the macro uses gets set, edited with the keyboard.

The old flow was: hide the window, click the spot in-game, hope you hit the
right pixel. That's hard to do accurately on an 8px tooltip and impossible
to nudge afterwards - a miss meant starting over.

Instead: take a screenshot of the game, then move the crosshair or the box
over it with the arrow keys. Arrows step one screen pixel at a time no
matter how the preview is scaled, Shift+Arrows resize a box, Ctrl+Arrows
jump ten pixels. A magnifier shows the pixels around the cursor at 8x, so
the exact pixel is visible while placing it.

Clicking on the preview to jump roughly into position still works, because
it's faster for the first placement - but nothing here needs the mouse.
"""

import os
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageTk

import config
import detect
import ocr
import screen
import slots
from applog import log
from ui import theme

MOVE_STEP = 1
FAST_STEP = 10
MIN_BOX = 4

POINT = "point"
REGION = "region"
HOVER = "hover"


class PixelOCRTab:
    def __init__(self, parent, app):
        self.app = app
        self.parent = parent

        self.shot = None            # full-resolution screenshot (PIL)
        self.shot_photo = None      # scaled PhotoImage, kept to avoid GC
        self.scale = 1.0
        self.offset = (0, 0)

        self.target = None          # (kind, key, label)
        self.value = None           # [x, y] or [x1, y1, x2, y2] being edited

        self._build()
        self.refresh()

    # -- layout ----------------------------------------------------------

    def _build(self):
        container = ctk.CTkFrame(self.parent, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=12, pady=12)

        left = theme.card(container, width=290)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        self._build_target_list(left)

        right = ctk.CTkFrame(container, fg_color="transparent")
        right.pack(side="left", fill="both", expand=True)
        self._build_editor(right)

    def _build_target_list(self, parent):
        theme.heading(parent, "What to set", 15).pack(anchor="w", padx=14, pady=(14, 2))
        theme.caption(parent, "Select something, then position it with the "
                              "arrow keys on the preview.").pack(anchor="w", padx=14)

        self.target_list = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.target_list.pack(fill="both", expand=True, padx=8, pady=8)

        self.per_item_var = ctk.BooleanVar(value=False)
        ctk.CTkSwitch(parent, text="Save for the active item only",
                      variable=self.per_item_var,
                      command=self.refresh).pack(anchor="w", padx=14, pady=(0, 12))

    def _build_editor(self, parent):
        toolbar = theme.card(parent)
        toolbar.pack(fill="x")

        row = ctk.CTkFrame(toolbar, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=10)

        theme.primary_button(row, "Capture screen", self.capture_now,
                             width=130).pack(side="left", padx=(0, 6))
        theme.subtle_button(row, "Capture in 5s", lambda: self.capture_later(5),
                            width=120).pack(side="left", padx=(0, 12))
        theme.caption(row, "Alt-tab into Minecraft during the countdown.").pack(side="left")

        self.coord_label = ctk.CTkLabel(row, text="X - / Y -",
                                        font=theme.font(13, "bold"))
        self.coord_label.pack(side="right")

        body = ctk.CTkFrame(parent, fg_color="transparent")
        body.pack(fill="both", expand=True, pady=(10, 0))

        canvas_card = theme.card(body)
        canvas_card.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Canvas(canvas_card, bg="#141518", highlightthickness=0,
                                cursor="tcross")
        self.canvas.pack(fill="both", expand=True, padx=10, pady=10)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<Configure>", lambda _e: self._draw())
        for key in ("Left", "Right", "Up", "Down"):
            self.canvas.bind(f"<{key}>", self._on_arrow)
            self.canvas.bind(f"<Shift-{key}>", self._on_arrow)
            self.canvas.bind(f"<Control-{key}>", self._on_arrow)
        self.canvas.bind("<Return>", lambda _e: self.save_value())
        self.canvas.bind("<Escape>", lambda _e: self.reset_value())

        side = ctk.CTkFrame(body, fg_color="transparent", width=250)
        side.pack(side="left", fill="y", padx=(10, 0))
        side.pack_propagate(False)
        self._build_side_panel(side)

    def _build_side_panel(self, parent):
        editor = theme.card(parent)
        editor.pack(fill="x")

        self.target_label = theme.heading(editor, "Nothing selected", 14)
        self.target_label.pack(anchor="w", padx=12, pady=(12, 2))
        self.target_help = theme.caption(editor, "")
        self.target_help.pack(anchor="w", padx=12)

        self.size_label = ctk.CTkLabel(editor, text="", font=theme.font(12),
                                       text_color=theme.TEXT_MUTED, anchor="w")
        self.size_label.pack(fill="x", padx=12, pady=(8, 0))

        self.magnifier = tk.Canvas(editor, width=200, height=120, bg="#141518",
                                   highlightthickness=1,
                                   highlightbackground=theme.BORDER)
        self.magnifier.pack(padx=12, pady=10)

        keys = ctk.CTkFrame(editor, fg_color="transparent")
        keys.pack(fill="x", padx=12, pady=(0, 8))
        theme.caption(keys,
                      "Arrows  move 1px\n"
                      "Ctrl + Arrows  move 10px\n"
                      "Shift + Arrows  resize (boxes)\n"
                      "Enter  save     Esc  reset").pack(anchor="w")

        buttons = ctk.CTkFrame(editor, fg_color="transparent")
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        theme.primary_button(buttons, "Save", self.save_value, width=70).pack(side="left", padx=2)
        theme.subtle_button(buttons, "Load", self.load_value, width=70).pack(side="left", padx=2)
        theme.subtle_button(buttons, "Reset", self.reset_value, width=70).pack(side="left", padx=2)

        test = theme.card(parent)
        test.pack(fill="x", pady=10)
        theme.heading(test, "Test", 14).pack(anchor="w", padx=12, pady=(12, 4))
        theme.subtle_button(test, "Test this selection", self.test_target).pack(
            fill="x", padx=12, pady=2)
        theme.subtle_button(test, "Test hotbar slots", lambda: self.test_slots("hotbar")).pack(
            fill="x", padx=12, pady=2)
        theme.subtle_button(test, "Test order slots", lambda: self.test_slots("order")).pack(
            fill="x", padx=12, pady=2)
        self.test_output = ctk.CTkTextbox(test, height=140, fg_color=theme.PANEL_LIGHT,
                                          font=theme.font(11))
        self.test_output.pack(fill="x", padx=12, pady=(6, 12))

        templates = theme.card(parent)
        templates.pack(fill="x")
        theme.heading(templates, "Empty-slot references", 14).pack(
            anchor="w", padx=12, pady=(12, 2))
        theme.caption(templates,
                      "Frame an EMPTY slot with a box above, then save it here. "
                      "Slot detection compares against these.").pack(
            anchor="w", padx=12)
        for definition in config.TEMPLATE_DEFINITIONS:
            row = ctk.CTkFrame(templates, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=4)
            ctk.CTkLabel(row, text=definition["label"], anchor="w",
                         font=theme.font(11)).pack(side="left")
            theme.subtle_button(
                row, "Save box as this", width=110,
                command=lambda d=definition: self.save_template(d["key"])).pack(side="right")
        self.template_status = theme.caption(templates, "")
        self.template_status.pack(anchor="w", padx=12, pady=(2, 12))

    # -- target list -----------------------------------------------------

    def _targets(self):
        groups = [
            ("OCR boxes", [(REGION, d["key"], d["label"], d.get("help", ""))
                           for d in config.REGION_DEFINITIONS if d.get("ocr")]),
            ("OCR hover points", [(HOVER, d["key"], d["label"], d.get("help", ""))
                                  for d in config.HOVER_DEFINITIONS]),
            ("Click points", [(POINT, d["key"], d["label"], d.get("help", ""))
                              for d in config.POINT_DEFINITIONS]),
            ("Slot boxes", [(REGION, d["key"], d["label"], d.get("help", ""))
                            for d in config.REGION_DEFINITIONS if not d.get("ocr")]),
        ]
        return groups

    def _refresh_target_list(self):
        for child in self.target_list.winfo_children():
            child.destroy()

        for group_name, entries in self._targets():
            ctk.CTkLabel(self.target_list, text=group_name.upper(),
                         font=theme.font(10, "bold"), text_color=theme.TEXT_MUTED,
                         anchor="w").pack(fill="x", pady=(10, 2))
            for kind, key, label, help_text in entries:
                current = self._stored_value(kind, key)
                selected = self.target and self.target[:2] == (kind, key)
                text = f"{label}\n{self._format(current)}"
                ctk.CTkButton(
                    self.target_list, text=text, anchor="w", height=42,
                    font=theme.font(11),
                    fg_color=theme.ACCENT if selected else theme.PANEL_LIGHT,
                    hover_color=theme.ACCENT_HOVER if selected else theme.BORDER,
                    command=lambda k=kind, y=key, l=label, h=help_text:
                        self.select_target(k, y, l, h),
                ).pack(fill="x", pady=2)

    @staticmethod
    def _format(value):
        if not value:
            return "not set"
        if len(value) == 2:
            return f"X {value[0]}  Y {value[1]}"
        return (f"X {value[0]}  Y {value[1]}  "
                f"W {value[2] - value[0]}  H {value[3] - value[1]}")

    def _item(self):
        """The item to save into, or None for the shared value."""
        return self.app.active_item() if self.per_item_var.get() else None

    def _stored_value(self, kind, key):
        settings, item = self.app.settings, self._item()
        if kind == POINT:
            return config.get_point(settings, key, item)
        if kind == HOVER:
            return config.get_hover_point(settings, key, item)
        return config.get_region(settings, key, item)

    def select_target(self, kind, key, label, help_text):
        self.target = (kind, key, label, help_text)
        self.target_label.configure(text=label)
        self.target_help.configure(text=help_text)
        self.load_value()
        self._refresh_target_list()
        self.canvas.focus_set()

    # -- screenshot ------------------------------------------------------

    def capture_now(self):
        try:
            self.shot = screen.grab_screen()
        except Exception as e:
            log.error(f"Screen capture failed: {e}")
            return
        log.info(f"Captured screen {self.shot.width}x{self.shot.height}")
        self._draw()

    def capture_later(self, seconds):
        """Countdown capture so the game can be brought to the front first."""
        def tick(remaining):
            if remaining <= 0:
                self.capture_now()
                return
            self.coord_label.configure(text=f"Capturing in {remaining}...")
            self.parent.after(1000, tick, remaining - 1)
        tick(seconds)

    # -- drawing ---------------------------------------------------------

    def _draw(self):
        self.canvas.delete("all")
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())

        if self.shot is None:
            self.canvas.create_text(
                width // 2, height // 2, fill=theme.TEXT_MUTED,
                font=("TkDefaultFont", 13),
                text="Press 'Capture screen' to grab the game window")
            return

        self.scale = min(width / self.shot.width, height / self.shot.height, 1.0)
        view = self.shot.resize(
            (max(1, int(self.shot.width * self.scale)),
             max(1, int(self.shot.height * self.scale))), Image.LANCZOS)
        self.offset = ((width - view.width) // 2, (height - view.height) // 2)
        self.shot_photo = ImageTk.PhotoImage(view)
        self.canvas.create_image(self.offset[0], self.offset[1],
                                 image=self.shot_photo, anchor="nw")

        if self.value:
            self._draw_overlay()
        self._update_readout()

    def _to_canvas(self, x, y):
        return (self.offset[0] + x * self.scale, self.offset[1] + y * self.scale)

    def _to_screen(self, cx, cy):
        return (int((cx - self.offset[0]) / self.scale),
                int((cy - self.offset[1]) / self.scale))

    def _draw_overlay(self):
        if len(self.value) == 2:
            x, y = self._to_canvas(*self.value)
            # A crosshair, not a box: a click target is one pixel, and a
            # box around it would hide which pixel that is.
            self.canvas.create_line(x - 18, y, x + 18, y, fill=theme.ACCENT, width=1)
            self.canvas.create_line(x, y - 18, x, y + 18, fill=theme.ACCENT, width=1)
            self.canvas.create_oval(x - 4, y - 4, x + 4, y + 4, outline=theme.ACCENT)
        else:
            x1, y1 = self._to_canvas(self.value[0], self.value[1])
            x2, y2 = self._to_canvas(self.value[2], self.value[3])
            self.canvas.create_rectangle(x1, y1, x2, y2, outline=theme.ACCENT, width=2)
            for cx, cy in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
                self.canvas.create_rectangle(cx - 3, cy - 3, cx + 3, cy + 3,
                                             outline=theme.ACCENT, fill=theme.ACCENT)

    def _update_readout(self):
        if not self.value:
            self.coord_label.configure(text="X - / Y -")
            self.size_label.configure(text="")
            return
        if len(self.value) == 2:
            x, y = self.value
            self.coord_label.configure(text=f"X {x}   Y {y}")
            self.size_label.configure(text="Single pixel target")
        else:
            x1, y1, x2, y2 = self.value
            self.coord_label.configure(
                text=f"X {x1}   Y {y1}   W {x2 - x1}   H {y2 - y1}")
            self.size_label.configure(text=f"Box  ({x1}, {y1}) -> ({x2}, {y2})")
        self._draw_magnifier()

    def _draw_magnifier(self):
        """The pixels around the target at 8x, so the exact pixel is
        visible without squinting at a scaled-down preview."""
        self.magnifier.delete("all")
        if self.shot is None or not self.value:
            return
        zoom = 8
        width, height = 200 // zoom, 120 // zoom
        cx = self.value[0] if len(self.value) == 2 else (self.value[0] + self.value[2]) // 2
        cy = self.value[1] if len(self.value) == 2 else (self.value[1] + self.value[3]) // 2
        left = max(0, min(self.shot.width - width, cx - width // 2))
        top = max(0, min(self.shot.height - height, cy - height // 2))

        crop = self.shot.crop((left, top, left + width, top + height))
        crop = crop.resize((width * zoom, height * zoom), Image.NEAREST)
        self._magnifier_photo = ImageTk.PhotoImage(crop)
        self.magnifier.create_image(0, 0, image=self._magnifier_photo, anchor="nw")

        mx = (cx - left) * zoom + zoom // 2
        my = (cy - top) * zoom + zoom // 2
        self.magnifier.create_line(mx - 10, my, mx + 10, my, fill=theme.ACCENT)
        self.magnifier.create_line(mx, my - 10, mx, my + 10, fill=theme.ACCENT)

    # -- editing ---------------------------------------------------------

    def _on_arrow(self, event):
        if not self.value:
            return "break"
        dx = {"Left": -1, "Right": 1}.get(event.keysym, 0)
        dy = {"Up": -1, "Down": 1}.get(event.keysym, 0)

        shift = bool(event.state & 0x0001)
        control = bool(event.state & 0x0004)
        step = FAST_STEP if control else MOVE_STEP

        if shift and len(self.value) == 4:
            # Resize from the bottom-right corner, clamped so the box can't
            # invert and end up with a negative width.
            self.value[2] = max(self.value[0] + MIN_BOX, self.value[2] + dx * step)
            self.value[3] = max(self.value[1] + MIN_BOX, self.value[3] + dy * step)
        else:
            self.value[0] += dx * step
            self.value[1] += dy * step
            if len(self.value) == 4:
                self.value[2] += dx * step
                self.value[3] += dy * step

        self._draw()
        return "break"

    def _on_canvas_click(self, event):
        self.canvas.focus_set()
        if self.shot is None or not self.target:
            return
        x, y = self._to_screen(event.x, event.y)
        if self.value and len(self.value) == 4:
            width = self.value[2] - self.value[0]
            height = self.value[3] - self.value[1]
            self.value = [x, y, x + width, y + height]
        else:
            self.value = [x, y]
        self._draw()

    def load_value(self):
        """Pull the saved value back in, or start from a sensible default."""
        if not self.target:
            return
        kind, key = self.target[0], self.target[1]
        stored = self._stored_value(kind, key)
        if stored:
            self.value = list(stored)
        elif kind == REGION:
            self.value = [100, 100, 220, 130]
        else:
            self.value = [100, 100]
        self._draw()

    def reset_value(self):
        if not self.target:
            return
        self.value = [100, 100, 220, 130] if self.target[0] == REGION else [100, 100]
        self._draw()

    def save_value(self):
        if not self.target or not self.value:
            return
        kind, key, label = self.target[0], self.target[1], self.target[2]
        item = self._item()

        if kind == POINT:
            config.set_point(self.app.settings, key, self.value, item)
        elif kind == HOVER:
            config.set_hover_point(self.app.settings, key, self.value, item)
        else:
            config.set_region(self.app.settings, key, self.value, item)

        self.app.save_settings()
        scope = f" for {item['name']}" if item else ""
        log.success(f"Saved {label}{scope}: {self._format(self.value)}")
        self._refresh_target_list()

    # -- tests -----------------------------------------------------------

    def _write_test(self, text):
        self.test_output.delete("1.0", "end")
        self.test_output.insert("1.0", text)

    def test_target(self):
        """Read whatever the current selection points at, live from screen."""
        if not self.target or not self.value:
            self._write_test("Select something first.")
            return
        kind, key, label = self.target[0], self.target[1], self.target[2]

        try:
            if kind in (POINT, HOVER):
                pixel = screen.grab((self.value[0], self.value[1],
                                     self.value[0] + 1, self.value[1] + 1))
                colour = pixel.getpixel((0, 0))
                self._write_test(f"{label}\nPixel at ({self.value[0]}, "
                                 f"{self.value[1]}) is RGB {colour}")
                return

            region = tuple(self.value)
            if key in ("price_tooltip_region", "money_region"):
                text = ocr.read_text(region)
                parsed = (ocr.parse_money(text) if key == "money_region"
                          else ocr.parse_price(text))
                self._write_test(f"{label}\nRead: {text!r}\nParsed: {parsed}")
                return

            template_key = ("empty_hotbar_slot" if key.startswith("hotbar")
                            else "empty_order_slot")
            self._write_test(self._describe_slot(region, template_key, label))
        except Exception as e:
            self._write_test(f"Test failed: {e}")

    def _describe_slot(self, region, template_key, label):
        path = config.get_template_path(self.app.settings, template_key)
        if not path:
            return (f"{label}\nNo '{template_key}' reference saved yet - frame an "
                    f"empty slot and use 'Save box as this' below.")
        template = detect.load_template(path)
        detection = self.app.settings.get("detection", {})
        state, diff = detect.classify(
            screen.grab(region), template,
            float(detection.get("empty_slot_tolerance", 12.0)),
            float(detection.get("occupied_slot_min_difference", 18.0)))
        return (f"{label}\nState: {state.upper()}\nDifference from empty: "
                f"{diff:.1f}\n(empty if <= "
                f"{detection.get('empty_slot_tolerance', 12.0)}, occupied if >= "
                f"{detection.get('occupied_slot_min_difference', 18.0)})")

    def test_slots(self, which):
        """Classify all nine slots at once - the quickest way to see whether
        the boxes and the reference image agree with what's on screen."""
        try:
            item = self.app.active_item()
            if which == "hotbar":
                regions = slots.hotbar_regions(self.app.settings, item)
                states = slots.read_hotbar(self.app.settings, item)
            else:
                regions = slots.order_regions(self.app.settings, item)
                states = slots.read_order(self.app.settings, item)
        except Exception as e:
            self._write_test(f"{which} test failed: {e}")
            return

        lines = [f"{which.title()} slots:"]
        for index, (region, state) in enumerate(zip(regions, states), 1):
            lines.append(f"  {index}: {state:<9} {tuple(region)}")
        occupied = sum(1 for s in states if s == detect.OCCUPIED)
        lines.append(f"{occupied} occupied, {states.count(detect.EMPTY)} empty")
        self._write_test("\n".join(lines))

    # -- templates -------------------------------------------------------

    def save_template(self, key):
        """Crop the current box out of the screenshot and store it as the
        empty-slot reference."""
        if not self.value or len(self.value) != 4:
            self.template_status.configure(text="Select a box first.")
            return
        if self.shot is None:
            self.template_status.configure(text="Capture the screen first.")
            return

        os.makedirs(config.TEMPLATE_DIR, exist_ok=True)
        path = os.path.join(config.TEMPLATE_DIR, f"{key}.png")
        self.shot.crop(tuple(self.value)).save(path)
        config.set_template_path(self.app.settings, key, path)
        self.app.save_settings()
        self.template_status.configure(text=f"Saved {key}.png")
        log.success(f"Saved empty-slot reference '{key}' from "
                    f"{self._format(self.value)}")

    # -- refresh ---------------------------------------------------------

    def refresh(self):
        self._refresh_target_list()
        saved = [d["label"] for d in config.TEMPLATE_DEFINITIONS
                 if config.get_template_path(self.app.settings, d["key"])]
        self.template_status.configure(
            text=("Saved: " + ", ".join(saved)) if saved else "No references saved yet.")
