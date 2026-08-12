"""
build.py
Builds the single-file Windows executable. Run on Windows:

    pip install -r requirements.txt pyinstaller
    python build.py

Produces dist/DonutAHMacro.exe. Attach that file to a GitHub release
tagged with the version in version.py and every existing install will
offer the update on next launch.

The font atlas is bundled inside the exe, so the resource pack folder does
not have to travel with it - though a Font+ folder placed next to the exe
still wins, which is how you switch packs without a rebuild.
"""

import os
import shutil
import subprocess
import sys

from version import VERSION

NAME = "DonutAHMacro"
ROOT = os.path.dirname(os.path.abspath(__file__))

# customtkinter ships its themes as data files and PyInstaller cannot see
# them by analysing imports, so they are collected explicitly. Without this
# the exe builds fine and then dies on launch looking for a .json theme.
HIDDEN_IMPORTS = ["customtkinter", "PIL._tkinter_finder", "pynput.keyboard._win32",
                  "pynput.mouse._win32"]


def data_arg(source, target):
    """PyInstaller wants os.pathsep between source and destination."""
    return f"{source}{os.pathsep}{target}"


def main():
    if not os.path.exists(os.path.join(ROOT, "Font+")):
        print("warning: no Font+ folder - the exe will have no bundled atlas")

    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        "--windowed",            # no console window behind the GUI
        "--name", NAME,
        "--collect-data", "customtkinter",
        "--add-data", data_arg(os.path.join(ROOT, "Font+"), "Font+"),
    ]
    for module in HIDDEN_IMPORTS:
        command += ["--hidden-import", module]

    icon = os.path.join(ROOT, "icon.ico")
    if os.path.exists(icon):
        command += ["--icon", icon]

    command.append(os.path.join(ROOT, "main.py"))

    print(f"Building {NAME} {VERSION}")
    subprocess.check_call(command, cwd=ROOT)

    built = os.path.join(ROOT, "dist", f"{NAME}.exe")
    print(f"\nDone: {built}")
    print(f"Tag a release v{VERSION} and attach that file.")
    return built


if __name__ == "__main__":
    if shutil.which("pyinstaller") is None and not os.environ.get("FORCE"):
        print("PyInstaller not found - pip install pyinstaller")
    main()
