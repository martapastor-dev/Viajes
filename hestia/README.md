# Hestia — mapa de accesibilidad a transporte público

App web interactiva que estima **tiempos reales de acceso a transporte público
en Madrid** (Metro, Metro Ligero y Cercanías) combinando:

- **Grafo GTFS del CRTM** — tiempos de trayecto por horario programado,
  espera media por línea (headway punta de mañana), penalización de
  transbordo (4 min) y acceso a andén (3 min), con factor de calibración ×0,9.
- **Isócronas peatonales reales (Valhalla)** precalculadas por estación y
  minuto (`walk_cache/`), en vez del clásico círculo haversine — respetan
  barreras urbanas (M-30, vías, río).
- **Isócronas en coche** opcionales vía Valhalla local (puerto 8002).

## Uso

Abrir `dinamico/index.html` en el navegador (no necesita servidor).

- Crea puntos de tipo **Destino** (🚶 andando, 🚗 coche, 🚇 TP, 🚇+🚗)
  o **Punto de recogida** (origen del modo 🚇+🚗).
- Cada punto dibuja su sombreado de tiempo; `∩ Intersección` muestra la
  zona común a las capas activas.
- **💾 Plantilla** guarda la configuración en el navegador;
  **🏠 Idealista** exporta la zona sombreada como área de búsqueda.

El sombreado TP de un destino es la unión de las isócronas peatonales de
cada estación cuyo tiempo TP hasta el destino deja margen de andar
(`minutos − T[estación]`), más un círculo conservador de andar directo.

## Estructura

```
dinamico/           App web (index.html + datos generados .js)
gtfs/               Feeds GTFS oficiales CRTM (metro, ligero, cercanías)
walk_cache/         Isócronas peatonales Valhalla por estación (JSON, 1-20 min)
mapa.html           Mapa folium estático con capas inyectadas
accesos_tp.json / isocronas_tp.json   Datos del mapa estático
```

## Regenerar datos (opcional)

```bash
pip install -r requirements.txt

python exportar_datos_dinamico.py   # GTFS -> dinamico/datos_tp.js + metro_sombra.js
python exportar_walk_real.py      # walk_cache/ -> walk_real.js, walk_minutes.js, walk_polys.js
python computar_isocronas_tp.py   # GTFS -> isocronas_tp.json (mapa estático)
python inyectar_capas_tp.py       # isocronas_tp.json -> capas en mapa.html
```

Los datos generados ya están incluidos; los scripts solo hacen falta si
cambian los GTFS o la caché de isócronas. `exportar_walk_real.py` trabaja
solo sobre `walk_cache/` (sin red).
