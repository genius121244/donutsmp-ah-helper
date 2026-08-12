"""
fontpack.py
Finds the bundled Font+ resource pack and installs it into Minecraft.

The price reader only works while the game is drawing text with the same
atlas the reader compares against, so on a fresh account/PC the pack has to
be in Minecraft's resourcepacks folder *and* enabled in the game. Copying it
there by hand is the one setup step that has nothing to do with this program,
so it is done from the Settings tab instead.

Installing writes a folder, not a zip: Minecraft loads either, and a folder
can be overwritten in place on a re-install without leaving a stale zip
behind that the game would show as a second, older pack.
"""

import os
import shutil
import sys

PACK_NAME = "Font+"


def _base_dirs():
    """Where a copy of the pack might sit, nearest first.

    Same order as mcfont: a pack next to the exe beats the one baked into
    it, so replacing the folder is enough to change fonts.
    """
    dirs = []
    if getattr(sys, "frozen", False):
        dirs.append(os.path.dirname(os.path.abspath(sys.executable)))
        dirs.append(getattr(sys, "_MEIPASS", ""))
    dirs.append(os.path.dirname(os.path.abspath(__file__)))
    return [d for d in dirs if d]


def find_pack():
    """Absolute path of the Font+ folder we can install, or None."""
    for base in _base_dirs():
        candidate = os.path.join(base, PACK_NAME)
        if os.path.isdir(candidate):
            return candidate
    return None


def minecraft_dir():
    """The .minecraft folder for this OS, whether or not it exists."""
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return os.path.join(appdata, ".minecraft")
        return os.path.join(os.path.expanduser("~"), "AppData", "Roaming", ".minecraft")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library",
                            "Application Support", "minecraft")
    return os.path.join(os.path.expanduser("~"), ".minecraft")


def resourcepacks_dir():
    return os.path.join(minecraft_dir(), "resourcepacks")


def install(destination=None):
    """Copy the pack into resourcepacks and return where it landed.

    Raises FileNotFoundError if there is no pack to copy, or if Minecraft
    has never run here - creating .minecraft ourselves would leave a folder
    the game doesn't know about and hide a wrong-launcher/wrong-drive
    mistake behind a success message.
    """
    source = find_pack()
    if not source:
        raise FileNotFoundError(
            f"No {PACK_NAME} folder found next to the program. Unzip the "
            f"release so {PACK_NAME} sits beside the exe.")

    target_root = destination or resourcepacks_dir()
    if not destination and not os.path.isdir(minecraft_dir()):
        raise FileNotFoundError(
            f"No Minecraft folder at {minecraft_dir()}. Run the game once, "
            f"or copy {PACK_NAME} into your resourcepacks folder yourself.")

    os.makedirs(target_root, exist_ok=True)
    target = os.path.join(target_root, PACK_NAME)
    if os.path.isdir(target):
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def is_installed(destination=None):
    target_root = destination or resourcepacks_dir()
    return os.path.isdir(os.path.join(target_root, PACK_NAME))
