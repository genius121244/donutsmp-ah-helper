"""
capture.py
Lets the user click "Set" in the GUI, then click anywhere on screen
(including in the game window) to record that pixel location.
Uses pynput because it listens globally, without stealing/blocking
the click from reaching the game underneath.
"""

from pynput import mouse


def capture_point(on_captured, on_status=None):
    """
    Listens for the next left-click anywhere on screen and calls
    on_captured(x, y) once it happens. Non-blocking (runs in a
    background listener thread). The click still passes through
    to whatever window is under the cursor.

    on_status: optional callback(str) for updating a "waiting for
               click..." style status message in the GUI.
    """
    if on_status:
        on_status("Click anywhere on screen to set this location...")

    def on_click(x, y, button, pressed):
        if button == mouse.Button.left and pressed:
            # Stop listening after the first click
            listener.stop()
            on_captured(int(x), int(y))
            return False  # also stops the listener

    listener = mouse.Listener(on_click=on_click)
    listener.start()
    return listener


def capture_region(on_captured, on_status=None):
    """
    Listens for a click-drag (mouse down -> mouse up) and calls
    on_captured(x1, y1, x2, y2) with the top-left/bottom-right
    corners once the drag finishes. Used for the OCR price box,
    since OCR needs an area, not a single point.
    """
    if on_status:
        on_status("Click and drag a box over the area, then release...")

    state = {"start": None}

    def on_click(x, y, button, pressed):
        if button != mouse.Button.left:
            return

        if pressed:
            state["start"] = (int(x), int(y))
        else:
            if state["start"] is None:
                return False
            x1, y1 = state["start"]
            x2, y2 = int(x), int(y)

            # Normalize so x1,y1 is always top-left and x2,y2 bottom-right
            left, right = sorted((x1, x2))
            top, bottom = sorted((y1, y2))

            listener.stop()
            on_captured(left, top, right, bottom)
            return False

    listener = mouse.Listener(on_click=on_click)
    listener.start()
    return listener
