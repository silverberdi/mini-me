#!/usr/bin/env bash
set -euo pipefail

# mini me — Deterministic Deploy/Update Script (019.2)
# Must be run as root or with sudo.

echo "=== mini me: Deploy / Update ==="

APP_DIR="/opt/minime/app"
VENV_DIR="/opt/minime/runtime/venv"

# 1. Update source code if tracked via git
if [ -d "${APP_DIR}/.git" ]; then
    echo "Updating git repository at ${APP_DIR}..."
    cd "${APP_DIR}"
    git fetch origin
    git checkout main
    git pull --ff-only origin main
fi

# 2. Update Python dependencies
echo "Updating Python package..."
"${VENV_DIR}/bin/pip" install -e "${APP_DIR}"

# 3. Apply database migrations if needed
if [ -f /etc/minime/minime.env ]; then
    echo "Checking / applying database migrations..."
    set -a
    source /etc/minime/minime.env
    set +a
    cd "${APP_DIR}"
    "${VENV_DIR}/bin/alembic" -c "${APP_DIR}/alembic.ini" upgrade head
fi

# 4. Ensure systemd units are up to date
echo "Updating systemd units..."
if [ -f "${APP_DIR}/config/systemd/minime-api.service" ]; then
    cp "${APP_DIR}/config/systemd/minime-api.service" /etc/systemd/system/
fi
if [ -f "${APP_DIR}/config/systemd/minime-scheduler.service" ]; then
    cp "${APP_DIR}/config/systemd/minime-scheduler.service" /etc/systemd/system/
fi
systemctl daemon-reload

# 5. Fix permissions
chown -R minime:minime /opt/minime /var/lib/minime /var/log/minime

# 6. Restart services
echo "Restarting services..."
systemctl restart minime-api minime-scheduler

# 7. Run health check
if [ -f "${APP_DIR}/scripts/health_check.sh" ]; then
    bash "${APP_DIR}/scripts/health_check.sh"
fi

echo "=== mini me: Deploy / Update Finished ==="
