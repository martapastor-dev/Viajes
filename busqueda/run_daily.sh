#!/usr/bin/env bash
# Pipeline diario: Fotocasa + Pisos.com -> filtros Marta -> casas/index.html
set -e
cd "$(dirname "$0")"
python3 zone_maybe.py
python3 scrape_fotocasa.py
python3 filtra.py | tail -3
python3 scrape_pisos.py
python3 pisos_details.py
python3 scrape_tecnocasa.py
python3 tc_details.py
python3 pisos_filtra.py
python3 build_page.py
cd casas && git add -A && git -c user.email=devin@cognition.ai -c user.name=Devin commit -qm "Datos $(date +%F)" || true
echo "PIPELINE_OK"
