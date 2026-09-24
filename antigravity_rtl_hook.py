# -*- coding: utf-8 -*-
"""
Antigravity PreInvocation Hook for Auto-Healing RTL Support.
Executed automatically by Antigravity via ~/.gemini/config/hooks.json.
Ensures that even if Antigravity just updated and the watcher was stopped,
the RTL patch and live injection are instantaneously restored.
"""

import os
import sys
import io
import socket

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def is_watcher_running(port=49876):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        s.close()
        return False
    except socket.error:
        return True


def main():
    real_stdout = sys.stdout
    sys.stdout = io.StringIO()

    try:
        import antigravity_rtl as rtl

        asar_path = rtl.get_asar_path()
        if os.path.exists(asar_path) and not rtl.is_already_patched(asar_path):
            rtl.patch_antigravity()
        else:
            rtl.inject_live_rtl(silent=True)

        if not is_watcher_running():
            rtl.start_background_watcher()

    except Exception:
        pass
    finally:
        sys.stdout = real_stdout
        print("{}")


if __name__ == "__main__":
    main()
