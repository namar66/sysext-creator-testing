#!/usr/bin/python3

# Sysext Doctor v3.1-rc2 - Precision Diagnostic
# Checks for /etc Overwrites & RPM Conflicts

import os
import subprocess
import sys
from pathlib import Path

SYSEXT_DIR = "/var/lib/extensions"
CONFEXT_DIR = "/var/lib/confexts"

def get_rpm_owner(file_path):
    if not os.path.exists(file_path): return None, False
    res = subprocess.run(["rpm", "-q", "--qf", "%{NAME}", "-f", file_path], capture_output=True, text=True)
    if res.returncode == 0: return res.stdout.strip(), True
    return None, True

def check_collisions():
    print("--- Checking for /usr & /etc Overwrites & RPM Conflicts ---")
    
    images = list(Path(SYSEXT_DIR).glob("*.raw")) + list(Path(CONFEXT_DIR).glob("*.raw"))
    if not images:
        print("No extensions found in /var/lib/extensions or /var/lib/confexts.")
        return

    # Global map of files across all extensions to detect cross-extension collisions
    # Format: { "/usr/bin/foo": ["ext1.raw", "ext2.raw"] }
    global_file_map = {}

    for img in images:
        print(f"\n🔍 Analyzing {img.name}...")
        try:
            res = subprocess.run(["systemd-dissect", "--list", str(img)], capture_output=True, text=True, check=True)
            for line in res.stdout.splitlines():
                if (line.startswith("usr/") or line.startswith("etc/")) and not line.endswith("/"):
                    full_path = "/" + line
                    
                    # Track for cross-extension collision
                    if full_path not in global_file_map:
                        global_file_map[full_path] = []
                    global_file_map[full_path].append(img.name)

                    owner, exists = get_rpm_owner(full_path)
                    if owner:
                        print(f"[FAIL] {full_path} overwrites system package: {owner}")
                    elif exists:
                        print(f"[WARN] {full_path} exists on host (local file or active extension)")
                    else:
                        print(f"[ OK ] {full_path} (new file)")
        except Exception as e: print(f"Error: {e}")

    print("\n--- Checking for Cross-Extension Collisions ---")
    cross_collisions = {k: v for k, v in global_file_map.items() if len(v) > 1}
    if cross_collisions:
        for path, exts in cross_collisions.items():
            print(f"[FAIL] Collision: {path} is provided by multiple extensions: {', '.join(exts)}")
    else:
        print("[ OK ] No cross-extension collisions detected.")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Please run with sudo.")
        sys.exit(1)
    check_collisions()
