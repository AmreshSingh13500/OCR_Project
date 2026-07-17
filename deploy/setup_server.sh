#!/bin/bash
# [MODULE]   deploy/setup_server.sh
# [TASK]     T2.1 — Smart PDF detection (Step 2b)
#            T6.1 — Server provisioning script (Phase 6)
# [SUBTASKS] T2.1.4 document/install poppler-utils system dependency
#            T6.1.1 install system deps, create service user, venv + pip install
#            T6.1.2 firewalld (allow 22 + 443 only) + certbot port-80 renewal hooks
#            T6.1.3 warm CLIP + PaddleOCR weights into the ocrsvc cache
# [SUMMARY]  AlmaLinux 9 server bootstrap / provisioning script for the OCR microservice.
#            Installs every system dependency (python3.12, poppler-utils, nginx, the OpenCV
#            runtime libs paddleocr transitively needs, and certbot), creates the
#            unprivileged `ocrsvc` service user, and builds the project virtualenv from the
#            pinned requirements.txt. Then configures firewalld to permit only SSH (22) and
#            HTTPS (443), and installs certbot renewal hooks that open port 80 transiently
#            only during HTTP-01 renewal (T6.1.2). Finally warms the CLIP + PaddleOCR model
#            weights into the ocrsvc cache via scripts/warmup_models.py (T6.1.3) so the
#            first request after deploy isn't slow. Idempotent — safe to re-run. Designed to
#            run unattended to completion on a fresh AlmaLinux 9 VM (T6.1 AC).
#            DEPLOY-TARGET NOTE: IMPLEMENTATION_PLAN.md's PHASE 6 heading still reads
#            "Ubuntu Dedicated Server" (apt / UFW / libgl1), but the recorded project
#            decision (TASKS.md §5, 2026-07-17 T6.1/T6.2) supersedes that wording — the
#            target is AlmaLinux 9, so this script uses dnf (not apt), firewalld (not UFW,
#            handled in T6.1.2), python3.12 (appstream), and mesa-libGL/glib2 (not libgl1).
#            No app/ code changes result — application code is OS-portable.
# [PLAN]     IMPLEMENTATION_PLAN.md §4 → T2.1.4, T6.1.1, T6.1.2, T6.1.3
# [HISTORY]  2026-07-17  T2.1.4  initial poppler-utils install step (apt-get)
#            2026-07-18  T6.1.1  full AlmaLinux 9 provisioning: migrate apt-get->dnf,
#                                 add python3.12/nginx/OpenCV-runtime-libs/certbot, create
#                                 ocrsvc service user, build venv + pip install
#                                 -r requirements.txt; set SELinux httpd_can_network_connect
#                                 for the T6.2 nginx->gunicorn proxy (TASKS.md §5 AlmaLinux
#                                 decision, consequences #1-#5)
#            2026-07-18  T6.1.2  firewalld (allow 22+443 only, default-deny) instead of UFW
#                                 (TASKS.md §5 #4); certbot HTTP-01 renewal hooks that open
#                                 port 80 transiently then close it; enable
#                                 certbot-renew.timer
#            2026-07-18  T6.1.3  run scripts/warmup_models.py as ocrsvc to pre-cache the
#                                 CLIP + PaddleOCR weights at the end of provisioning
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

# [T6.1.2] Firewall — firewalld (AlmaLinux default; UFW is Debian/Ubuntu, TASKS.md §5 #4).
# Default-deny incoming (the public zone rejects anything not explicitly opened) with
# exactly 22/tcp + 443/tcp allowed, matching the PRD "only 22 and 443" rule. Port 80 is
# deliberately NOT permanently open — it's opened transiently only during certbot HTTP-01
# renewal by the hooks below. Ports (not the ssh/https service aliases) are used so
# `firewall-cmd --list-ports` reads exactly "22/tcp 443/tcp", matching the AC literally.
echo "==> Configuring firewalld (allow 22 + 443 only)"
systemctl enable --now firewalld
firewall-cmd --permanent --zone=public --add-port=22/tcp
firewall-cmd --permanent --zone=public --add-port=443/tcp
# Drop the services AlmaLinux pre-seeds into the public zone so nothing beyond the two
# ports above stays reachable (idempotent — ignore if a service is already absent).
for svc in ssh cockpit dhcpv6-client; do
    firewall-cmd --permanent --zone=public --remove-service="${svc}" 2>/dev/null || true
done
firewall-cmd --reload

# [T6.1.2] certbot renewal hooks. The cert is issued once with the --standalone
# authenticator (nginx listens on 443 only, so certbot can bind port 80 during renewal
# without a conflict). Because 80 stays firewalled the rest of the time, these global
# hooks open it just for the renewal window and close it again afterwards — the transient
# HTTP-01 window called for in plan T6.1.2. The firewall changes are runtime-only (no
# --permanent) so a reload/reboot can never leave port 80 stuck open.
echo "==> Installing certbot port-80 renewal hooks"
install -d /etc/letsencrypt/renewal-hooks/pre /etc/letsencrypt/renewal-hooks/post
cat > /etc/letsencrypt/renewal-hooks/pre/open-port-80.sh <<'HOOK'
#!/bin/bash
# [T6.1.2] Open port 80 transiently for certbot HTTP-01 standalone renewal.
set -euo pipefail
firewall-cmd --add-port=80/tcp
HOOK
cat > /etc/letsencrypt/renewal-hooks/post/close-port-80.sh <<'HOOK'
#!/bin/bash
# [T6.1.2] Close port 80 again after certbot renewal completes.
set -euo pipefail
firewall-cmd --remove-port=80/tcp || true
HOOK
chmod +x /etc/letsencrypt/renewal-hooks/pre/open-port-80.sh \
         /etc/letsencrypt/renewal-hooks/post/close-port-80.sh

# [T6.1.2] Enable certbot's auto-renewal timer (shipped by the EPEL certbot package) so
# the hooks above actually fire on schedule. Ignored if the timer unit isn't present.
systemctl enable --now certbot-renew.timer 2>/dev/null || true

echo "==> T6.1.2 firewall + renewal hooks configured: 22/tcp + 443/tcp open, port 80 transient."

# [T6.1.3] Pre-download CLIP + PaddleOCR weights into the ocrsvc cache so the first real
# request after deploy doesn't pay the multi-hundred-MB download mid-pipeline. Run as
# ${SERVICE_USER} with HOME=${APP_DIR} (so the HuggingFace/PaddleOCR caches land under the
# service user's home) and cwd=${REPO_ROOT} (so `-m scripts.warmup_models` resolves). The
# warmup script sets placeholder env vars itself, so it runs fine before /etc/ocr-service/env
# exists (that file is T6.2's deliverable).
echo "==> Warming up model weights (CLIP + PaddleOCR)"
runuser -u "${SERVICE_USER}" -- env HOME="${APP_DIR}" \
    bash -c "cd '${REPO_ROOT}' && exec '${VENV_DIR}/bin/python' -m scripts.warmup_models"

echo "==> T6.1.3 model warmup complete."
echo "==> Server provisioning finished."
