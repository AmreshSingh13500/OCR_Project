#!/bin/bash
# [MODULE]   deploy/setup_server.sh
# [TASK]     T2.1 — Smart PDF detection (Step 2b)
# [SUBTASKS] T2.1.4 document/install poppler-utils system dependency
# [SUMMARY]  Ubuntu server bootstrap script. Currently installs only the poppler-utils
#            system dependency required by pdf2image (T2.1.3's convert_scanned_pdf, in
#            app/pipeline/pdf_handler.py) to rasterize scanned PDFs. The full provisioning
#            script — python3.11+, python3-venv, nginx, libgl1, certbot, service user
#            `ocrsvc`, venv + pip install — is T6.1.1's deliverable and will extend this
#            file in place per CODING_RULES.md Rule 3, not replace it.
# [PLAN]     IMPLEMENTATION_PLAN.md §4 → T2.1.4
# [HISTORY]  2026-07-17  T2.1.4  initial poppler-utils install step
set -euo pipefail

# [T2.1.4] poppler-utils provides pdftoppm, which pdf2image shells out to for scanned-PDF
# rasterization (app/pipeline/pdf_handler.py convert_scanned_pdf). Without it that call
# fails at the first scanned PDF processed.
apt-get update
apt-get install -y poppler-utils
