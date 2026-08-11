"""
main.py
Entry point. Run this file to launch the macro GUI.
"""

BUILD_VERSION = "2026-08-10-r6-debug-prints"

from gui import App

if __name__ == "__main__":
    print(f"=== DonutSMP AH Macro | build: {BUILD_VERSION} ===")
    app = App()
    app.mainloop()
