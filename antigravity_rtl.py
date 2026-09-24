# -*- coding: utf-8 -*-
"""
Antigravity RTL Tool (v2.0 - With Auto-Update Persistence)
Adds complete Bidirectional (RTL / LTR) support to Google Antigravity
and automatically heals itself after every Antigravity update.
"""

import os
import sys
import json
import struct
import shutil
import socket
import base64
import argparse
import subprocess
import urllib.request
import winreg

DEFAULT_APP_DIR = os.path.expandvars(r"%LOCALAPPDATA%\Programs\antigravity")
DEFAULT_ROAMING_DIR = os.path.expandvars(r"%APPDATA%\Antigravity")
GLOBAL_CONFIG_DIR = os.path.expanduser(r"~\.gemini\config")
GLOBAL_HOOKS_PATH = os.path.join(GLOBAL_CONFIG_DIR, "hooks.json")

RTL_SIGNATURE = "/* ANTIGRAVITY_RTL_ENGINE_V1 */"
REGISTRY_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_VALUE_NAME = "AntigravityRTLWatcher"
HOOK_NAME = "antigravity-rtl-auto-heal"
WATCHER_PORT = 49876


def get_base_dir():
    return os.path.dirname(os.path.abspath(__file__))


def get_python_executables():
    """Return (python_exe, pythonw_exe) paths."""
    py_exe = sys.executable
    py_dir = os.path.dirname(py_exe)
    candidate_pyw = os.path.join(py_dir, "pythonw.exe")
    if os.path.exists(candidate_pyw):
        pyw_exe = candidate_pyw
    else:
        pyw_exe = py_exe
    return py_exe, pyw_exe


def get_asar_path(app_dir=None):
    base = app_dir or DEFAULT_APP_DIR
    return os.path.join(base, "resources", "app.asar")


def get_backup_path(app_dir=None):
    return get_asar_path(app_dir) + ".bak"


def read_asar_archive(asar_path):
    with open(asar_path, "rb") as f:
        u1, u2, u3, json_len = struct.unpack("<IIII", f.read(16))
        header = json.loads(f.read(json_len).decode("utf-8"))
        pad = (4 - (json_len % 4)) % 4
        payload_offset = 16 + json_len + pad
        return header, payload_offset


def extract_file_from_asar(asar_path, header, payload_offset, file_path_parts):
    curr = header
    for p in file_path_parts:
        curr = curr["files"][p]
    offset = int(curr["offset"])
    size = int(curr["size"])
    with open(asar_path, "rb") as f:
        f.seek(payload_offset + offset)
        return f.read(size)


def is_already_patched(asar_path):
    try:
        if not os.path.exists(asar_path):
            return False
        header, payload_offset = read_asar_archive(asar_path)
        preload_code = extract_file_from_asar(
            asar_path, header, payload_offset, ["dist", "preload.js"]
        ).decode("utf-8", errors="ignore")
        return RTL_SIGNATURE in preload_code
    except Exception:
        return False


def pack_asar_archive(orig_header, extracted_files_map, output_asar_path):
    new_header = {"files": {}}
    payload = bytearray()

    def build_tree(orig_d, path_parts, target_d):
        for name, meta in orig_d.get("files", {}).items():
            current_parts = path_parts + [name]
            rel_key = "/".join(current_parts)

            if "files" in meta:
                target_d[name] = {"files": {}}
                build_tree(meta, current_parts, target_d[name]["files"])
            elif meta.get("unpacked"):
                target_d[name] = {"size": meta["size"], "unpacked": True}
                if meta.get("executable"):
                    target_d[name]["executable"] = True
            else:
                if rel_key in extracted_files_map:
                    data = extracted_files_map[rel_key]
                else:
                    data = meta["_raw_data"]

                offset = len(payload)
                payload.extend(data)
                node = {"size": len(data), "offset": str(offset)}
                if meta.get("executable"):
                    node["executable"] = True
                target_d[name] = node

    build_tree(orig_header, [], new_header["files"])

    header_json_str = json.dumps(new_header, separators=(",", ":")).encode("utf-8")
    json_len = len(header_json_str)
    pad = (4 - (json_len % 4)) % 4
    padded_json_str = header_json_str + (b"\0" * pad)

    u1 = 4
    u2 = json_len + pad + 8
    u3 = json_len + pad + 4

    with open(output_asar_path, "wb") as out_f:
        out_f.write(struct.pack("<IIII", u1, u2, u3, json_len))
        out_f.write(padded_json_str)
        out_f.write(payload)


def read_all_asar_files(asar_path):
    header, payload_offset = read_asar_archive(asar_path)
    with open(asar_path, "rb") as f:
        def attach_data(d):
            for name, meta in d.get("files", {}).items():
                if "files" in meta:
                    attach_data(meta)
                elif not meta.get("unpacked"):
                    offset = int(meta["offset"])
                    size = int(meta["size"])
                    f.seek(payload_offset + offset)
                    meta["_raw_data"] = f.read(size)
        attach_data(header)
    return header


def is_watcher_running():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", WATCHER_PORT))
        s.close()
        return False
    except socket.error:
        return True


def start_background_watcher():
    if is_watcher_running():
        return True

    _, pyw_exe = get_python_executables()
    watcher_script = os.path.join(get_base_dir(), "antigravity_rtl_watcher.pyw")
    if not os.path.exists(watcher_script):
        return False

    try:
        # Use WMI Win32_Process.Create so the process escapes any parent Job Object
        base_dir = get_base_dir()
        wmi_cmd = (
            f"Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
            f"-Arguments @{{ CommandLine = '\"{pyw_exe}\" \"{watcher_script}\"'; "
            f"CurrentDirectory = '{base_dir}' }} | Out-Null"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", wmi_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
        if is_watcher_running():
            return True

        # Fallback to detached Popen
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        subprocess.Popen(
            [pyw_exe, watcher_script],
            cwd=base_dir,
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
        )
        return True
    except Exception as e:
        print(f"[!] Could not launch background watcher: {e}")
        return False


def stop_background_watcher():
    try:
        cmd = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -like '*antigravity_rtl_watcher.pyw*' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def is_startup_registered():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_RUN_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, REGISTRY_VALUE_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def is_hook_installed():
    try:
        if not os.path.exists(GLOBAL_HOOKS_PATH):
            return False
        with open(GLOBAL_HOOKS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return HOOK_NAME in data and data[HOOK_NAME].get("enabled", True)
    except Exception:
        return False


def enable_auto_persistence():
    py_exe, pyw_exe = get_python_executables()
    watcher_script = os.path.join(get_base_dir(), "antigravity_rtl_watcher.pyw")
    hook_script = os.path.join(get_base_dir(), "antigravity_rtl_hook.py")

    # 1. Register in Windows Startup (HKCU\...\Run)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_RUN_PATH, 0, winreg.KEY_SET_VALUE) as key:
            cmd_str = f'"{pyw_exe}" "{watcher_script}"'
            winreg.SetValueEx(key, REGISTRY_VALUE_NAME, 0, winreg.REG_SZ, cmd_str)
        print("[+] Registered Auto-Update Watcher in Windows Startup.")
    except Exception as e:
        print(f"[!] Failed to register Windows Startup key: {e}")

    # 2. Install Global PreInvocation Hook in ~/.gemini/config/hooks.json
    try:
        os.makedirs(GLOBAL_CONFIG_DIR, exist_ok=True)
        hooks_data = {}
        if os.path.exists(GLOBAL_HOOKS_PATH):
            try:
                with open(GLOBAL_HOOKS_PATH, "r", encoding="utf-8") as f:
                    hooks_data = json.load(f)
            except Exception:
                hooks_data = {}

        hooks_data[HOOK_NAME] = {
            "enabled": True,
            "PreInvocation": [
                {
                    "type": "command",
                    "command": f'"{py_exe}" "{hook_script}"',
                    "timeout": 10,
                }
            ],
        }
        with open(GLOBAL_HOOKS_PATH, "w", encoding="utf-8") as f:
            json.dump(hooks_data, f, indent=2, ensure_ascii=False)
        print("[+] Installed Global Self-Healing Hook in ~/.gemini/config/hooks.json.")
    except Exception as e:
        print(f"[!] Failed to configure global hook: {e}")

    # 3. Launch the background watcher right now
    if start_background_watcher():
        print("[+] Background Auto-Update Watcher is now active and monitoring updates.")


def disable_auto_persistence():
    # 1. Remove Windows Startup key
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_RUN_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, REGISTRY_VALUE_NAME)
        print("[+] Removed Auto-Update Watcher from Windows Startup.")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[!] Could not remove startup key: {e}")

    # 2. Remove Global Hook
    try:
        if os.path.exists(GLOBAL_HOOKS_PATH):
            with open(GLOBAL_HOOKS_PATH, "r", encoding="utf-8") as f:
                hooks_data = json.load(f)
            if HOOK_NAME in hooks_data:
                del hooks_data[HOOK_NAME]
                with open(GLOBAL_HOOKS_PATH, "w", encoding="utf-8") as f:
                    json.dump(hooks_data, f, indent=2, ensure_ascii=False)
                print("[+] Removed Global Self-Healing Hook from ~/.gemini/config/hooks.json.")
    except Exception as e:
        print(f"[!] Could not remove global hook: {e}")

    # 3. Stop running watcher process
    stop_background_watcher()
    print("[+] Stopped Background Auto-Update Watcher.")


def patch_antigravity(app_dir=None, enable_auto=True):
    asar_path = get_asar_path(app_dir)
    bak_path = get_backup_path(app_dir)

    if not os.path.exists(asar_path):
        print(f"[-] Error: Antigravity app.asar not found at '{asar_path}'")
        return False

    if is_already_patched(asar_path):
        print("[+] Antigravity is already patched with RTL support!")
        if enable_auto:
            enable_auto_persistence()
        inject_live_rtl()
        return True

    print(f"[*] Reading Antigravity archive from: {asar_path}")
    header = read_all_asar_files(asar_path)

    # Always backup the current clean unpatched app.asar so backup matches the latest version
    print(f"[*] Creating/updating clean version backup at: {bak_path}")
    shutil.copy2(asar_path, bak_path)

    engine_file = os.path.join(get_base_dir(), "rtl_engine.js")
    if not os.path.exists(engine_file):
        print(f"[-] Error: rtl_engine.js not found at '{engine_file}'")
        return False

    with open(engine_file, "r", encoding="utf-8") as f:
        engine_code = f.read()

    orig_preload = header["files"]["dist"]["files"]["preload.js"]["_raw_data"].decode("utf-8")
    injection = f"\n\n{RTL_SIGNATURE}\n" + engine_code + "\n"
    modified_preload = orig_preload + injection

    modified_files = {"dist/preload.js": modified_preload.encode("utf-8")}

    temp_asar = asar_path + ".tmp"
    print("[*] Rebuilding app.asar with RTL engine...")
    pack_asar_archive(header, modified_files, temp_asar)

    try:
        shutil.move(temp_asar, asar_path)
        print("[+] Successfully patched Antigravity! RTL support is now enabled.")
    except Exception as e:
        print(f"[-] Failed to overwrite app.asar: {e}")
        if os.path.exists(temp_asar):
            os.remove(temp_asar)
        return False

    if enable_auto:
        enable_auto_persistence()

    inject_live_rtl()
    return True


def unpatch_antigravity(app_dir=None):
    disable_auto_persistence()

    asar_path = get_asar_path(app_dir)
    bak_path = get_backup_path(app_dir)

    if not os.path.exists(bak_path):
        print(f"[-] Error: Backup file not found at '{bak_path}'. Cannot restore.")
        return False

    print(f"[*] Restoring original app.asar from: {bak_path}")
    try:
        shutil.copy2(bak_path, asar_path)
        print("[+] Antigravity has been restored to its original unpatched state.")
        return True
    except Exception as e:
        print(f"[-] Failed to restore backup: {e}")
        return False


def inject_live_rtl(roaming_dir=None, silent=False):
    base_roaming = roaming_dir or DEFAULT_ROAMING_DIR
    port_file = os.path.join(base_roaming, "DevToolsActivePort")

    if not os.path.exists(port_file):
        if not silent:
            print("[!] Antigravity is not currently running or DevToolsActivePort is not present.")
        return False

    try:
        with open(port_file, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        port = int(lines[0])
    except Exception as e:
        if not silent:
            print(f"[!] Could not read DevTools port: {e}")
        return False

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2.0) as resp:
            targets = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        if not silent:
            print(f"[!] Could not query DevTools targets: {e}")
        return False

    engine_file = os.path.join(get_base_dir(), "rtl_engine.js")
    with open(engine_file, "r", encoding="utf-8") as f:
        js_code = f.read()

    pages = [t for t in targets if t.get("type") == "page" and "webSocketDebuggerUrl" in t]
    if not pages:
        if not silent:
            print("[!] No active page targets found to inject live.")
        return False

    success_count = 0
    for page in pages:
        ws_url = page["webSocketDebuggerUrl"]
        try:
            path = ws_url.split(f"127.0.0.1:{port}")[1]
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect(("127.0.0.1", port))
            key = base64.b64encode(os.urandom(16)).decode("utf-8")
            s.sendall(
                f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode("utf-8")
            )
            s.recv(4096)

            payload_bytes = json.dumps(
                {
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {"expression": js_code, "returnByValue": True},
                }
            ).encode("utf-8")
            length = len(payload_bytes)
            frame = bytearray([0x81])
            mask = os.urandom(4)
            if length <= 125:
                frame.append(0x80 | length)
            elif length <= 65535:
                frame.append(0x80 | 126)
                frame.extend(length.to_bytes(2, "big"))
            else:
                frame.append(0x80 | 127)
                frame.extend(length.to_bytes(8, "big"))
            frame.extend(mask)
            frame.extend(bytearray(b ^ mask[i % 4] for i, b in enumerate(payload_bytes)))
            s.sendall(frame)

            b1, b2 = s.recv(2)
            plen = b2 & 0x7F
            if plen == 126:
                plen = int.from_bytes(s.recv(2), "big")
            elif plen == 127:
                plen = int.from_bytes(s.recv(8), "big")
            data = bytearray()
            while len(data) < plen:
                chunk = s.recv(plen - len(data))
                if not chunk:
                    break
                data.extend(chunk)
            s.close()
            success_count += 1
        except Exception as err:
            if not silent:
                print(f"[!] Live injection error on target {page.get('title')}: {err}")

    if not silent:
        print(f"[+] Live RTL injected into {success_count} running window(s) successfully!")
    return success_count > 0


def print_status(app_dir=None):
    asar_path = get_asar_path(app_dir)
    bak_path = get_backup_path(app_dir)

    print("==================================================")
    print("      Antigravity RTL Engine Status (v2.0)        ")
    print("==================================================")
    print(f"App Path:            {os.path.dirname(asar_path)}")
    print(f"app.asar exists:     {os.path.exists(asar_path)}")
    print(f"Backup exists:       {os.path.exists(bak_path)}")
    patched = is_already_patched(asar_path)
    print(f"RTL Patched:         {'YES [Active]' if patched else 'NO [Original]'}")
    print(f"Auto-Update Watcher: {'RUNNING (Background)' if is_watcher_running() else 'STOPPED'}")
    print(f"Windows Startup:     {'ENABLED' if is_startup_registered() else 'DISABLED'}")
    print(f"Global Self-Heal Hook:{'ENABLED' if is_hook_installed() else 'DISABLED'}")

    port_file = os.path.join(DEFAULT_ROAMING_DIR, "DevToolsActivePort")
    is_running = os.path.exists(port_file)
    print(f"Antigravity Live:    {'RUNNING' if is_running else 'NOT RUNNING'}")
    print("==================================================")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Antigravity RTL Fix & Auto-Update Persistence Tool")
    parser.add_argument("--patch", "-p", action="store_true", help="Patch Antigravity + Enable Auto-Update Protection")
    parser.add_argument("--unpatch", "-u", action="store_true", help="Disable Auto-Update Protection & Restore original Antigravity")
    parser.add_argument("--live", "-l", action="store_true", help="Inject RTL engine live into open Antigravity window(s)")
    parser.add_argument("--status", "-s", action="store_true", help="Show Antigravity RTL & Auto-Update status")
    parser.add_argument("--app-dir", type=str, default=None, help="Custom path to Antigravity directory")

    args = parser.parse_args()

    if args.patch:
        patch_antigravity(args.app_dir, enable_auto=True)
    elif args.unpatch:
        unpatch_antigravity(args.app_dir)
    elif args.live:
        inject_live_rtl()
    elif args.status:
        print_status(args.app_dir)
    else:
        patch_antigravity(args.app_dir, enable_auto=True)
        print_status(args.app_dir)


if __name__ == "__main__":
    main()
