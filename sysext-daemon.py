#!/usr/bin/python3
import os
import socket
import json
import subprocess
import threading
import logging

# Configuration
SOCKET_PATH = "/run/sysext-creator.sock"
LOG_FILE = "/var/log/sysext-creator.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

def handle_client(conn):
    try:
        data = conn.recv(4096)
        if not data:
            return
        
        request = json.loads(data.decode('utf-8'))
        method = request.get("method")
        params = request.get("params", {})
        
        logging.info(f"Request: {method} with params {params}")
        
        response = {"status": "error", "message": "Unknown method"}
        
        if method == "search":
            query = params.get("q", "")
            if query and query.isalnum() or all(c in "._+-" or c.isalnum() for c in query):
                res = subprocess.run(["dnf", "search", query, "--quiet"], capture_output=True, text=True)
                results = []
                for line in res.stdout.splitlines():
                    if " : " in line:
                        name, desc = line.split(" : ", 1)
                        results.append({"name": name.strip(), "description": desc.strip()})
                response = {"status": "ok", "results": results[:20]}
            else:
                response = {"status": "error", "message": "Invalid query"}

        elif method == "build":
            name = params.get("name")
            packages = params.get("packages", [])
            # Run builder in background or synchronously for now (simple)
            # In a real app, we'd use a queue
            cmd = ["python3", "/sysext-builder.py", name] + packages
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                response = {"status": "ok", "message": "Build successful"}
            else:
                response = {"status": "error", "message": res.stderr}

        elif method == "remove":
            name = params.get("name")
            if name and (name.isalnum() or all(c in "._+-" or c.isalnum() for c in name)):
                try:
                    subprocess.run(["rm", "-f", f"/var/lib/extensions/{name}.raw"], check=True)
                    subprocess.run(["rm", "-f", f"/usr/lib/extension-release.d/extension-release.{name}"], check=True)
                    subprocess.run(["systemd-sysext", "refresh"], check=True)
                    response = {"status": "ok"}
                except Exception as e:
                    response = {"status": "error", "message": str(e)}
            else:
                response = {"status": "error", "message": "Invalid name"}

        elif method == "doctor":
            res = subprocess.run(["python3", "/sysext-doctor.py"], capture_output=True, text=True)
            response = {"status": "ok", "output": res.stdout}

        conn.sendall(json.dumps(response).encode('utf-8'))
    except Exception as e:
        logging.error(f"Error handling client: {e}")
        try:
            conn.sendall(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        except: pass
    finally:
        conn.close()

def main():
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)
    
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    
    # Restrict access to root and wheel group
    try:
        import grp
        wheel_gid = grp.getgrnam('wheel').gr_gid
        os.chown(SOCKET_PATH, 0, wheel_gid)
        os.chmod(SOCKET_PATH, 0o660)
        logging.info(f"Socket permissions set to 0660 (root:wheel)")
    except Exception as e:
        logging.warning(f"Could not set socket permissions to root:wheel: {e}")
        os.chmod(SOCKET_PATH, 0o666) # Fallback to more permissive if wheel group doesn't exist
    
    server.listen(5)
    
    logging.info(f"Daemon started, listening on {SOCKET_PATH}")
    
    try:
        while True:
            conn, _ = server.accept()
            thread = threading.Thread(target=handle_client, args=(conn,))
            thread.start()
    except KeyboardInterrupt:
        logging.info("Daemon stopping...")
    finally:
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)

if __name__ == "__main__":
    main()
