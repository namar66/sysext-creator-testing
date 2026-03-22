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
        buffer = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buffer += chunk
            if b'\0' in buffer:
                break
        
        if not buffer:
            return
            
        # Split by null byte and process each message
        messages = buffer.split(b'\0')
        for msg_bytes in messages:
            if not msg_bytes.strip():
                continue
                
            msg = ""
            try:
                msg = msg_bytes.decode('utf-8').strip()
                request = json.loads(msg)
                
                full_method = request.get("method", "")
                method = full_method.split(".")[-1] if "." in full_method else full_method
                params = request.get("parameters", request.get("params", {}))
                
                logging.info(f"Request: {method} with params {params}")
                
                response_data = {"status": "error", "message": "Unknown method"}
                
                if method == "ListExtensions":
                    extensions = []
                    if os.path.exists("/var/lib/extensions"):
                        for f in os.listdir("/var/lib/extensions"):
                            if f.endswith(".raw"):
                                name = f[:-4]
                                version = "unknown"
                                release_file = f"/usr/lib/extension-release.d/extension-release.{name}"
                                if os.path.exists(release_file):
                                    with open(release_file, "r") as rf:
                                        for line in rf:
                                            if line.startswith("SYSEXT_LEVEL="):
                                                version = line.split("=")[1].strip().strip('"')
                                
                                extensions.append({
                                    "name": name,
                                    "version": version,
                                    "packages": "N/A"
                                })
                    response_data = {"extensions": extensions}

                elif method == "search":
                    query = params.get("q", "")
                    if query and (query.isalnum() or all(c in "._+-" or c.isalnum() for c in query)):
                        res = subprocess.run(["dnf", "search", query, "--quiet"], capture_output=True, text=True)
                        results = []
                        for line in res.stdout.splitlines():
                            if " : " in line:
                                name, desc = line.split(" : ", 1)
                                results.append({"name": name.strip(), "description": desc.strip()})
                        response_data = {"status": "ok", "results": results[:20]}
                    else:
                        response_data = {"status": "error", "message": "Invalid query"}

                elif method == "DeploySysext" or method == "build":
                    name = params.get("name")
                    packages = params.get("packages", [])
                    path = params.get("path")
                    
                    if method == "DeploySysext" and path:
                        try:
                            os.makedirs("/var/lib/extensions", exist_ok=True)
                            dest = f"/var/lib/extensions/{name}.raw"
                            subprocess.run(["cp", "-f", path, dest], check=True)
                            subprocess.run(["systemd-sysext", "refresh"], check=True)
                            logging.info("Running systemd-tmpfiles --create to apply /etc configuration")
                            subprocess.run(["systemd-tmpfiles", "--create"], check=False)
                            response_data = {"status": "Success"}
                        except Exception as e:
                            response_data = {"status": "error", "message": str(e)}
                    else:
                        cmd = ["python3", "/sysext-builder.py", name] + packages
                        res = subprocess.run(cmd, capture_output=True, text=True)
                        if res.returncode == 0:
                            response_data = {"status": "ok", "message": "Build successful"}
                        else:
                            response_data = {"status": "error", "message": res.stderr}

                elif method == "RemoveSysext" or method == "remove":
                    name = params.get("name")
                    if name and (name.isalnum() or all(c in "._+-" or c.isalnum() for c in name)):
                        try:
                            subprocess.run(["rm", "-f", f"/var/lib/extensions/{name}.raw"], check=True)
                            subprocess.run(["systemd-sysext", "refresh"], check=True)
                            logging.info("Running systemd-tmpfiles --create after removal")
                            subprocess.run(["systemd-tmpfiles", "--create"], check=False)
                            response_data = {"status": "ok"}
                        except Exception as e:
                            response_data = {"status": "error", "message": str(e)}
                    else:
                        response_data = {"status": "error", "message": "Invalid name"}

                elif method == "doctor":
                    res = subprocess.run(["python3", "/sysext-doctor.py"], capture_output=True, text=True)
                    response_data = {"status": "ok", "output": res.stdout}

                elif method == "check_updates":
                    # Placeholder for update logic
                    response_data = {"status": "ok", "updates": []}

                elif method == "update_all":
                    # Placeholder for update logic
                    response_data = {"status": "ok", "message": "All extensions updated"}

                final_resp = {"parameters": response_data}
                conn.sendall(json.dumps(final_resp).encode('utf-8') + b'\0')
                
            except json.JSONDecodeError as e:
                logging.error(f"JSON error: {e} in message: '{msg}'")
                conn.sendall(json.dumps({"status": "error", "message": f"JSON error: {str(e)}"}).encode('utf-8') + b'\0')
            except Exception as e:
                logging.error(f"Error processing message: {e}")
                conn.sendall(json.dumps({"status": "error", "message": str(e)}).encode('utf-8') + b'\0')

    except Exception as e:
        logging.error(f"Error handling client connection: {e}")
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
