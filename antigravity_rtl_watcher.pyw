# -*- coding: utf-8 -*-
"""
Antigravity RTL Auto-Watcher Daemon (.pyw)
Runs silently in the background (via pythonw.exe) with zero console window.
Automatically detects Antigravity updates and new windows, re-applying the RTL patch
and injecting live RTL support without any manual user intervention.
"""

import os
import sys
import time
import json
import socket
import traceback
import urllib.request

# Ensure local imports work
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import antigravity_rtl as rtl

SINGLETON_PORT = 49876
CHECK_INTERVAL_SECONDS = 3.0
LOG_FILE = os.path.join(BASE_DIR, "watcher.log")


def log_event(msg):
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {msg}\n")
    except Exception:
        pass


def acquire_singleton_lock():
    """Bind to a localhost port to ensure only one watcher instance runs at a time."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", SINGLETON_PORT))
        sock.listen(1)
        return sock
    except socket.error:
        return None


def get_active_page_ids():
    """Return a set of active CDP page IDs if Antigravity is currently running."""
    port_file = os.path.join(rtl.DEFAULT_ROAMING_DIR, "DevToolsActivePort")
    if not os.path.exists(port_file):
        return set()
    try:
        with open(port_file, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines:
            return set()
        port = int(lines[0])
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1.5) as resp:
            targets = json.loads(resp.read().decode("utf-8"))
        return {t.get("id") for t in targets if t.get("type") == "page" and t.get("id")}
    except Exception:
        return set()


def run_watcher():
    lock_socket = acquire_singleton_lock()
    if lock_socket is None:
        # Another watcher instance is already active
        sys.exit(0)

    log_event("Antigravity RTL Watcher started.")

    last_asar_sig = None
    injected_page_ids = set()

    while True:
        try:
            asar_path = rtl.get_asar_path()
            if os.path.exists(asar_path):
                stat = os.stat(asar_path)
                current_sig = (stat.st_mtime, stat.st_size)

                if current_sig != last_asar_sig:
                    # Wait briefly in case the updater is still flushing app.asar
                    time.sleep(1.0)
                    if not rtl.is_already_patched(asar_path):
                        log_event("Detected unpatched/updated app.asar! Applying RTL patch automatically...")
                        ok = rtl.patch_antigravity()
                        if ok:
                            log_event("Successfully auto-patched updated app.asar.")
                            injected_page_ids.clear()
                    # Refresh signature after patching
                    if os.path.exists(asar_path):
                        st2 = os.stat(asar_path)
                        last_asar_sig = (st2.st_mtime, st2.st_size)

            # Check live running windows to ensure any newly opened window has RTL active
            current_pages = get_active_page_ids()
            if not current_pages:
                injected_page_ids.clear()
            else:
                new_pages = current_pages - injected_page_ids
                if new_pages:
                    time.sleep(0.8)
                    if rtl.inject_live_rtl(silent=True):
                        injected_page_ids.update(current_pages)
                        log_event(f"Auto-injected live RTL into {len(new_pages)} window(s).")

        except Exception as e:
            log_event(f"Watcher error: {e}\n{traceback.format_exc()}")

        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    run_watcher()
