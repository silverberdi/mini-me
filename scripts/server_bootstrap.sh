#!/usr/bin/env bash
set -euo pipefail

# mini me — Server Bootstrap Script (019.1)
# Must be run as root or with sudo.

echo "=== mini me: Starting Server Bootstrap (019.1) ==="

# 1. Ensure dedicated system user and group exist
if ! id -u minime >/dev/null 2>&1; then
    echo "Creating system user 'minime'..."
    useradd -r -s /usr/sbin/nologin -d /var/lib/minime minime
fi

# Ensure minime is in docker group
if getent group docker >/dev/null 2>&1; then
    usermod -aG docker minime
fi

# 2. Establish canonical directories
echo "Provisioning canonical directories..."
mkdir -p /opt/minime/app
mkdir -p /opt/minime/runtime
mkdir -p /opt/minime/workspaces
mkdir -p /etc/minime/secrets
mkdir -p /var/lib/minime/worktrees
mkdir -p /var/lib/minime/state
mkdir -p /var/lib/minime/previews
mkdir -p /var/log/minime

# Set permissions
chmod 0755 /opt/minime /var/lib/minime /var/log/minime /etc/minime
chmod 0700 /etc/minime/secrets
chmod 0755 /var/lib/minime/worktrees /var/lib/minime/state /var/lib/minime/previews

chown -R minime:minime /opt/minime
chown -R minime:minime /var/lib/minime
chown -R minime:minime /var/log/minime
chown -R minime:minime /etc/minime

# Configure git safe directories
git config --system --add safe.directory /opt/minime/app || true
git config --system --add safe.directory '/var/lib/minime/worktrees/*' || true

# 3. Provision Python virtual environment
echo "Setting up Python virtual environment..."
if [ ! -d /opt/minime/runtime/venv ]; then
    python3 -m venv /opt/minime/runtime/venv
fi

# Upgrade pip and install build dependencies
/opt/minime/runtime/venv/bin/pip install --upgrade pip setuptools wheel

# 4. Install systemd units
echo "Installing systemd service units..."
if [ -f /opt/minime/app/config/systemd/minime-api.service ]; then
    cp /opt/minime/app/config/systemd/minime-api.service /etc/systemd/system/
fi
if [ -f /opt/minime/app/config/systemd/minime-scheduler.service ]; then
    cp /opt/minime/app/config/systemd/minime-scheduler.service /etc/systemd/system/
fi
systemctl daemon-reload

echo "=== mini me: Server Bootstrap Complete ==="
