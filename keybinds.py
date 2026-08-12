"""
keybinds.py
Configurable hotkeys, keyboard or mouse.

Bindings are plain strings so they survive in settings.json unchanged:
a key is its own name ("f8", "ctrl+shift+s"), a mouse button is prefixed
("mouse:middle", "mouse:x2"). Nothing is limited to a fixed list - the
binding is whatever the user physically pressed while the field was
listening.

Two libraries are needed because neither covers both: `keyboard` for
global key hotkeys (already used for F8), pynput for mouse buttons.
"""

import threading

from applog import log

# Both listener libraries talk to the OS input stack at import time and
# raise on a machine with no desktop (a CI runner, a headless box). The
# naming and conflict rules below are pure string work, so they are kept
# importable without them; anything that actually listens checks first.
try:
    import keyboard
except Exception as _e:      # pragma: no cover - platform dependent
    keyboard = None
    log.warning(f"Keyboard hotkeys unavailable: {_e}")

try:
    from pynput import mouse as pynput_mouse
except Exception as _e:      # pragma: no cover - platform dependent
    pynput_mouse = None
    log.warning(f"Mouse bindings unavailable: {_e}")

MOUSE_PREFIX = "mouse:"

# Left click is never offered as a binding: the user has to left-click the
# field to start listening, and firing the macro from the same button they
# use to operate the UI is a trap.
_IGNORED_MOUSE_BUTTONS = {"left"}


def is_mouse(binding):
    return bool(binding) and binding.startswith(MOUSE_PREFIX)


def describe(binding):
    """Human-readable name for the UI."""
    if not binding:
        return "Unassigned"
    if is_mouse(binding):
        return "Mouse " + binding[len(MOUSE_PREFIX):].replace("_", " ").title()
    return binding.upper()


def conflicts(bindings):
    """{binding: [action, ...]} for every binding used more than once."""
    seen = {}
    for action, binding in bindings.items():
        if binding:
            seen.setdefault(binding, []).append(action)
    return {binding: actions for binding, actions in seen.items() if len(actions) > 1}


class BindingCapture:
    """Listens for one key or mouse press, then reports it and stops.

    Runs off the UI thread; the callback fires from a listener thread, so
    the UI has to marshal back to its own thread before touching widgets.
    """

    def __init__(self, on_captured):
        self.on_captured = on_captured
        self._mouse_listener = None
        self._keyboard_hook = None
        self._done = threading.Event()

    def start(self):
        if keyboard is not None:
            try:
                self._keyboard_hook = keyboard.hook(self._on_key)
            except (ImportError, OSError) as e:
                # The keyboard library needs elevated rights on some
                # systems; mouse buttons can still be bound without it.
                log.warning(f"Cannot listen for keys: {e}")
        if pynput_mouse is not None:
            self._mouse_listener = pynput_mouse.Listener(on_click=self._on_click)
            self._mouse_listener.start()

    def _finish(self, binding):
        if self._done.is_set():
            return
        self._done.set()
        self.stop()
        self.on_captured(binding)

    def _on_key(self, event):
        if event.event_type != keyboard.KEY_DOWN:
            return
        name = event.name
        if not name:
            return
        if name == "esc":
            self._finish(None)  # escape clears the binding
            return
        self._finish(name.lower())

    def _on_click(self, x, y, button, pressed):
        if not pressed:
            return
        name = button.name.lower()
        if name in _IGNORED_MOUSE_BUTTONS:
            return
        self._finish(MOUSE_PREFIX + name)

    def stop(self):
        if self._keyboard_hook is not None and keyboard is not None:
            try:
                keyboard.unhook(self._keyboard_hook)
            except (KeyError, ValueError):
                pass
            self._keyboard_hook = None
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None


class KeybindManager:
    """Keeps the live hotkeys in sync with the configured bindings."""

    def __init__(self, settings, handlers):
        """handlers: {action: callable}. Actions with no handler are ignored."""
        self.settings = settings
        self.handlers = handlers
        self._registered = []
        self._mouse_listener = None
        self._mouse_bindings = {}

    def bindings(self):
        return dict(self.settings.get("keybinds") or {})

    def apply(self):
        """Re-register everything. Safe to call after each settings change."""
        self.clear()
        self._mouse_bindings = {}

        for action, binding in self.bindings().items():
            handler = self.handlers.get(action)
            if not binding or handler is None:
                continue
            if is_mouse(binding):
                self._mouse_bindings[binding] = handler
            elif keyboard is None:
                continue
            else:
                try:
                    self._registered.append(keyboard.add_hotkey(binding, handler))
                except (ValueError, KeyError):
                    # An unknown key name (odd layouts, exotic keys) must
                    # not stop the rest of the hotkeys from registering.
                    log.warning(f"Could not register hotkey '{binding}' for {action}")
                except (ImportError, OSError) as e:
                    # No global key access at all (missing permissions).
                    # The buttons in the window still work, so the app has
                    # to keep running rather than refusing to start.
                    log.warning(f"Global hotkeys unavailable: {e}")
                    break

        if self._mouse_bindings and pynput_mouse is not None:
            self._mouse_listener = pynput_mouse.Listener(on_click=self._on_click)
            self._mouse_listener.start()

    def _on_click(self, x, y, button, pressed):
        if not pressed:
            return
        handler = self._mouse_bindings.get(MOUSE_PREFIX + button.name.lower())
        if handler:
            handler()

    def clear(self):
        for hotkey in self._registered:
            try:
                keyboard.remove_hotkey(hotkey)
            except (KeyError, ValueError, AttributeError):
                pass
        self._registered = []
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None
