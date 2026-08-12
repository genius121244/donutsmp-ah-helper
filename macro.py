"""
macro.py
Kept as the old entry point so anything that used to call
`macro.run(settings, is_running)` still works. The workflow itself now
lives in engine.py, which does the same sequence but verifies each step
against the screen instead of assuming it worked.

The individual click helpers moved to actions.py and the price rules to
pricing.py.
"""

import engine


def run(settings, is_running, on_status=None, on_error=None, is_paused=None):
    """Runs the macro. `on_status` receives 'Status: <STATE>' strings for
    the old GUI's status label; the new GUI subscribes to states directly."""

    def on_state(state):
        if on_status:
            on_status(f"Status: {state}")

    return engine.run(settings, is_running, is_paused=is_paused,
                      on_state=on_state, on_error=on_error)
