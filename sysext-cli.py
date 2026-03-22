#!/usr/bin/python3

# Sysext-Creator CLI v3.7
# Fixes: Robust version checking using dnf repoquery

import sys
import os
import argparse
import subprocess
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

try:
    import varlink
except ImportError:
    print("Error: python3-varlink is missing.")
    sys.exit(1)

SOCKET_ADDRESS = "unix:/run/sysext-creator/sysext-creator.sock"
INTERFACE = "io.sysext.creator"
BUILDER_SCRIPT = "/usr/local/bin/sysext-creator-builder.py"
BUILD_DIR = Path("/var/tmp/sysext-creator")
CONTAINER_NAME = "sysext-builder"

def connect():
    try:
        client = varlink.Client(address=SOCKET_ADDRESS)
        return client.open(INTERFACE)
    except Exception as e:
        print(f"Error: Daemon not reachable ({e})")
        sys.exit(1)

def get_package_version(pkg_name_or_path):
    """Zjistí verzi balíčku z RPM nebo z repozitáře (v toolboxu)."""
    if pkg_name_or_path.endswith(".rpm") and os.path.exists(pkg_name_or_path):
        res = subprocess.run(["rpm", "-qp", "--qf", "%{VERSION}-%{RELEASE}", pkg_name_or_path], capture_output=True, text=True)
        return res.stdout.strip() if res.returncode == 0 else None
    else:
        # Repoquery je mnohem spolehlivější pro skriptování než 'dnf info'
        try:
            cmd = ["toolbox", "run", "-c", CONTAINER_NAME, "dnf", "repoquery", "-y", "--latest-limit", "1", "--qf", "%{version}-%{release}", pkg_name_or_path]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode == 0 and res.stdout.strip():
                # Vezmeme poslední řádek (pro případ, že jich repoquery vrátí víc)
                return res.stdout.strip().splitlines()[-1].strip()
        except: pass
    return None

def cmd_list(args):
    with connect() as remote:
        res = remote.ListExtensions()
        exts = res.get("extensions", [])
        if not exts:
            print("No extensions active.")
            return
        print(f"{'NAME':<20} | {'VERSION':<20} | {'PACKAGES'}")
        print("-" * 70)
        for e in exts:
            print(f"{e.get('name'):<20} | {e.get('version'):<20} | {e.get('packages')}")

def cmd_remove(args):
    with connect() as remote:
        remote.RemoveSysext(args.name)
        print(f"Extension '{args.name}' removed.")

def cmd_install(args):
    if args.name_or_rpm.endswith(".rpm") and os.path.exists(args.name_or_rpm):
        abs_path = os.path.abspath(args.name_or_rpm)
        try:
            res = subprocess.run(["rpm", "-qp", "--qf", "%{NAME}", abs_path], capture_output=True, text=True, check=True)
            name = res.stdout.strip()
        except:
            name = Path(abs_path).stem.split('-')[0]
        packages = [abs_path] + args.packages
        main_pkg = abs_path
    else:
        name = args.name_or_rpm
        packages = args.packages if args.packages else [name]
        main_pkg = packages[0]

    # --- KONTROLA VERZE ---
    print(f"Checking version for '{name}'...")
    with connect() as remote:
        res = remote.ListExtensions()
        current_ext = next((e for e in res.get("extensions", []) if e['name'] == name), None)

        if current_ext:
            current_version = current_ext.get("version")
            if subprocess.run(["podman", "container", "exists", CONTAINER_NAME]).returncode != 0:
                subprocess.run(["toolbox", "create", "-c", CONTAINER_NAME], check=True)

            new_version = get_package_version(main_pkg)

            if new_version and current_version == new_version and not args.force:
                print(f"✅ Extension '{name}' is already up to date (version {current_version}).")
                return
            elif new_version:
                print(f"🔄 Update available: {current_version} -> {new_version}")
            else:
                print(f"⚠️ Could not determine remote version. Proceeding with build to be safe...")

    # --- BUILD PROCES ---
    print(f"\n--- Step 1: Building '{name}' ---")
    script = "/run/host" + BUILDER_SCRIPT
    try:
        subprocess.run(["toolbox", "run", "-c", CONTAINER_NAME, "python3", script, name] + packages, check=True)
    except:
        print("Build failed.")
        sys.exit(1)

    print(f"\n--- Step 2: Deploying ---")
    with connect() as remote:
        p = BUILD_DIR / f"{name}.raw"
        if p.exists():
            res = remote.DeploySysext(name, str(p), args.force)
            if res.get("status") == "Success":
                print("\n✅ Done! Extension is now active.")
            else:
                print(f"\n❌ Deployment failed: {res.get('status')}")
        else:
            print(f"\n❌ Build output not found: {p}")

def main():
    parser = argparse.ArgumentParser(description="Sysext CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    rem = sub.add_parser("remove"); rem.add_argument("name")
    ins = sub.add_parser("install")
    ins.add_argument("name_or_rpm")
    ins.add_argument("packages", nargs="*")
    ins.add_argument("--force", action="store_true")

    args = parser.parse_args()
    if args.command == "list": cmd_list(args)
    elif args.command == "remove": cmd_remove(args)
    elif args.command == "install": cmd_install(args)

if __name__ == "__main__":
    main()
