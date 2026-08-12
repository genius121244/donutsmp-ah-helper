"""
updater.py
Checks GitHub releases for a newer build and installs it.

Windows won't let a running .exe be overwritten, so the swap can't happen
in this process. The download goes to a temp file, a small batch script is
written that waits for this process to exit, replaces the exe and starts it
again, and then we quit. The batch file deletes itself last.

Everything here is standard library on purpose: an updater that needs a
dependency installed is an updater that can't fix a broken install.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request

from applog import log
from version import GITHUB_REPO, VERSION

API = "https://api.github.com/repos/{repo}/releases/latest"
TIMEOUT = 10


def parse_version(text):
    """'v1.2.3' -> (1, 2, 3). Unparseable input sorts lowest, so a release
    with a strange tag never looks newer than what is installed."""
    if not text:
        return (0, 0, 0)
    found = re.findall(r"\d+", str(text))
    numbers = [int(n) for n in found[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)


def is_newer(candidate, current=VERSION):
    return parse_version(candidate) > parse_version(current)


def frozen():
    """True when running as a PyInstaller build rather than from source."""
    return getattr(sys, "frozen", False)


class Update:
    def __init__(self, version, url, notes=""):
        self.version = version
        self.url = url
        self.notes = notes


def check(repo=GITHUB_REPO, current=VERSION):
    """The newest release if it beats `current`, else None.

    Never raises: no network, rate limiting and a repo with no releases at
    all are all just 'no update', because none of them should stop the
    macro from starting.
    """
    try:
        request = urllib.request.Request(
            API.format(repo=repo),
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "donutsmp-ah-helper"})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        log.info(f"Update check skipped: {e}")
        return None

    tag = data.get("tag_name") or data.get("name")
    if not is_newer(tag, current):
        return None

    asset = next((a for a in data.get("assets", [])
                  if str(a.get("name", "")).lower().endswith(".exe")), None)
    if asset is None:
        log.info(f"Release {tag} has no .exe attached - skipping")
        return None

    return Update(str(tag), asset["browser_download_url"], data.get("body") or "")


def check_async(on_found, repo=GITHUB_REPO, current=VERSION):
    """Check in the background; `on_found(update)` only fires if there is
    one. Called at startup, so it must never delay the window opening."""
    def run():
        update = check(repo, current)
        if update:
            on_found(update)
    threading.Thread(target=run, daemon=True).start()


def download(update, on_progress=None):
    """Fetch the new exe to a temp file and return its path."""
    target = os.path.join(tempfile.gettempdir(),
                          f"ah_macro_{parse_version(update.version)}.exe")
    request = urllib.request.Request(
        update.url, headers={"User-Agent": "donutsmp-ah-helper"})
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with open(target, "wb") as out:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if on_progress and total:
                    on_progress(done / total)
    return target


_SWAP_SCRIPT = """@echo off
rem Wait for the old build to exit before overwriting it.
:wait
tasklist /fi "PID eq {pid}" | find "{pid}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)
move /y "{new}" "{current}" >nul
start "" "{current}"
del "%~f0"
"""


def apply_and_restart(downloaded):
    """Replace this executable with the download and relaunch it.

    Returns False (without touching anything) when not running as a built
    exe - from source there is nothing to swap, and git is the update
    mechanism.
    """
    if not frozen():
        log.warning("Running from source - update with git, not the updater")
        return False

    current = sys.executable
    script = os.path.join(tempfile.gettempdir(), "ah_macro_update.bat")
    with open(script, "w") as f:
        f.write(_SWAP_SCRIPT.format(pid=os.getpid(), new=downloaded,
                                    current=current))

    subprocess.Popen(["cmd", "/c", script],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True
