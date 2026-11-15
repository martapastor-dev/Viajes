#!/usr/bin/env bash
# Pipeline: Fotocasa + Pisos.com -> filtros -> index.html (buscar en idealista aparte)
set -e
cd "$(dirname "$0")"
python3 scrape_fotocasa.py
python3 filtra.py | tail -3
python3 scrape_pisos.py
python3 pisos_details.py
python3 pisos_filtra.py
python3 build_page.py
echo "PIPELINE_OK"
