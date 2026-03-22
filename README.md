# Sysext Manager Dashboard (v3.1-rc2)

A modern graphical interface and toolset for managing system extensions (`systemd-sysext`) on Fedora Atomic Desktops (Silverblue, Kinoite, etc.).

## ⚠️ CRITICAL WARNING: EMERGENCY RECOVERY

System extensions modify your `/usr` and `/etc` hierarchies at runtime. While powerful, a malformed or incompatible extension **can break your system boot process** or cause desktop environment instability.

### If your system fails to boot:
1.  **Reboot** and enter the **GRUB menu** (usually by holding `Shift` or tapping `Esc` during boot).
2.  Select your current deployment and press `e` to edit the boot parameters.
3.  Find the line starting with `linux` and append the following parameter to the end:
    ```text
    systemd.mask=systemd-sysext.service
    ```
4.  Press `Ctrl+X` or `F10` to boot. This will prevent any extensions from being activated.
5.  Once the system is up, you can safely remove the problematic extension:
    ```bash
    # List extensions to find the culprit
    ls /var/lib/extensions
    
    # Remove the problematic .raw or .img file
    sudo rm /var/lib/extensions/problematic-extension.raw
    
    # Unmask the service for the next boot
    sudo systemctl unmask systemd-sysext.service
    ```

---

## Features
- **Extensions**: Overview of installed system extensions with version detection from the daemon.
- **Update**: Check for and install updates for individual sysext packages.
- **Search**: Real-time search of Fedora repositories for packages compatible with sysext.
- **Doctor**: System health diagnostics, collision detection in `/etc`, and daemon connection status.
- **Sticky-Bit Drop-Zone**: Secure transfer of images from unprivileged toolboxes to the privileged host.

## Technology Stack
- **Frontend**: React, Tailwind CSS, Lucide Icons, Framer Motion.
- **Backend**: Express.js (API bridge to the Varlink daemon socket).
- **Core**: Python-based Varlink daemon and CLI tools.

## Installation
The project includes an `install.sh` script that sets up binaries, systemd services, and the environment:

```bash
# Run installation (requires sudo)
chmod +x install.sh
./install.sh
```

**What the script does:**
1.  Installs binaries to `/usr/local/bin/`.
2.  Sets up the **Drop-Zone** (`/var/tmp/sysext-creator`) with a Sticky Bit (1777).
3.  Creates and starts the **systemd service** `sysext-creator.service`.
4.  Pre-configures the `sysext-builder` toolbox container.
5.  *Note: Web Interface installation is disabled by default in v3.1-rc2.*

## Python Toolset (Local)
In addition to the optional web dashboard, the project provides a suite of Python scripts for direct host management:

- **`sysext-gui.py`**: Main PyQt6 graphical interface for management, creation, and diagnostics.
- **`sysext-daemon.py`**: Varlink daemon running in the background with root privileges.
- **`sysext-builder.py`**: Script running inside the toolbox to create `.raw` images from RPMs.
- **`sysext-cli.py`**: Command-line interface for fast extension installation (`sysext-cli install <pkg>`).
- **`sysext-doctor.py`**: Diagnostic tool for checking collisions in `/etc` and the RPM database.
- **`sysext-updater.py`**: Automatic update checker for repository packages.

## Running the Local GUI
```bash
# Ensure you have PyQt6 and varlink installed
python3 sysext-gui.py
```
