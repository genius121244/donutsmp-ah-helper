"""
applog.py
The macro's log: an in-memory ring buffer plus subscribers, so the same
entry reaches the Logs tab, stdout and (for the noisy levels) Discord.

Named applog rather than logging so it can't shadow the standard library
module for anything importing it.

The state machine logs transitions and decisions, not per-frame detail -
an overnight run should be readable the next morning.
"""

import os
import threading
import time

INFO = "INFO"
SUCCESS = "SUCCESS"
WARNING = "WARNING"
ERROR = "ERROR"

LEVELS = (INFO, SUCCESS, WARNING, ERROR)

MAX_ENTRIES = 2000


class LogEntry:
    __slots__ = ("timestamp", "level", "message")

    def __init__(self, level, message):
        self.timestamp = time.time()
        self.level = level
        self.message = message

    @property
    def time_string(self):
        return time.strftime("%H:%M:%S", time.localtime(self.timestamp))

    def format(self):
        return f"[{self.time_string}] [{self.level}] {self.message}"

    def __str__(self):
        return self.format()


class Log:
    def __init__(self, max_entries=MAX_ENTRIES, echo=True):
        self._entries = []
        self._subscribers = []
        self._lock = threading.Lock()
        self.max_entries = max_entries
        self.echo = echo

    def subscribe(self, callback):
        """callback(entry) for every new entry. Called from whichever
        thread logged, so a UI subscriber must marshal to its own thread."""
        self._subscribers.append(callback)
        return callback

    def unsubscribe(self, callback):
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def log(self, level, message):
        entry = LogEntry(level, message)
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self.max_entries:
                del self._entries[: len(self._entries) - self.max_entries]
        if self.echo:
            print(entry.format())
        for callback in list(self._subscribers):
            try:
                callback(entry)
            except Exception as e:  # a broken listener must not stop the macro
                print(f"[LOG] subscriber failed: {e}")
        return entry

    def info(self, message):
        return self.log(INFO, message)

    def success(self, message):
        return self.log(SUCCESS, message)

    def warning(self, message):
        return self.log(WARNING, message)

    def error(self, message):
        return self.log(ERROR, message)

    def entries(self, level=None):
        with self._lock:
            entries = list(self._entries)
        if level:
            entries = [e for e in entries if e.level == level]
        return entries

    def clear(self):
        with self._lock:
            self._entries.clear()

    def export(self, path):
        """Write the buffer to a text file; returns the path written."""
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for entry in self.entries():
                f.write(entry.format() + "\n")
        return path


# The application-wide log. Modules import this rather than passing a
# logger through every call.
log = Log()
