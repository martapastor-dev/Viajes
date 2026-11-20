# Búsqueda de vivienda (Fotocasa + Pisos + Idealista)

Pipeline que filtra viviendas en venta en Madrid según los criterios de Marta
y la zona de accesibilidad de Hestia.

## Reglas

- Coste real = precio anuncio × (1 + comisión): Redpiso 4,84%, otras
  inmobiliarias 3,63%, particular 0%. Todos los límites se aplican al coste real.
- Precio efectivo ≤ 260.000/0,85 = 305.882 € (o 295.882 € sin calefacción).
- ≤ 3.800 €/m² efectivos, ≥ 70 m².
- Excluir: bajos, semisótanos, ocupadas/okupas, nuda propiedad, alquiladas,
  subastas, "no se puede visitar", solo inversores.
- Ascensor obligatorio a partir de la 3ª planta.
- Zona: celda válida de `zona_final.json` (TP ≤40' a Alonso Martínez y
  ≤12' andando a metro/cercanías) ∩ polígono de `coche25.json`
  (≤25' en coche a CGS Boadilla en hora punta).

## Pipeline

`run_daily.sh` → scrape_fotocasa.py → filtra.py → scrape_pisos.py →
pisos_details.py (caché por id) → pisos_filtra.py → build_page.py
(genera index.html + items.json).

Assets: zona_final.json (rejilla de celdas válidas), coche25.json (isócrona
de coche), stop_names.json (nombres GTFS de estaciones).

## Idealista

Idealista banea la IP de datacenter (DataDome): hay que scrapearlo desde una
IP residencial — ver prompt para Devin local en la conversación de Marta.
