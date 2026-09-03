#!/usr/bin/env bash
set -euo pipefail

# mini me — Comprehensive Health Check Script (019.2)

echo "============================================================"
echo "mini me — Comprehensive Server Health Check"
echo "============================================================"

PASS=0
FAIL=0

check() {
    local desc="$1"
    shift
    if "$@"; then
        echo "  [PASS] ${desc}"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] ${desc}"
        FAIL=$((FAIL + 1))
    fi
}

# 1. System Services
echo ""
echo "--- 1. System Services ---"
check "minime-api.service active" systemctl is-active --quiet minime-api
check "minime-scheduler.service active" systemctl is-active --quiet minime-scheduler

# 2. Local Endpoints
echo ""
echo "--- 2. Endpoints ---"
check "API Health HTTP 200" curl -s -f -o /dev/null http://127.0.0.1:8787/health
check "PWA Index HTTP 200" curl -s -f -o /dev/null http://127.0.0.1:8787/
check "PWA Manifest HTTP 200" curl -s -f -o /dev/null http://127.0.0.1:8787/static/manifest.webmanifest

# 3. Database
echo ""
echo "--- 3. PostgreSQL Database ---"
if [ -f /etc/minime/minime.env ]; then
    set -a
    source /etc/minime/minime.env
    set +a
    check "PostgreSQL Connectivity & Revision" /opt/minime/runtime/venv/bin/python3 -c "
import os
from sqlalchemy import create_engine, text
url = os.environ.get('MINIME_DATABASE_URL')
engine = create_engine(url)
with engine.connect() as conn:
    rev = conn.execute(text('SELECT version_num FROM alembic_version')).scalar()
    assert rev == '016_provider_efficiency_telemetry', f'Unexpected rev: {rev}'
"
fi

# 4. Providers & Tooling
echo ""
echo "--- 4. Providers & Tooling ---"
check "Headless Chrome Available" which google-chrome >/dev/null 2>&1 || which chromium >/dev/null 2>&1
check "Docker Available" docker info >/dev/null 2>&1
check "DeepSeek API Key Configured" test -n "${DEEPSEEK_API_KEY:-}"
check "GitHub App Key Configured" test -f "${MINIME_GITHUB_PRIVATE_KEY_PATH:-/etc/minime/secrets/github-app.pem}"

echo ""
echo "============================================================"
echo "Health Check Summary: ${PASS} Passed, ${FAIL} Failed"
echo "============================================================"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
