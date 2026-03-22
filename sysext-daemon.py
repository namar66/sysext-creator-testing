#!/usr/bin/python3

# Sysext-Creator Daemon v3.1-rc2 - Native Protocol Mode
# Fixes: Added missing 'import time' and systemd-tmpfiles sync

import os
import sys
import subprocess
import json
import socketserver
import grp
import logging
import datetime
import shutil
import re
import time
from pathlib import Path

RUN_DIR = "/run/sysext-creator"
SOCKET_PATH = f"{RUN_DIR}/sysext-creator.sock"
EXT_DIR = "/var/lib/extensions"
CONFEXT_DIR = "/var/lib/confexts"

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

INTERFACE_NAME = "io.sysext.creator"
INTERFACE_DEFINITION = """interface io.sysext.creator
type Extension (name: string, version: string, packages: string)
type Package (name: string, summary: string)
type Update (name: string, current_version: string, new_version: string)
type Check (name: string, status: string, message: string)

method ListExtensions() -> (extensions: []Extension)
method RemoveSysext(name: string) -> ()
method DeploySysext(name: string, path: string, force: bool) -> (status: string, conflicts: []string, progress: int)
method RefreshExtensions() -> (status: string)
method SearchPackages(query: string) -> (packages: []Package)
method CheckUpdates() -> (updates: []Update)
method UpdateAll() -> ()
method GetDoctorStatus() -> (checks: []Check)
"""

class SysextCreatorLogic:
    NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')
    CONTAINER_NAME = "sysext-builder"

    def ListExtensions(self):
        extensions = []
        dump_tool = shutil.which("dump.erofs")
        if os.path.exists(EXT_DIR):
            for file in os.listdir(EXT_DIR):
                if file.endswith(".raw") and not file.endswith(".confext.raw"):
                    name = file.replace(".raw", "")
                    raw_path = os.path.join(EXT_DIR, file)
                    stat = os.stat(raw_path)
                    version = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
                    packages = "N/A"
                    host_rel = f"/usr/lib/extension-release.d/extension-release.{name}"
                    if os.path.exists(host_rel):
                        try:
                            with open(host_rel, "r") as f:
                                content = f.read()
                                match = re.search(r'^SYSEXT_LEVEL=(.+)$', content, re.MULTILINE)
                                if match: version = match.group(1).strip()
                        except: pass
                    if dump_tool:
                        try:
                            for p_path in [f"usr/share/factory/sysext-metadata/{name}/packages.txt", f"/usr/share/factory/sysext-metadata/{name}/packages.txt"]:
                                cmd = [dump_tool, f"--cat={p_path}", raw_path]
                                res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
                                if res.returncode == 0 and res.stdout.strip():
                                    packages = res.stdout.strip()
                                    break
                        except: pass
                    extensions.append({"name": name, "version": version, "packages": packages})
        return {"extensions": extensions}

    def RemoveSysext(self, name):
        if not self.NAME_PATTERN.match(name): return {}
        
        # 1. Cleanup /etc symlinks before removing the image
        self._CleanupEtc(name)
        
        # 2. Remove the actual image files
        for directory in [EXT_DIR, CONFEXT_DIR]:
            for suffix in [".raw", ".confext.raw"]:
                target = os.path.join(directory, f"{name}{suffix}")
                if os.path.exists(target): os.remove(target)
        
        # 3. Refresh system state
        self.RefreshExtensions()
        return {}

    def _CleanupEtc(self, name):
        """Parses tmpfiles.d config and removes symlinks in /etc created by this sysext."""
        conf_path = f"/usr/lib/tmpfiles.d/sysext-creator-{name}.conf"
        if not os.path.exists(conf_path):
            logging.info(f"No tmpfiles.d config found for {name} at {conf_path}")
            return

        logging.info(f"Cleaning up /etc for {name} using {conf_path}...")
        try:
            with open(conf_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"): continue
                    
                    # Format: L+ /etc/path - - - - /usr/lib/...
                    parts = line.split()
                    if len(parts) >= 2 and parts[0] in ["L", "L+"]:
                        target_etc = parts[1]
                        if target_etc.startswith("/etc/"):
                            if os.path.islink(target_etc):
                                logging.info(f"Removing symlink: {target_etc}")
                                os.remove(target_etc)
                            elif os.path.exists(target_etc):
                                logging.warning(f"Path {target_etc} exists but is not a symlink, skipping.")
        except Exception as e:
            logging.error(f"Error during /etc cleanup for {name}: {e}")

    def DeploySysext(self, name, path, force):
        resolved_path = os.path.realpath(path)
        if not resolved_path.startswith("/var/tmp/sysext-creator/"):
            return {"status": "Error: Untrusted path", "conflicts": [], "progress": 0}

        is_confext = resolved_path.endswith(".confext.raw")
        target_dir = CONFEXT_DIR if is_confext else EXT_DIR
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, os.path.basename(resolved_path))

        try:
            logging.info(f"Deploying {resolved_path} to {target_path}")
            shutil.copy2(resolved_path, target_path)

            if os.path.exists(resolved_path):
                logging.info(f"Removing temporary build file: {resolved_path}")
                os.remove(resolved_path)

            restorecon = shutil.which("restorecon")
            if restorecon: subprocess.run([restorecon, "-v", target_path], check=True)
            status = self.RefreshExtensions()
            return {"status": status, "conflicts": [], "progress": 100}
        except Exception as e:
            logging.error(f"Deployment error: {e}")
            return {"status": f"Error: {str(e)}", "conflicts": [], "progress": 0}

    def RefreshExtensions(self):
        # 1. restore sysext/confext
        for tool_name in ["systemd-sysext", "systemd-confext"]:
            tool = shutil.which(tool_name)
            if tool:
                logging.info(f"Refreshing {tool_name}...")
                subprocess.run([tool, "refresh"], capture_output=True)

        logging.info("Waiting 3s for systemd-sysext to settle...")
        time.sleep(3)

        # 3. Synchronizing /etc with tmpfiles.d
        tmpfiles_tool = shutil.which("systemd-tmpfiles")
        if tmpfiles_tool:
            logging.info("Running systemd-tmpfiles --create to sync /etc...")
            subprocess.run([tmpfiles_tool, "--create", "--prefix=/etc"], capture_output=True)

        return "Success"

    def SearchPackages(self, query):
        packages = []
        try:
            cmd = ["toolbox", "run", "-c", self.CONTAINER_NAME, "dnf", "search", "-y", query]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if " : " in line:
                        name, summary = line.split(" : ", 1)
                        packages.append({"name": name.strip(), "summary": summary.strip()})
        except: pass
        return {"packages": packages}

    def CheckUpdates(self):
        updates = []
        exts = self.ListExtensions().get("extensions", [])
        for e in exts:
            name = e['name']
            current_version = e['version']
            packages = e['packages'].split()
            if not packages or packages[0] == "N/A": continue
            
            main_pkg = packages[0]
            try:
                cmd = ["toolbox", "run", "-c", self.CONTAINER_NAME, "dnf", "repoquery", "-y", "--latest-limit", "1", "--qf", "%{version}-%{release}", main_pkg]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                if res.returncode == 0 and res.stdout.strip():
                    new_version = res.stdout.strip().splitlines()[-1].strip()
                    if new_version != current_version:
                        updates.append({"name": name, "current_version": current_version, "new_version": new_version})
            except: pass
        return {"updates": updates}

    def UpdateAll(self):
        # Simply call the updater script
        updater_script = "/usr/local/bin/sysext-updater.py"
        if os.path.exists(updater_script):
            subprocess.Popen(["python3", updater_script])
        return {}

    def GetDoctorStatus(self):
        checks = []
        # Check Varlink socket
        checks.append({"name": "Varlink Socket", "status": "ok" if os.path.exists(SOCKET_PATH) else "error", "message": "Socket exists" if os.path.exists(SOCKET_PATH) else "Socket missing"})
        
        # Check systemd-sysext
        sysext_tool = shutil.which("systemd-sysext")
        checks.append({"name": "systemd-sysext", "status": "ok" if sysext_tool else "error", "message": "Tool found" if sysext_tool else "Tool missing"})
        
        # Check toolbox image (more reliable for root than container check)
        try:
            res = subprocess.run(["podman", "image", "exists", "registry.fedoraproject.org/fedora-toolbox"], capture_output=True)
            if res.returncode != 0:
                # Try generic name
                res = subprocess.run(["podman", "image", "list", "--format", "{{.Repository}}"], capture_output=True, text=True)
                has_toolbox = "toolbox" in res.stdout.lower()
            else:
                has_toolbox = True
            
            checks.append({"name": "Toolbox Image", "status": "ok" if has_toolbox else "warning", "message": "Image found" if has_toolbox else "Image might be missing (check 'toolbox list')"})
        except:
            checks.append({"name": "Toolbox Image", "status": "error", "message": "Podman check failed"})
            
        return {"checks": checks}

logic = SysextCreatorLogic()

class VarlinkNativeHandler(socketserver.StreamRequestHandler):
    def handle(self):
        buffer = b""
        while True:
            try:
                chunk = self.request.recv(8192)
                if not chunk: break
                buffer += chunk
                while b'\0' in buffer:
                    msg_bytes, buffer = buffer.split(b'\0', 1)
                    req = json.loads(msg_bytes.decode('utf-8'))
                    method = req.get("method", "")
                    params = req.get("parameters", {})
                    if method == "org.varlink.service.GetInfo":
                        resp = {"parameters": {"vendor": "Sysext Project", "product": "Sysext Creator", "version": "3.1-rc2", "interfaces": ["org.varlink.service", INTERFACE_NAME]}}
                    elif method == "org.varlink.service.GetInterfaceDescription":
                        resp = {"parameters": {"description": INTERFACE_DEFINITION}}
                    elif method == f"{INTERFACE_NAME}.ListExtensions":
                        resp = {"parameters": logic.ListExtensions()}
                    elif method == f"{INTERFACE_NAME}.RemoveSysext":
                        resp = {"parameters": logic.RemoveSysext(**params)}
                    elif method == f"{INTERFACE_NAME}.DeploySysext":
                        resp = {"parameters": logic.DeploySysext(**params)}
                    elif method == f"{INTERFACE_NAME}.RefreshExtensions":
                        resp = {"parameters": {"status": logic.RefreshExtensions()}}
                    elif method == f"{INTERFACE_NAME}.SearchPackages":
                        resp = {"parameters": logic.SearchPackages(**params)}
                    elif method == f"{INTERFACE_NAME}.CheckUpdates":
                        resp = {"parameters": logic.CheckUpdates()}
                    elif method == f"{INTERFACE_NAME}.UpdateAll":
                        resp = {"parameters": logic.UpdateAll()}
                    elif method == f"{INTERFACE_NAME}.GetDoctorStatus":
                        resp = {"parameters": logic.GetDoctorStatus()}
                    else:
                        resp = {"error": "org.varlink.service.MethodNotFound"}
                    self.request.sendall(json.dumps(resp).encode('utf-8') + b'\0')
            except: break

class ThreadedUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer): pass

def run_server():
    os.makedirs(RUN_DIR, exist_ok=True)
    if os.path.exists(SOCKET_PATH): os.remove(SOCKET_PATH)
    logging.info("Daemon v3.1-rc2 starting (Native Mode) on %s", SOCKET_PATH)
    with ThreadedUnixServer(SOCKET_PATH, VarlinkNativeHandler) as server:
        os.chmod(SOCKET_PATH, 0o660)
        try:
            wheel_info = grp.getgrnam('wheel')
            os.chown(SOCKET_PATH, -1, wheel_info.gr_gid)
        except: pass
        server.serve_forever()

if __name__ == "__main__":
    if os.geteuid() != 0: sys.exit(1)
    run_server()
