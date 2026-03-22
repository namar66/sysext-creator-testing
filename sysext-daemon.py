#!/usr/bin/python3

# Sysext-Creator Daemon v10.5 - Native Protocol Mode
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
method ListExtensions() -> (extensions: []Extension)
method RemoveSysext(name: string) -> ()
method DeploySysext(name: string, path: string, force: bool) -> (status: string, conflicts: []string, progress: int)
method RefreshExtensions() -> (status: string)
"""

class SysextCreatorLogic:
    NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')

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
        for directory in [EXT_DIR, CONFEXT_DIR]:
            for suffix in [".raw", ".confext.raw"]:
                target = os.path.join(directory, f"{name}{suffix}")
                if os.path.exists(target): os.remove(target)
        self.RefreshExtensions()
        return {}

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
                        resp = {"parameters": {"vendor": "Sysext Project", "product": "Sysext Creator", "version": "10.5", "interfaces": ["org.varlink.service", INTERFACE_NAME]}}
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
                    else:
                        resp = {"error": "org.varlink.service.MethodNotFound"}
                    self.request.sendall(json.dumps(resp).encode('utf-8') + b'\0')
            except: break

class ThreadedUnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer): pass

def run_server():
    os.makedirs(RUN_DIR, exist_ok=True)
    if os.path.exists(SOCKET_PATH): os.remove(SOCKET_PATH)
    logging.info("Daemon v10.5 starting (Native Mode) on %s", SOCKET_PATH)
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
