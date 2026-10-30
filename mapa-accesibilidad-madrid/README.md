# Accesibilidad a Metro y Cercanías · Madrid

Aplicación local para analizar dónde comprar vivienda según la accesibilidad andando a las estaciones
de transporte público. Calcula **isócronas peatonales reales** (no círculos) desde los accesos de cada
estación y permite filtrar por red, línea, estación y ámbito geográfico, incluido
**"estaciones a ≤ 30 min en coche de la Ciudad Financiera del Banco Santander (Boadilla)"**, que es el
ámbito por defecto.

## Puesta en marcha

Requisitos: Python 3.10 o superior. Unos 2 GB de RAM libres y ~300 MB de disco para los datos.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e .
python -m accesibilidad.pipeline     # descarga y prepara los datos (~1-2 min la primera vez)
streamlit run app.py                 # abre http://localhost:8501
```

`python -m accesibilidad.pipeline --force` vuelve a descargar los datos del CRTM y de OpenStreetMap y lo
recalcula todo (por ejemplo, una vez al mes).

## Qué hace

| Control | Opciones |
|---|---|
| Red de transporte | Metro, Cercanías (por defecto) y Metro Ligero |
| Ámbito | A X min en coche de un punto (por defecto: Ciudad Financiera, 30 min), Comunidad de Madrid, municipio de Madrid, municipios seleccionados, zona dibujada en el mapa o subida como GeoJSON |
| Coche (ámbito) | minutos, sentido (desde/hacia el punto), factor de tráfico, cambiar el punto buscando una dirección |
| Filtros | líneas concretas y estaciones individuales |
| A pie | 5, 10, 15 y 20 min (varios a la vez), velocidad de 3 a 7 km/h |
| Tipo de área | isócrona por la red peatonal o círculo de radio fijo (para comparar) |
| Solapes | zonas cubiertas por 2, 3 o 4+ estaciones para el tiempo elegido |
| Viviendas | importar CSV/Excel, estaciones y líneas accesibles desde cada vivienda, €/m², comparativa por municipio, indicador experimental |
| Exportar | mapa HTML, áreas y solapes en GeoJSON, estaciones y viviendas en CSV/GeoJSON |

Bicicleta y coche como modo de desplazamiento hasta la estación aparecen como "próximamente".

### Viviendas

El fichero puede tener columnas `titulo`, `direccion`, `lat`, `lon`, `precio`, `superficie`, `url`
(también se reconocen nombres como `latitud`, `longitud`, `price`, `m2`...). Si no hay coordenadas se
geocodifica la dirección con Nominatim (1 petición por segundo, con caché). Hay un ejemplo con datos
ficticios en `examples/viviendas_ejemplo.csv`.

El **indicador experimental** combina proximidad a la estación más cercana, número de estaciones,
número de líneas y disponibilidad de Metro y Cercanías, con pesos ajustables. Es orientativo y no está
validado; los servicios (supermercados, salud, colegios, zonas verdes) quedan para una fase posterior.

## Datos y método

- **Transporte**: servicios *Datos abiertos — Elementos de la Red* del CRTM (`M4_Red` Metro,
  `M5_Red` Cercanías, `M10_Red` Metro Ligero): estaciones, **accesos** y tramos. Se usan en lugar de los
  GTFS porque están más actualizados (el GTFS de Metro publicado no incluye la línea 3) y tienen los
  accesos de las tres redes. Licencia: <https://www.crtm.es/licencia-de-uso>.
- **Calles**: extracto OSM de Geofabrik para la Comunidad de Madrid (© colaboradores de OpenStreetMap,
  ODbL). Se leen con `pyosmium` aplicando los mismos filtros que las redes `walk` y `drive` de OSMnx.
  Con un solo fichero no hay límites de peticiones de Overpass y el proceso es reproducible.
- **Isócronas**: el pipeline hace un Dijkstra por estación desde todos sus accesos hasta 20 min a 7 km/h
  y guarda la distancia a cada nodo. La app convierte ese alcance en polígonos para cualquier tiempo y
  velocidad (calles alcanzables, incluidos tramos parciales, con un pasillo de 35 m y patios de manzana
  rellenos) y los guarda en caché en `data/cache/`. Cambiar el tiempo o la velocidad no recorre la red de
  nuevo.
- **Coche**: red viaria dirigida con velocidades sin tráfico al estilo OSRM (80 % del `maxspeed` o un
  valor típico por tipo de vía). El factor de tráfico multiplica los tiempos.
- **Viviendas**: como la red peatonal es simétrica, se reutiliza el alcance de cada estación. No hace
  falta otro cálculo por vivienda.

### Limitaciones

- Son estimaciones: no tienen en cuenta semáforos, pendientes, esperas ni el recorrido dentro de la
  estación, y el tiempo en coche no incluye tráfico real.
- OpenStreetMap puede tener pasos peatonales incompletos o desactualizados.
- Las estaciones sin accesos publicados (algunas de Metro Ligero) usan un único punto.

## Estructura

```
app.py                         interfaz Streamlit
src/accesibilidad/
  config.py                    rutas, redes, parámetros y punto de referencia por defecto
  transit.py                   descarga y normalización de estaciones, accesos y líneas (CRTM)
  download.py / osm.py         extracto OSM -> tablas de nodos/aristas a pie y en coche, municipios
  graph.py                     grafos (scipy), encaje de puntos, Dijkstra
  isochrones.py                alcance por estación, polígonos, caché, círculos y solapes
  drive.py                     ámbito por tiempo en coche
  housing.py                   importación de viviendas, accesibilidad e indicador experimental
  mapping.py                   capas Folium
  pipeline.py                  proceso de preparación de datos
tests/                         pruebas (pytest)
```

### Añadir redes (EMT, interurbanos)

Las redes de autobús usan el mismo esquema de servicio del CRTM (`M6_Red`, `M8_Red`). Para añadirlas basta
con poner `available=True` en `config.TRANSIT_NETWORKS` y ejecutar `python -m accesibilidad.pipeline --force`.
Tienen miles de paradas, así que conviene revisar el rendimiento del mapa antes de activarlas por defecto.

### Alternativa con OSMnx/Overpass

Si se prefiere descargar la red con OSMnx (`ox.graph_from_polygon(..., network_type="walk")`), basta con
convertir el grafo a las mismas tablas `nodes.parquet` (x, y en EPSG:25830) y `walk_edges.parquet`
(u, v, length). El resto del proceso no cambia.
