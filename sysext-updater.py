#!/usr/bin/python3

# Sysext-Creator Auto-Updater v3.1
# Fixes: Version-aware updates (only rebuilds if newer version exists)

import sys
import os
import subprocess
import logging
import json
import socket
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

SOCKET_PATH = "/run/sysext-creator/sysext-creator.sock"
INTERFACE = "io.sysext.creator"
CONTAINER_NAME = "sysext-builder"
BUILDER_SCRIPT = "/usr/local/bin/sysext-creator-builder.py"
BUILD_DIR = Path("/var/tmp/sysext-creator")

class NativeVarlinkClient:
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.sock = None

    def __enter__(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.sock.connect(self.socket_path)
        except Exception as e:
            logging.error(f"Daemon not reachable at {self.socket_path} ({e})")
            sys.exit(1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.sock:
            self.sock.close()

    def call(self, method, **params):
        req = {
            "method": f"{INTERFACE}.{method}",
            "parameters": params
        }
        self.sock.sendall(json.dumps(req).encode('utf-8') + b'\0')
        
        buffer = b""
        while True:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            buffer += chunk
            if b'\0' in buffer:
                msg, _ = buffer.split(b'\0', 1)
                resp = json.loads(msg.decode('utf-8'))
                if "error" in resp:
                    logging.error(f"Error from daemon: {resp['error']}")
                    return {}
                return resp.get("parameters", {})
        return {}

def connect():
    return NativeVarlinkClient(SOCKET_PATH)

def get_remote_version(pkg_name):
    """Zjistí dostupnou verzi v repozitáři přes toolbox."""
    try:
        cmd = ["toolbox", "run", "-c", CONTAINER_NAME, "dnf", "--refresh", "repoquery", "-y", "--latest-limit", "1", "--qf", "%{version}-%{release}", pkg_name]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        v, r = "", ""
        for line in res.stdout.splitlines():
            if line.startswith("Version"): v = line.split(":")[1].strip()
            if line.startswith("Release"): r = line.split(":")[1].strip()
        if v and r: return f"{v}-{r}"
    except: pass
    return None

def update_extensions():
    with connect() as remote:
        try:
            res = remote.call("ListExtensions")
            extensions = res.get("extensions", [])
        except Exception as e:
            logging.error(f"Failed to fetch extensions: {e}")
            sys.exit(1)

        if not extensions:
            logging.info("No extensions found to update.")
            return

        # Ujistíme se, že builder kontejner existuje
        if subprocess.run(["podman", "container", "exists", CONTAINER_NAME]).returncode != 0:
            logging.info(f"Creating toolbox container '{CONTAINER_NAME}'...")
            subprocess.run(["toolbox", "create", "-y", "-c", CONTAINER_NAME], check=True)

        toolbox_script_path = "/run/host" + BUILDER_SCRIPT

        for ext in extensions:
            name = ext.get("name")
            current_version = ext.get("version")
            packages_str = ext.get("packages", "")

            if not packages_str or packages_str == "N/A" or "missing" in packages_str:
                logging.warning(f"Skipping '{name}': No metadata available.")
                continue

            packages = packages_str.split()
            main_pkg = packages[0] # Předpokládáme, že první balíček je ten hlavní

            # Pokud je to lokální RPM, updater ho neumí "aktualizovat" (nemá odkud vzít nové)
            if main_pkg.endswith(".rpm"):
                logging.info(f"Skipping '{name}': Local RPM based extension.")
                continue

            logging.info(f"Checking for updates: '{name}' (current: {current_version})")
            new_version = get_remote_version(main_pkg)

            if new_version and new_version == current_version:
                logging.info(f"Extension '{name}' is up to date.")
                continue

            if new_version:
                logging.info(f"New version found for '{name}': {new_version}. Starting rebuild...")
            else:
                logging.info(f"Could not check remote version for '{name}'. Rebuilding anyway to be sure.")

            build_args = ["run", "-c", CONTAINER_NAME, "python3", toolbox_script_path, name] + packages
            try:
                subprocess.run(["toolbox"] + build_args, check=True)

                # Nasazení po úspěšném buildu
                path = BUILD_DIR / f"{name}.raw"
                if path.exists():
                    remote.call("DeploySysext", name=name, path=str(path), force=True)
                    logging.info(f"Successfully updated '{name}' to {new_version if new_version else 'latest'}.")
                else:
                    logging.error(f"Build finished but output {path} not found.")
            except Exception as e:
                logging.error(f"Update failed for '{name}': {e}")

if __name__ == "__main__":
    update_extensions()
