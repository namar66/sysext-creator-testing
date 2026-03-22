#!/usr/bin/python3

# Sysext-Creator Builder v4.8
# Fixes: Automatic /etc migration via tmpfiles.d

import os
import sys
import subprocess
import shutil
import logging
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

def run_cmd(cmd, cwd=None):
    try:
        return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True, errors="replace")
    except subprocess.CalledProcessError as e:
        logging.error(f"Command failed: {e.stderr}")
        sys.exit(1)

def get_os_info():
    info = {"ID": "fedora", "VERSION_ID": "any"}
    try:
        path = "/run/host/etc/os-release"
        if os.path.exists(path):
            with open(path, "r") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        info[k] = v.strip('"')
    except: pass
    return info

def get_rpm_version(rpm_path):
    query = "%|EPOCH?{%{EPOCH}:}:{}|%{VERSION}-%{RELEASE}"
    try:
        res = subprocess.run(["rpm", "-qp", f"--qf={query}", rpm_path], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except:
        return "unknown"

def calculate_host_dependencies(packages):
    if not packages: return []
    logging.info("Calculating missing dependencies against host OS...")
    cmd = ["flatpak-spawn", "--host", "rpm-ostree", "install", "--dry-run"] + packages
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
        added_pkgs = []
        parsing_added = False
        nevra_re = re.compile(r'^(.+?)-(([0-9]+:)?([^-]+)-([^-]+))\.(x86_64|noarch|i686)$')
        for line in res.stdout.splitlines():
            if any(line.startswith(s) for s in ["Installing ", "Added:", "Upgrading ", "Upgraded:"]):
                parsing_added = True
                continue
            elif any(line.startswith(s) for s in ["Removing ", "Removed:"]):
                parsing_added = False
                continue
            if parsing_added and line.startswith(" "):
                raw_pkg = line.strip().split()[0]
                match = nevra_re.match(raw_pkg)
                if match:
                    name_pkg, arch = match.group(1), match.group(6)
                    formatted = f"{name_pkg}.{arch}"
                    if formatted not in added_pkgs: added_pkgs.append(formatted)
        return added_pkgs
    except: return packages

def sync_host_repos():
    """Synchronize repositories and GPG keys from the host to the toolbox."""
    logging.info("Syncing host repositories and GPG keys...")
    host_repos = "/run/host/etc/yum.repos.d"
    host_gpg = "/run/host/etc/pki/rpm-gpg"
    
    if os.path.exists(host_repos):
        # Use sudo cp to be able to overwrite files in /etc
        try:
            subprocess.run(f"sudo cp -f {host_repos}/*.repo /etc/yum.repos.d/", shell=True)
        except: pass
                
    if os.path.exists(host_gpg):
        try:
            subprocess.run(["sudo", "mkdir", "-p", "/etc/pki/rpm-gpg"], check=True)
            subprocess.run(f"sudo cp -rf {host_gpg}/* /etc/pki/rpm-gpg/", shell=True)
            # Import keys into the toolbox RPM database
            for f in os.listdir(host_gpg):
                subprocess.run(["sudo", "rpm", "--import", os.path.join("/etc/pki/rpm-gpg", f)], capture_output=True)
        except: pass

def verify_rpms(rpm_paths):
    """Verify GPG signatures of downloaded RPM packages."""
    if not rpm_paths: return
    logging.info(f"Verifying GPG signatures for {len(rpm_paths)} packages...")
    for rpm in rpm_paths:
        try:
            # rpm -K (or --checksig) verifies the signature
            subprocess.run(["rpm", "-K", rpm], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            logging.error(f"❌ GPG Verification FAILED for: {rpm}")
            sys.exit(1)
    logging.info("✅ All signatures verified.")

def main():
    if len(sys.argv) < 3: sys.exit(1)
    name = sys.argv[1]
    requested_packages = sys.argv[2:]

    sync_host_repos()

    output_dir = "/run/host/var/tmp/sysext-creator"
    build_dir = f"/var/tmp/sysext-build-{name}"
    staging_root = build_dir

    try:
        if os.path.exists(build_dir): shutil.rmtree(build_dir)
        os.makedirs(staging_root, exist_ok=True)

        local_rpms = [p for p in requested_packages if p.endswith(".rpm") and os.path.isfile(p)]
        repo_packages = [p for p in requested_packages if p not in local_rpms]
        all_pkgs = repo_packages + local_rpms

        missing_deps = calculate_host_dependencies(all_pkgs)
        dnf_dir = os.path.join(build_dir, "dnf-downloads")
        os.makedirs(dnf_dir, exist_ok=True)

        if missing_deps:
            run_cmd(["dnf", "--refresh", "download", "-y", f"--destdir={dnf_dir}"] + missing_deps)
            # Verify GPG signatures of downloaded packages
            downloaded_rpms = [os.path.join(dnf_dir, f) for f in os.listdir(dnf_dir) if f.endswith(".rpm")]
            verify_rpms(downloaded_rpms)

        rpms_to_extract = local_rpms + [os.path.join(dnf_dir, f) for f in os.listdir(dnf_dir) if f.endswith(".rpm")]

        version = "unknown"
        for rpm in rpms_to_extract:
            if os.path.basename(rpm).startswith(name + "-"):
                version = get_rpm_version(rpm)
                break
        if version == "unknown" and rpms_to_extract:
            version = get_rpm_version(rpms_to_extract[0])

        logging.info(f"Detected version: {version}")

        for rpm in rpms_to_extract:
            ps = subprocess.Popen(["rpm2cpio", rpm], stdout=subprocess.PIPE)
            subprocess.run(["cpio", "-idmv"], stdin=ps.stdout, cwd=staging_root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ps.wait()

        # --- NEW: /ETC PROCESSING ---
        etc_src = os.path.join(staging_root, "etc")
        if os.path.exists(etc_src):
            logging.info(f"Found /etc content in {name}. Migrating to tmpfiles.d...")
            etc_template_dir = f"usr/lib/sysext-creator/etc-template/{name}"
            full_template_path = os.path.join(staging_root, etc_template_dir)
            os.makedirs(full_template_path, exist_ok=True)

            tmpfiles_content = []
            # Iterate through all files in /etc
            for root, dirs, files in os.walk(etc_src):
                for f in files:
                    full_f_path = os.path.join(root, f)
                    rel_f_path = os.path.relpath(full_f_path, etc_src)

                    # Path within sysext (where we move the file)
                    target_in_usr = os.path.join(full_template_path, rel_f_path)
                    os.makedirs(os.path.dirname(target_in_usr), exist_ok=True)
                    shutil.move(full_f_path, target_in_usr)

                    # Add line to tmpfiles.d (L+ creates a symlink and overwrites existing)
                    # Format: L+ /etc/path - - - - /usr/lib/sysext-creator/etc-template/name/path
                    tmpfiles_content.append(f"L+ /etc/{rel_f_path} - - - - /{etc_template_dir}/{rel_f_path}")

            # Delete empty /etc in staging root
            shutil.rmtree(etc_src)

            # Write tmpfiles.d configuration
            tmp_dir = os.path.join(staging_root, "usr/lib/tmpfiles.d")
            os.makedirs(tmp_dir, exist_ok=True)
            with open(os.path.join(tmp_dir, f"sysext-creator-{name}.conf"), "w") as f:
                f.write("# Generated by Sysext-Creator\n")
                f.write("\n".join(tmpfiles_content) + "\n")

        # --- END OF /ETC PROCESSING ---

        os_info = get_os_info()
        rel_dir = os.path.join(staging_root, "usr/lib/extension-release.d")
        os.makedirs(rel_dir, exist_ok=True)
        with open(os.path.join(rel_dir, f"extension-release.{name}"), "w") as f:
            f.write(f"ID={os_info.get('ID')}\n")
            f.write(f"VERSION_ID={os_info.get('VERSION_ID')}\n")
            f.write(f"SYSEXT_LEVEL={version}\n")
            f.write(f"VERSION={version}\n")

        meta_dir = os.path.join(staging_root, f"usr/share/factory/sysext-metadata/{name}")
        os.makedirs(meta_dir, exist_ok=True)
        with open(os.path.join(meta_dir, "packages.txt"), "w") as f:
            f.write(" ".join(requested_packages))
        with open(os.path.join(meta_dir, "version.txt"), "w") as f:
            f.write(version)

        out_file = os.path.join(output_dir, f"{name}.raw")
        selinux_contexts = "/run/host/etc/selinux/targeted/contexts/files/file_contexts"
        cmd = ["mkfs.erofs", "-x1", "--all-root", "-U", "clear", "-T", "0"]
        if os.path.exists(selinux_contexts):
            cmd.append(f"--file-contexts={selinux_contexts}")
        cmd.extend([out_file, staging_root])
        run_cmd(cmd)
        logging.info(f"Build finished: {out_file}")

    finally:
        if os.path.exists(build_dir):
            shutil.rmtree(build_dir)

if __name__ == "__main__":
    main()
