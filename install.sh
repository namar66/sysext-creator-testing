#!/bin/bash

# Sysext-Creator Installer v3.1
# Features: Sticky-Bit Drop-Zone, Hardened Systemd Service

set -e

# --- CONFIGURATION ---
INSTALL_DIR="/usr/local/bin"
SERVICE_DIR="/etc/systemd/system"
DROP_ZONE="/var/tmp/sysext-creator"
SOCKET_DIR="/run/sysext-creator"
SERVICE_USR_DIR="$HOME/.config/systemd/user"

# --- FILE PATHS (From current directory) ---
DAEMON_SRC="sysext-daemon.py"
BUILDER_SRC="sysext-builder.py"
CLI_SRC="sysext-cli.py"
UPDATER_SRC="sysext-updater.py"
DOCTOR_SRC="sysext-doctor.py"
GUI_SRC="sysext-gui.py"
SYSEXT_CREATOR_ICON="sysext-creator-icon.png"
KIO_SERVICE_MENU_INSTALL="sysext-creator-local-install.desktop"
GUI_DESKTOP_INSTALL="sysext-creator-gui.desktop"
BASH_COMPLETION_SRC="sysext-creator-cli.bash"

case "$1" in
    uninstall|remove|--uninstall)
        echo "=== Uninstalling Sysext-Creator ==="
        sudo systemctl disable --now sysext-creator.service 2>/dev/null || true
        sudo systemctl disable --now sysext-web.service 2>/dev/null || true
        systemctl --user disable --now sysext-autoupdater.timer 2>/dev/null || true

        sudo rm -f "$INSTALL_DIR/sysext-creator-daemon.py"
        sudo rm -f "$INSTALL_DIR/sysext-creator-builder.py"
        sudo rm -f "$INSTALL_DIR/sysext-creator-cli.py"
        sudo rm -f "$INSTALL_DIR/sysext-cli"
        sudo rm -f "$INSTALL_DIR/sysext-updater.py"
        sudo rm -f "$INSTALL_DIR/sysext-doctor.py"
        sudo rm -f "$INSTALL_DIR/sysext-gui.py"

        rm -f "$HOME/.local/share/applications/sysext-creator-gui.desktop"
        rm -f "$HOME/.local/share/bash-completion/completions/sysext-cli"
        rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/sysext-creator.png"
        rm -f "$HOME/.local/share/kio/servicemenus/sysext-creator-local-install.desktop"

        sudo rm -f "$SERVICE_DIR/sysext-creator.service"
        sudo rm -f "$SERVICE_DIR/sysext-web.service"
        rm -f "$SERVICE_USR_DIR/sysext-autoupdater.service" "$SERVICE_USR_DIR/sysext-autoupdater.timer"

        sudo systemctl daemon-reload
        systemctl --user daemon-reload
        echo "=== Uninstallation Completed! ==="
        echo "Note: Extensions in $DROP_ZONE were kept."
        exit 0
        ;;
esac

echo "=== Sysext-Creator Setup v3.1 ==="

# --- FILE CHECK ---
for f in "$DAEMON_SRC" "$BUILDER_SRC" "$CLI_SRC" "$UPDATER_SRC" "$DOCTOR_SRC" "$GUI_SRC" "$KIO_SERVICE_MENU_INSTALL" "$GUI_DESKTOP_INSTALL" "$BASH_COMPLETION_SRC"; do
    if [ ! -f "$f" ]; then
        echo "Error: Missing $f in current directory."
        exit 1
    fi
done

if [ ! -f "$SYSEXT_CREATOR_ICON" ]; then
    echo "Warning: Missing $SYSEXT_CREATOR_ICON. Icon will not be installed."
fi

# add -f for rewrite files
echo ">>> Phase 1: Installing Binaries to $INSTALL_DIR"
sudo cp -f "$DAEMON_SRC" "$INSTALL_DIR/sysext-creator-daemon.py"
sudo cp -f "$BUILDER_SRC" "$INSTALL_DIR/sysext-creator-builder.py"
sudo cp -f "$CLI_SRC" "$INSTALL_DIR/sysext-creator-cli.py"
sudo cp -f "$UPDATER_SRC" "$INSTALL_DIR/sysext-updater.py"
sudo cp -f "$DOCTOR_SRC" "$INSTALL_DIR/sysext-doctor.py"

sudo chmod +x "$INSTALL_DIR"/sysext-creator-*.py
sudo chmod +x "$INSTALL_DIR"/sysext-updater.py
sudo chmod +x "$INSTALL_DIR"/sysext-doctor.py

# Symlink for CLI
sudo ln -sf "$INSTALL_DIR/sysext-creator-cli.py" "$INSTALL_DIR/sysext-cli"

echo ">>> Phase 1.1: Installing Bash Completion"
COMPLETION_DIR="$HOME/.local/share/bash-completion/completions"
mkdir -p "$COMPLETION_DIR"
cp -f "$BASH_COMPLETION_SRC" "$COMPLETION_DIR/sysext-cli"

echo ">>> Phase 2: Setting up Drop-Zone (Sticky Bit)"
# DROP-ZONE: Place where user (toolbox) writes .raw images
# Sticky bit (1777) ensures users cannot delete each other's files
sudo mkdir -p "$DROP_ZONE"
sudo chmod 1777 "$DROP_ZONE"

echo ">>> Phase 3: Creating Systemd Service"
sudo tee "$SERVICE_DIR/sysext-creator.service" > /dev/null <<EOF
[Unit]
Description=Sysext Creator Daemon
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $INSTALL_DIR/sysext-creator-daemon.py
Restart=always
User=root
Group=wheel

# --- SECURITY SETTINGS ---
RuntimeDirectory=sysext-creator
RuntimeDirectoryMode=0770

# Share mount namespace with host (required for systemd-sysext refresh)
MountFlags=shared

# Permissions for mount operations
CapabilityBoundingSet=CAP_SYS_ADMIN CAP_CHOWN CAP_FOWNER CAP_DAC_OVERRIDE
AmbientCapabilities=CAP_SYS_ADMIN CAP_CHOWN CAP_FOWNER CAP_DAC_OVERRIDE

# Disable isolation that could prevent access to /usr
ProtectSystem=no
ProtectHome=no

[Install]
WantedBy=multi-user.target
EOF

echo " Configuring Auto-Updater..."
mkdir -p "$SERVICE_USR_DIR"
cat <<EOF | tee "$SERVICE_USR_DIR/sysext-autoupdater.service" > /dev/null
[Unit]
Description=Sysext Creator Auto-Updater
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 $INSTALL_DIR/sysext-updater.py
EOF

cat <<EOF | tee "$SERVICE_USR_DIR/sysext-autoupdater.timer" > /dev/null
[Unit]
Description=Weekly Timer for Sysext Auto-Updater
[Timer]
OnCalendar=Mon *-*-* 06:00:00
Persistent=true
[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now sysext-autoupdater.timer

echo ">>> Phase 4: Reloading Systemd & Starting Service"
sudo systemctl daemon-reload
sudo systemctl enable --now sysext-creator.service

echo ">>> Phase 5: Initializing Toolbox Container"
# Create container in advance so GUI doesn't have to wait
if ! podman container exists sysext-builder; then
    echo "Creating 'sysext-builder' toolbox container..."
    toolbox create -y -c sysext-builder
fi


echo ">>> Phase 6: Web Interface (Disabled for v3.1)"
install_web="n"
# read -p "Do you want to install and start the Web Interface? (y/N): " install_web
if [[ "$install_web" =~ ^([yY][eE][sS]|[yY])$ ]]; then
echo ">>> Phase 6.1: Checking System Dependencies (Node.js)"
# Check and install npm (Node.js)
if ! command -v npm &> /dev/null; then
    echo "npm not found. Installing nodejs..."
    if command -v sysext-cli &> /dev/null; then
        sysext-cli install nodejs
    else
        echo "Warning: sysext-cli not found. Please install nodejs/npm manually."
    fi
fi
    echo "Installing Web Interface dependencies..."
    if [ -f "package.json" ]; then
        npm install
        echo "Building Web Interface..."
        npm run build
        
        echo "Creating systemd service for Web Interface..."
        sudo tee "$SERVICE_DIR/sysext-web.service" > /dev/null <<EOF
[Unit]
Description=Sysext Creator Web Interface
After=sysext-creator.service

[Service]
Type=simple
WorkingDirectory=$(pwd)
ExecStart=/usr/bin/npm start
Restart=always
User=$(whoami)
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
EOF
        sudo systemctl daemon-reload
        sudo systemctl enable --now sysext-web.service
        echo "Web Interface is now running at http://localhost:3000"
    else
        echo "Warning: package.json not found. Skipping web interface installation."
    fi
fi

echo ">>> Phase 7: PyQt6 Gui Interface (Optional)"
read -p "Do you want to install and start the PyQt6 Gui Interface? (y/N): " install_gui
if [[ "$install_gui" =~ ^([yY][eE][sS]|[yY])$ ]]; then
sudo cp -f "$GUI_SRC" "$INSTALL_DIR/sysext-gui.py"
sudo chmod +x "$INSTALL_DIR"/sysext-gui.py

# Install icon if available
if [ -f "$SYSEXT_CREATOR_ICON" ]; then
    echo "Installing icon..."
    mkdir -p "$HOME/.local/share/icons/hicolor/scalable/apps/"
    cp -f "$SYSEXT_CREATOR_ICON" "$HOME/.local/share/icons/hicolor/scalable/apps/sysext-creator.png"
fi

# Install KDE Service Menu
echo "Installing KDE Service Menu..."
mkdir -p "$HOME/.local/share/kio/servicemenus/"
cp -f "$KIO_SERVICE_MENU_INSTALL" "$HOME/.local/share/kio/servicemenus/sysext-creator-local-install.desktop"
chmod +x "$HOME/.local/share/kio/servicemenus/sysext-creator-local-install.desktop"

# Create regular Application Launcher for GUI
echo "Creating Application Launcher..."
mkdir -p "$HOME/.local/share/applications/"
cp -f "$GUI_DESKTOP_INSTALL" "$HOME/.local/share/applications/sysext-creator-gui.desktop"
chmod +x "$HOME/.local/share/applications/sysext-creator-gui.desktop"

if ! python3 -c "import PyQt6" &> /dev/null; then
    echo "PyQt6 not found. Installing python3-pyqt6..."
    if command -v sysext-cli &> /dev/null; then
        sysext-cli install python3-pyqt6
    else
        echo "Warning: sysext-cli not found. Please install python3-pyqt6 manually."
    fi
fi
fi

echo "--------------------------------------------------"
echo "✅ Installation Complete!"
echo "Daemon is running. You can now use:"
echo " - 'sysext-cli list' (CLI)"
echo " - 'sysext-gui.py' (GUI, if installed)"
echo " - 'sudo sysext-doctor.py' (Diagnostics)"
echo "--------------------------------------------------"
