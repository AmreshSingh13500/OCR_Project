#!/bin/bash
# [MODULE]   deploy/setup_server.sh
# [TASK]     T2.1 — Smart PDF detection (Step 2b)
#            T6.1 — Server provisioning script (Phase 6)
# [SUBTASKS] T2.1.4 document/install poppler-utils system dependency
#            T6.1.1 install system deps, create service user, venv + pip install
# [SUMMARY]  AlmaLinux 9 server bootstrap / provisioning script for the OCR microservice.
#            Installs every system dependency (python3.12, poppler-utils, nginx, the OpenCV
#            runtime libs paddleocr transitively needs, and certbot), creates the
#            unprivileged `ocrsvc` service user, and builds the project virtualenv from the
#            pinned requirements.txt. Idempotent — safe to re-run. Designed to run
#            unattended to completion on a fresh AlmaLinux 9 VM (T6.1 AC).
#            DEPLOY-TARGET NOTE: IMPLEMENTATION_PLAN.md's PHASE 6 heading still reads
#            "Ubuntu Dedicated Server" (apt / UFW / libgl1), but the recorded project
#            decision (TASKS.md §5, 2026-07-17 T6.1/T6.2) supersedes that wording — the
#            target is AlmaLinux 9, so this script uses dnf (not apt), firewalld (not UFW,
#            handled in T6.1.2), python3.12 (appstream), and mesa-libGL/glib2 (not libgl1).
#            No app/ code changes result — application code is OS-portable.
# [PLAN]     IMPLEMENTATION_PLAN.md §4 → T2.1.4, T6.1.1
# [HISTORY]  2026-07-17  T2.1.4  initial poppler-utils install step (apt-get)
#            2026-07-18  T6.1.1  full AlmaLinux 9 provisioning: migrate apt-get->dnf,
#                                 add python3.12/nginx/OpenCV-runtime-libs/certbot, create
#                                 ocrsvc service user, build venv + pip install
#                                 -r requirements.txt; set SELinux httpd_can_network_connect
#                                 for the T6.2 nginx->gunicorn proxy (TASKS.md §5 AlmaLinux
#                                 decision, consequences #1-#5)
set -euo pipefail

# --- Provisioning parameters -------------------------------------------------
SERVICE_USER="ocrsvc"
APP_DIR="/opt/ocr-service"
VENV_DIR="${APP_DIR}/.venv"
PYTHON_BIN="python3.12"

# This script lives in <repo>/deploy, so the repo root (with requirements.txt) is its
# parent — resolvable whether run from a git checkout or a copied deploy/ directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "${SCRIPT_DIR}")"

if [[ "${EUID}" -ne 0 ]]; then
    echo "This provisioning script must run as root (use sudo)." >&2
    exit 1
fi

# [T6.1.1] Enable the repos the packages below come from. EPEL provides certbot + its
# nginx plugin; several EPEL packages depend on CRB (CodeReady Builder — named 'crb' on
# AlmaLinux 9, 'powertools' on 8). dnf-plugins-core provides `dnf config-manager`.
echo "==> Enabling EPEL + CRB repositories"
dnf install -y dnf-plugins-core epel-release
dnf config-manager --set-enabled crb 2>/dev/null \
    || dnf config-manager --set-enabled powertools 2>/dev/null \
    || true
dnf makecache

# [T6.1.1] System packages. Notes on the non-obvious ones:
#   poppler-utils     [T2.1.4] pdftoppm — pdf2image shells out to it to rasterize scanned
#                     PDFs (app/pipeline/pdf_handler.py convert_scanned_pdf). Same package
#                     name in AlmaLinux repos as in Ubuntu (TASKS.md §5 consequence #1).
#   mesa-libGL,glib2  paddleocr transitively installs the NON-headless opencv wheels even
#                     though requirements.txt pins opencv-python-headless; those need
#                     libGL.so.1 + libgthread-2.0 on a GUI-less server or import dies with
#                     "libGL.so.1: cannot open shared object file" (TASKS.md §5 #3).
#   certbot + plugin  from EPEL (TASKS.md §5 #4); actual cert issuance/renewal wiring is
#                     T6.1.2's firewall + renewal-hook step.
echo "==> Installing system packages"
dnf install -y \
    python3.12 \
    poppler-utils \
    nginx \
    mesa-libGL \
    glib2 \
    certbot \
    python3-certbot-nginx

# [T6.1.1] SELinux ships enforcing on AlmaLinux 9 (TASKS.md §5 #2). The T6.2 nginx reverse
# proxy connects out to gunicorn on 127.0.0.1:8000; without this boolean SELinux silently
# blocks that socket and nginx returns 502 while the app logs look clean. Persist it now so
# the proxy works the moment T6.2 lands. No-op on a system where SELinux is disabled.
if command -v setsebool >/dev/null 2>&1 && [[ "$(getenforce 2>/dev/null || echo Disabled)" != "Disabled" ]]; then
    echo "==> Allowing httpd -> gunicorn network connections (SELinux)"
    setsebool -P httpd_can_network_connect 1
fi

# [T6.1.1] Unprivileged system user the gunicorn service (T6.2.1) runs as. No login shell;
# home = APP_DIR so the model weights the warmup step (T6.1.3) pulls land under a stable,
# service-owned HOME cache instead of root's.
if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
    echo "==> Creating service user ${SERVICE_USER}"
    useradd --system --home-dir "${APP_DIR}" --create-home --shell /sbin/nologin "${SERVICE_USER}"
fi

# [T6.1.1] Project virtualenv built from the pinned requirements as ${SERVICE_USER}, so the
# whole tree is service-owned from the start (torch/paddlepaddle are the CPU builds pinned
# in requirements.txt). APP_DIR is expected to hold the deployed app code (git checkout);
# the systemd unit's WorkingDirectory (T6.2.1) points here.
echo "==> Building virtualenv at ${VENV_DIR}"
install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" "${APP_DIR}"
runuser -u "${SERVICE_USER}" -- "${PYTHON_BIN}" -m venv "${VENV_DIR}"
runuser -u "${SERVICE_USER}" -- "${VENV_DIR}/bin/python" -m pip install --upgrade pip
runuser -u "${SERVICE_USER}" -- "${VENV_DIR}/bin/pip" install -r "${REPO_ROOT}/requirements.txt"

echo "==> T6.1.1 provisioning complete: system deps installed, ${SERVICE_USER} created, venv ready."
