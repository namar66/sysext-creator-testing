#!/usr/bin/python3

# Sysext-Creator Auto-Updater v3.1
# Fixes: Version-aware updates (only rebuilds if newer version exists)

import sys
import os
import subprocess
import logging
import json
from pathlib import Path

# Pokusíme se importovat varlink, pokud chybí, vypíšeme chybu
try:
    import varlink
except ImportError:
    logging.error("python3-varlink is missing.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

SOCKET_PATH = "unix:/run/sysext-creator/sysext-creator.sock"
INTERFACE = "io.sysext.creator"
CONTAINER_NAME = "sysext-builder"
BUILDER_SCRIPT = "/usr/local/bin/sysext-creator-builder.py"
BUILD_DIR = Path("/var/tmp/sysext-creator")

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
    try:
        client = varlink.Client(address=SOCKET_PATH)
        remote = client.open(INTERFACE)
    except Exception as e:
        logging.error(f"Failed to connect to daemon: {e}")
        sys.exit(1)

    try:
        res = remote.ListExtensions()
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
                remote.DeploySysext(name, str(path), True)
                logging.info(f"Successfully updated '{name}' to {new_version if new_version else 'latest'}.")
            else:
                logging.error(f"Build finished but output {path} not found.")
        except Exception as e:
            logging.error(f"Update failed for '{name}': {e}")

if __name__ == "__main__":
    update_extensions()
