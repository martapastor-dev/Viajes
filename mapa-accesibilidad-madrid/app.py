"""Aplicación Streamlit: mapa de accesibilidad a Metro y Cercanías en Madrid.

streamlit run app.py
"""

from __future__ import annotations

import json
import re

import geopandas as gpd
import pandas as pd
import shapely
import streamlit as st
from shapely.geometry import shape
from streamlit_folium import st_folium

from accesibilidad import config, drive, graph, housing, isochrones, mapping, pipeline

st.set_page_config(page_title="Accesibilidad a estaciones · Madrid", layout="wide", page_icon="🚇")

SCOPE_DRIVE = "A X minutos en coche de un punto"
SCOPE_REGION = "Toda la Comunidad de Madrid"
SCOPE_CITY = "Municipio de Madrid"
SCOPE_MUNIS = "Municipios seleccionados"
SCOPE_CUSTOM = "Zona personalizada"
AREA_ISO = "Isócrona (red peatonal real)"
AREA_CIRCLE = "Círculo (radio fijo, comparación)"
MAX_INDIVIDUAL_POLYGONS = 80


# --------------------------------------------------------------------------- datos


@st.cache_resource(show_spinner="Cargando datos de transporte...")
def load_transit():
    stations = gpd.read_parquet(pipeline.processed(pipeline.STATIONS_FILE))
    stations["lines"] = stations["lines"].map(list)
    access = gpd.read_parquet(pipeline.processed(pipeline.ACCESS_FILE))
    lines = gpd.read_parquet(pipeline.processed(pipeline.LINES_FILE))
    bounds = gpd.read_file(pipeline.processed(pipeline.BOUNDARIES_FILE))
    places_path = pipeline.processed(pipeline.PLACES_FILE)
    places = gpd.read_parquet(places_path) if places_path.exists() else None
    return stations, access, lines, bounds, places, pipeline.load_meta()


@st.cache_resource(show_spinner="Cargando la red peatonal y viaria (solo la primera vez)...")
def load_graphs():
    nodes = graph.load_nodes()
    wg = graph.load_walk_graph(nodes=nodes)
    dg = graph.load_drive_graph(nodes=nodes)
    wg.snap_xy(0, 0)  # construye los índices espaciales
    dg.snap_xy(0, 0)
    reach = isochrones.ReachIndex.load(pipeline.processed(isochrones.REACH_FILE))
    return wg, dg, reach, isochrones.IsochroneBuilder(wg, reach)


@st.cache_resource(show_spinner="Aplicando el tráfico de hora punta a la red viaria...", max_entries=2)
def rush_graph(lon: float, lat: float) -> graph.DriveGraph:
    nodes = graph.load_nodes()
    edges = pd.read_parquet(pipeline.processed("drive_edges.parquet"))
    factors = drive.rush_hour_factors(edges, nodes, config.RUSH_HOUR, (lon, lat))
    return graph.DriveGraph(nodes, edges.assign(speed_kmh=edges["speed_kmh"] / factors))


def _traffic_summary() -> str:
    p = config.RUSH_HOUR
    names = {1: "M-30", 2: "M-40", 3: "M-50", 4: "otras autovías", 5: "vías principales", 6: "resto de calles"}
    fmt = lambda f: f"×{f:.2f}".rstrip("0").rstrip(".").replace(".", ",")  # noqa: E731
    parts = [f"{names[c]} {fmt(f)}" for c, f in p.road_factors]
    rings = [f"calles a ≤{r / 1000:.0f} km de Sol {fmt(f)}" for r, f in sorted(p.urban_rings_m)]
    parts += rings + [f"≤{p.near_origin_m / 1000:.0f} km del punto al menos {fmt(p.near_origin_factor)}"]
    if p.fixed_minutes:
        parts.append(f"+{p.fixed_minutes:.0f} min fijos")
    return ", ".join(parts)


def _drive_graph(lon: float, lat: float, rush: bool) -> graph.DriveGraph:
    return rush_graph(lon, lat) if rush else load_graphs()[1]


@st.cache_data(show_spinner="Calculando tiempos en coche...", max_entries=20)
def drive_minutes(lon: float, lat: float, towards: bool, rush: bool) -> pd.Series:
    dg = _drive_graph(lon, lat, rush)
    stations = load_transit()[0]
    node_min = drive.drive_times(dg, lon, lat, config.SETTINGS.drive_max_minutes, towards)
    extra = config.RUSH_HOUR.fixed_minutes if rush else 0.0
    return pd.Series(drive.station_drive_minutes(dg, stations, node_min) + extra, index=stations["station_id"].values)


@st.cache_data(show_spinner="Calculando el área alcanzable en coche...", max_entries=20)
def drive_area_wkb(lon: float, lat: float, towards: bool, rush: bool, minutes: float) -> bytes:
    """Área a ≤`minutes` en coche (ya dividido por el ajuste extra); incluye los minutos fijos de hora punta."""
    dg = _drive_graph(lon, lat, rush)
    node_min = drive.drive_times(dg, lon, lat, config.SETTINGS.drive_max_minutes, towards)
    budget = minutes - (config.RUSH_HOUR.fixed_minutes if rush else 0.0)
    area = drive.drive_area(dg, node_min, budget)
    return area.geometry.iloc[0].wkb if len(area) else b""


@st.cache_data(show_spinner="Buscando dirección...", max_entries=50)
def geocode(text: str):
    from geopy.geocoders import Nominatim

    loc = Nominatim(user_agent="mapa-accesibilidad-madrid").geocode(f"{text}, Comunidad de Madrid, España")
    return (loc.latitude, loc.longitude, loc.address) if loc else None


def progress_cb(label: str):
    """Barra de progreso que solo aparece si hay trabajo y desaparece al terminar."""
    slot = st.empty()

    def cb(done: int, total: int):
        if done >= total:
            slot.empty()
        else:
            slot.progress(done / max(total, 1), text=f"{label} ({done}/{total})")

    return cb


# --------------------------------------------------------------------------- preparación

MOBILE_CSS = """
<style>
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"] {padding: 2.5rem 0.75rem 1rem !important;}
  h1 {font-size: 1.45rem !important; padding: 0 0 0.25rem !important;}
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) {flex-wrap: wrap !important; gap: 0.25rem 1rem !important;}
  [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"] {
    flex: 1 1 40% !important; min-width: 40% !important; width: auto !important;
  }
  [data-testid="stMetricValue"] {font-size: 1.2rem !important;}
  [data-testid="stMetricLabel"] p {font-size: 0.75rem !important;}
  iframe[title="streamlit_folium.st_folium"] {height: 68vh !important;}
}
</style>
"""
st.markdown(MOBILE_CSS, unsafe_allow_html=True)
st.title("Accesibilidad a Metro y Cercanías · Madrid")

if not pipeline.is_ready():
    st.warning("Todavía no se han preparado los datos (descarga del CRTM y de OpenStreetMap y cálculo del alcance a pie).")
    st.code("python -m accesibilidad.pipeline", language="bash")
    if st.button("Preparar datos ahora (unos minutos)", type="primary"):
        with st.spinner("Descargando y procesando datos..."):
            pipeline.run()
        st.rerun()
    st.stop()

stations_all, access_all, lines_all, bounds, places_all, meta = load_transit()
wg, dg, reach, builder = load_graphs()
munis = bounds[bounds.admin_level == 8].sort_values("name")
region = bounds[bounds.admin_level == 4]

# --------------------------------------------------------------------------- barra lateral

sb = st.sidebar
sb.header("Red de transporte")
networks = [n for n in config.available_networks()]
selected_modes = [n.key for n in networks if sb.checkbox(n.label, value=n.enabled_by_default, key=f"net_{n.key}")]
sb.caption("EMT y autobuses interurbanos: previstos para una versión posterior.")

sb.header("Ámbito geográfico")
scope_kind = sb.radio("Ámbito", [SCOPE_DRIVE, SCOPE_REGION, SCOPE_CITY, SCOPE_MUNIS, SCOPE_CUSTOM], label_visibility="collapsed")
if "origin" not in st.session_state:
    o = config.DEFAULT_ORIGIN
    st.session_state.origin = (o.lat, o.lon, o.name)
origin_lat, origin_lon, origin_name = st.session_state.origin
drive_limit = factor = None
towards = False
rush = False
selected_munis: list[str] = []
drive_bands_sel: list[int] = []
if scope_kind == SCOPE_DRIVE:
    sb.markdown(f"**Punto de referencia:** {origin_name}")
    with sb.expander("Cambiar punto de referencia"):
        query = st.text_input("Dirección o lugar", placeholder="p. ej. Puerta del Sol")
        if st.button("Buscar") and query:
            found = geocode(query)
            if found:
                st.session_state.origin = found
                st.rerun()
            st.error("No se encontró la dirección.")
        if st.button("Volver a CGS"):
            o = config.DEFAULT_ORIGIN
            st.session_state.origin = (o.lat, o.lon, o.name)
            st.rerun()
    drive_limit = sb.slider("Minutos en coche (máximo)", 5, config.SETTINGS.drive_max_minutes, config.DEFAULT_DRIVE_MINUTES, 5)
    towards = sb.radio("Sentido del viaje", ["Desde el punto", "Hacia el punto"], index=1, horizontal=True) == "Hacia el punto"
    rush = (
        sb.radio(
            "Tráfico",
            [config.RUSH_HOUR.label, "Sin tráfico"],
            help="Hora punta: ralentización aproximada por tipo de vía y zona (M-30, M-40, calles del centro...) "
            "calibrada a mano con Google Maps; no está medida con datos reales de tráfico.",
        )
        == config.RUSH_HOUR.label
    )
    drive_bands_sel = [b for b in config.DEFAULT_DRIVE_BANDS if b <= drive_limit]
    factor = sb.slider(
        "Ajuste extra de tiempos",
        0.7,
        1.5,
        1.0,
        0.05,
        help="Multiplica los tiempos en coche calculados (para calibrar con Google Maps, por ejemplo).",
    )
elif scope_kind == SCOPE_MUNIS:
    selected_munis = sb.multiselect("Municipios", munis["name"].tolist(), default=["Madrid"])
elif scope_kind == SCOPE_CUSTOM:
    sb.caption("Dibuja un polígono o rectángulo en el mapa (herramientas de la izquierda) o sube un GeoJSON.")
    up = sb.file_uploader("GeoJSON de la zona", type=["geojson", "json"])
    if up is not None:
        gj = json.load(up)
        feats = gj.get("features", [gj])
        st.session_state.custom_zone = shapely.union_all([shape(f.get("geometry", f)) for f in feats]).wkb
    if st.session_state.get("custom_zone") and sb.button("Borrar zona personalizada"):
        st.session_state.custom_zone = None
        st.rerun()

excluded_munis = sb.multiselect(
    "Excluir municipios",
    munis["name"].tolist(),
    default=[n for n in config.DEFAULT_EXCLUDED_MUNICIPALITIES if n in set(munis["name"])],
)
station_names = sorted(stations_all["name"].unique())
excluded_stations = sb.multiselect(
    "Excluir estaciones",
    station_names,
    default=[n for n in config.DEFAULT_EXCLUDED_STATIONS if n in set(station_names)],
)

sb.header("Desplazamiento a pie")
travel_mode = sb.radio("Medio", ["Andando", "Bicicleta (próximamente)", "Coche (próximamente)"])
if travel_mode != "Andando":
    sb.info("De momento solo se calculan áreas andando. Bicicleta y coche se añadirán con su propia red y método.")
times = sb.pills("Tiempo máximo andando (min)", config.SETTINGS.walk_times_min, selection_mode="multi", default=[5, 10, 15])
times = sorted(times or [10])
speed = sb.slider(
    "Velocidad andando (km/h)",
    config.SETTINGS.walk_speed_kmh_min,
    config.SETTINGS.walk_speed_kmh_max,
    config.SETTINGS.walk_speed_kmh_default,
    0.1,
)
area_kind = sb.radio("Tipo de área", [AREA_ISO, AREA_CIRCLE])
show_overlaps = sb.checkbox("Mostrar zonas donde se solapan varias estaciones", value=False)
clip_to_scope = sb.checkbox(
    "Recortar las áreas andando al ámbito",
    value=True,
    help="Solo se pintan las partes de las áreas andando que están dentro del ámbito (p. ej. la zona roja en coche).",
)
overlap_minutes = sb.selectbox("Solapes para el tiempo de", times, index=min(1, len(times) - 1)) if show_overlaps else None

# --------------------------------------------------------------------------- filtrado de estaciones

stations = stations_all[
    stations_all["mode"].isin(selected_modes)
    & stations_all["in_region"]
    & ~stations_all["municipality"].isin(excluded_munis)
    & ~stations_all["name"].isin(excluded_stations)
].copy()
dmin = drive_minutes(origin_lon, origin_lat, towards, rush)
stations["drive_min"] = stations["station_id"].map(dmin) * (factor or 1.0)

scope_gdf = None
drive_band_gdfs: dict[int, gpd.GeoDataFrame] = {}
if scope_kind == SCOPE_DRIVE:
    stations = stations[stations["drive_min"] <= drive_limit]
    wkb = drive_area_wkb(origin_lon, origin_lat, towards, rush, drive_limit / factor)
    if wkb:
        scope_gdf = gpd.GeoDataFrame(geometry=[shapely.from_wkb(wkb)], crs=config.CRS_METRIC)
    for band_min in drive_bands_sel:
        bw = drive_area_wkb(origin_lon, origin_lat, towards, rush, band_min / factor)
        if bw:
            drive_band_gdfs[band_min] = gpd.GeoDataFrame(geometry=[shapely.from_wkb(bw)], crs=config.CRS_METRIC)
elif scope_kind == SCOPE_CITY:
    stations = stations[stations["municipality"] == "Madrid"]
    scope_gdf = munis[munis["name"] == "Madrid"]
elif scope_kind == SCOPE_MUNIS:
    stations = stations[stations["municipality"].isin(selected_munis)]
    scope_gdf = munis[munis["name"].isin(selected_munis)]
elif scope_kind == SCOPE_CUSTOM:
    if st.session_state.get("custom_zone"):
        zone = shapely.from_wkb(st.session_state.custom_zone)
        scope_gdf = gpd.GeoDataFrame(geometry=[zone], crs=config.CRS_WGS84)
        stations = stations[stations.within(zone)]
    else:
        stations = stations.iloc[0:0]
else:
    scope_gdf = region
if scope_gdf is not None and excluded_munis:
    cut = munis[munis["name"].isin(excluded_munis)].to_crs(scope_gdf.crs).geometry.union_all()
    scope_gdf = gpd.GeoDataFrame(geometry=[scope_gdf.geometry.union_all().difference(cut)], crs=scope_gdf.crs)

line_options = sorted(
    {(m, ln) for m, ls in zip(stations["mode"], stations["lines"]) for ln in ls},
    key=lambda t: (selected_modes.index(t[0]), re.sub(r"\D", "", t[1]).zfill(3), t[1]),
)
sb.header("Filtros")
sel_lines = sb.multiselect(
    "Líneas",
    line_options,
    format_func=lambda t: f"{config.TRANSIT_NETWORKS[t[0]].label} {t[1]}",
    help="Vacío = todas las líneas.",
)
if sel_lines:
    wanted = set(sel_lines)
    stations = stations[[any((m, ln) in wanted for ln in ls) for m, ls in zip(stations["mode"], stations["lines"])]]
station_labels = {
    sid: f"{name} · {config.TRANSIT_NETWORKS[m].label} {', '.join(ls)}"
    for sid, name, m, ls in zip(stations["station_id"], stations["name"], stations["mode"], stations["lines"])
}
sel_stations = sb.multiselect(
    "Estaciones",
    sorted(station_labels, key=station_labels.get),
    format_func=station_labels.get,
    help="Vacío = todas las estaciones que cumplen los filtros.",
)
if sel_stations:
    stations = stations[stations["station_id"].isin(sel_stations)]
stations = stations.sort_values(["mode", "name"]).reset_index(drop=True)
lines_shown = lines_all[lines_all["mode"].isin(selected_modes)]
if sel_lines:
    lines_shown = lines_shown[[(m, ln) in set(sel_lines) for m, ln in zip(lines_shown["mode"], lines_shown["line"])]]

# --------------------------------------------------------------------------- áreas


def _clip(polys: gpd.GeoDataFrame, zone) -> gpd.GeoDataFrame:
    clipped = polys.to_crs(config.CRS_METRIC).assign(geometry=lambda d: d.geometry.intersection(zone))
    return clipped[~clipped.geometry.is_empty].to_crs(polys.crs)


def areas_for(minutes: int) -> gpd.GeoDataFrame:
    budget = isochrones.walk_budget_m(minutes, speed)
    if area_kind == AREA_CIRCLE:
        return isochrones.circles(stations, budget)
    return builder.get(stations["station_id"], budget, progress=progress_cb(f"Calculando isócronas de {minutes} min"))


polys = {}
if travel_mode == "Andando" and len(stations):
    polys = {m: areas_for(m) for m in times}
    if clip_to_scope and scope_gdf is not None:
        clip_zone = scope_gdf.to_crs(config.CRS_METRIC).geometry.union_all()
        polys = {m: _clip(p, clip_zone) for m, p in polys.items()}
overlaps = isochrones.overlap_zones(polys[overlap_minutes]) if show_overlaps and overlap_minutes in polys else None

tab_map, tab_st, tab_homes, tab_export, tab_info = st.tabs(
    ["Mapa", f"Estaciones ({len(stations)})", "Viviendas", "Exportar", "Datos y limitaciones"]
)

# --------------------------------------------------------------------------- viviendas (se procesa antes del mapa)

with tab_homes:
    st.subheader("Análisis de viviendas")
    st.caption(
        "Sube un CSV o Excel con columnas como `titulo`, `direccion`, `lat`, `lon`, `precio`, `superficie`, `url`. "
        "Si faltan coordenadas se geocodifica la dirección con Nominatim (OpenStreetMap)."
    )
    c1, c2 = st.columns([3, 1])
    upload = c1.file_uploader("Anuncios", type=["csv", "xlsx", "xls"])
    if c2.button("Cargar ejemplo"):
        st.session_state.homes_file = (
            "viviendas_ejemplo.csv",
            (config.PROJECT_ROOT / "examples" / "viviendas_ejemplo.csv").read_bytes(),
        )
    if upload is not None:
        st.session_state.homes_file = (upload.name, upload.getvalue())
    homes_gdf = homes_pairs = None
    if st.session_state.get("homes_file"):
        name, data = st.session_state.homes_file
        raw = housing.read_listings(data, name)
        if raw.get("lat") is None or raw["lat"].isna().any():
            if "direccion" in raw and st.checkbox("Geocodificar direcciones sin coordenadas", value=True):
                raw = housing.geocode_missing(raw, progress=progress_cb("Geocodificando"))
        home_minutes = st.select_slider(
            "Tiempo máximo andando desde la vivienda", config.SETTINGS.walk_times_min, value=max(times)
        )
        with st.expander("Pesos del indicador experimental"):
            st.warning("Indicador orientativo con fórmula y pesos provisionales. No es una medida objetiva ni validada.")
            weights = {
                k: st.slider(k.replace("_", " ").capitalize(), 0.0, 1.0, v, 0.05, key=f"w_{k}")
                for k, v in housing.DEFAULT_WEIGHTS.items()
            }
        if "lat" in raw and raw["lat"].notna().any():
            homes_gdf, homes_pairs = housing.analyze(
                raw, wg, reach, stations, isochrones.walk_budget_m(home_minutes, speed), speed, weights
            )
            st.caption(f"Estaciones consideradas: las {len(stations)} que cumplen los filtros actuales.")
            cols = [
                c
                for c in [
                    "titulo",
                    "direccion",
                    "precio",
                    "superficie",
                    "eur_m2",
                    "estacion_mas_cercana",
                    "min_a_estacion",
                    "n_estaciones",
                    "lineas",
                    "redes",
                    "indicador_experimental",
                    "url",
                ]
                if c in homes_gdf
            ]
            st.dataframe(
                homes_gdf[cols],
                width="stretch",
                hide_index=True,
                column_config={
                    "precio": st.column_config.NumberColumn("Precio (€)", format="%.0f"),
                    "superficie": st.column_config.NumberColumn("m²", format="%.0f"),
                    "eur_m2": st.column_config.NumberColumn("€/m²", format="%.0f"),
                    "min_a_estacion": st.column_config.NumberColumn("Min. a estación", format="%.1f"),
                    "indicador_experimental": st.column_config.ProgressColumn("Indicador (exp.)", min_value=0, max_value=100),
                    "url": st.column_config.LinkColumn("Anuncio"),
                },
            )
            if homes_pairs is not None and not homes_pairs.empty:
                with st.expander("Estaciones accesibles desde cada vivienda"):
                    labels = homes_gdf.get("titulo", homes_gdf.index.astype(str))
                    view = homes_pairs.assign(vivienda=homes_pairs["vivienda"].map(dict(enumerate(labels))))
                    st.dataframe(
                        view[["vivienda", "estacion", "red", "lineas", "minutos", "metros"]], width="stretch", hide_index=True
                    )
            if "municipio" not in homes_gdf:
                joined = gpd.sjoin(homes_gdf, munis[["name", "geometry"]], how="left", predicate="within")
                homes_gdf["municipio"] = joined["name"].groupby(level=0).first()
            st.markdown("**Comparativa por municipio**")
            agg = {
                "n": ("indicador_experimental", "size"),
                "indicador_medio": ("indicador_experimental", "mean"),
                "min_medio_a_estacion": ("min_a_estacion", "mean"),
            }
            if "eur_m2" in homes_gdf:
                agg["eur_m2_medio"] = ("eur_m2", "mean")
            st.dataframe(homes_gdf.groupby("municipio").agg(**agg).round(1), width="stretch")
        else:
            st.error("No hay coordenadas: añade columnas lat/lon o una columna de dirección.")

# --------------------------------------------------------------------------- mapa

with tab_map:
    if travel_mode != "Andando":
        st.info("Solo está disponible el cálculo andando en esta versión; se muestran las estaciones sin áreas.")
    c = st.columns(4)
    c[0].metric("Estaciones", len(stations))
    c[1].metric("Metro / Cercanías", f"{(stations['mode'] == 'metro').sum()} / {(stations['mode'] == 'cercanias').sum()}")
    if polys:
        biggest = polys[max(polys)]
        covered = biggest.geometry.union_all().area / 1e6 if len(biggest) else 0
        c[2].metric(
            f"Superficie a ≤{max(polys)} min", f"{covered:,.1f} km²".replace(",", "X").replace(".", ",").replace("X", ".")
        )
    if overlaps is not None and len(overlaps):
        c[3].metric(f"Con ≥2 estaciones a ≤{overlap_minutes} min", f"{overlaps.area.sum() / 1e6:,.1f} km²".replace(".", ","))

    if len(stations):
        b = stations.total_bounds
        center = ((b[1] + b[3]) / 2, (b[0] + b[2]) / 2)
    else:
        center = (40.42, -3.75)
    m = mapping.base_map(center=center, zoom=11)
    if scope_kind == SCOPE_CUSTOM:
        mapping.add_drawing(m)
    scope_label = {SCOPE_DRIVE: f"Área a ≤{drive_limit} min en coche"}.get(scope_kind, "Ámbito")
    if scope_kind != SCOPE_DRIVE or not drive_band_gdfs:
        mapping.add_scope(m, scope_gdf, scope_label, color="#d62728" if scope_kind == SCOPE_DRIVE else "#555555")
    else:
        mapping.add_drive_bands(m, drive_band_gdfs, "CGS")
    if places_all is not None:
        area = scope_gdf if scope_gdf is not None else region
        zone = area.to_crs(config.CRS_WGS84).geometry.union_all()
        mapping.add_neighbourhoods(m, places_all[places_all.within(zone)])
    mapping.add_lines(m, lines_shown)
    label = "Andando" if area_kind == AREA_ISO else "Círculo"
    mapping.add_isochrones(m, polys, stations, individual=len(stations) <= MAX_INDIVIDUAL_POLYGONS, label=label)
    if overlaps is not None:
        mapping.add_overlaps(m, overlaps, overlap_minutes)
    acc = access_all[access_all["station_id"].isin(stations["station_id"])]
    mapping.add_stations(m, stations, acc)
    if scope_kind == SCOPE_DRIVE:
        mapping.add_origin(m, origin_lat, origin_lon, origin_name)
    mapping.add_housing(m, homes_gdf)
    mapping.add_legend(m, list(polys) or times, overlaps is not None and len(overlaps) > 0)
    mapping.finish(m)
    if len(stations):
        b = stations.total_bounds
        m.fit_bounds([[b[1], b[0]], [b[3], b[2]]])
    out = st_folium(
        m,
        height=720,
        use_container_width=True,
        key="map",
        returned_objects=["all_drawings"] if scope_kind == SCOPE_CUSTOM else [],
    )
    if scope_kind == SCOPE_CUSTOM and out and out.get("all_drawings"):
        zone = shapely.union_all([shape(f["geometry"]) for f in out["all_drawings"]])
        if zone.wkb != st.session_state.get("custom_zone"):
            st.session_state.custom_zone = zone.wkb
            st.rerun()
    st.caption(
        "Las áreas andando se calculan sobre la red peatonal de OpenStreetMap desde los accesos de cada estación "
        "(o desde la estación si no hay accesos publicados). Son estimaciones: no garantizan el tiempo real de cada persona."
    )

# --------------------------------------------------------------------------- tabla de estaciones

with tab_st:
    table = pd.DataFrame(
        {
            "Estación": stations["name"],
            "Red": stations["mode"].map(lambda k: config.TRANSIT_NETWORKS[k].label),
            "Líneas": stations["lines"].map(", ".join),
            "Municipio": stations["municipality"],
            "Accesos": stations["n_accesses"],
            f"Min. en coche ({'hacia' if towards else 'desde'} el punto)": stations["drive_min"].round(1),
        }
    )
    for mnt, p in polys.items():
        table[f"km² a ≤{mnt} min"] = (p.set_index("station_id").area / 1e6).reindex(stations["station_id"]).round(2).values
    st.dataframe(table, width="stretch", hide_index=True)

# --------------------------------------------------------------------------- exportar

with tab_export:
    st.subheader("Exportar")
    st.download_button("Mapa interactivo (HTML)", m.get_root().render().encode("utf-8"), "mapa_accesibilidad.html", "text/html")
    if polys:
        names = dict(zip(stations["station_id"], stations["name"]))
        iso_all = pd.concat([p.assign(minutos=mnt) for mnt, p in polys.items()], ignore_index=True)
        iso_all = gpd.GeoDataFrame(iso_all, crs=config.CRS_METRIC).to_crs(config.CRS_WGS84)
        iso_all["estacion"] = iso_all["station_id"].map(names)
        iso_all["velocidad_kmh"] = speed
        iso_all["tipo"] = "isocrona" if area_kind == AREA_ISO else "circulo"
        st.download_button("Áreas por estación (GeoJSON)", iso_all.to_json(), "areas_estaciones.geojson", "application/geo+json")
    if overlaps is not None and len(overlaps):
        st.download_button(
            "Zonas de solape (GeoJSON)", overlaps.to_crs(config.CRS_WGS84).to_json(), "solapes.geojson", "application/geo+json"
        )
    st_export = stations.drop(columns=["geometry"]).assign(lines=stations["lines"].map(", ".join))
    st.download_button("Estaciones (CSV)", st_export.to_csv(index=False).encode("utf-8"), "estaciones.csv", "text/csv")
    st.download_button(
        "Estaciones (GeoJSON)",
        stations.assign(lines=stations["lines"].map(", ".join)).to_json(),
        "estaciones.geojson",
        "application/geo+json",
    )
    if homes_gdf is not None:
        st.download_button(
            "Viviendas analizadas (CSV)",
            homes_gdf.drop(columns="geometry").to_csv(index=False).encode("utf-8"),
            "viviendas_accesibilidad.csv",
            "text/csv",
        )

# --------------------------------------------------------------------------- información

with tab_info:
    versions = meta.get("crtm_versions", {})
    st.markdown(
        f"""
**Fuentes**
- Estaciones, accesos y trazados: *Datos abiertos — Elementos de la Red* del Consorcio Regional de Transportes de
  Madrid (CRTM), servicios {", ".join(config.TRANSIT_NETWORKS[k].service for k in versions)}. Fecha de los datos:
  {", ".join(f"{config.TRANSIT_NETWORKS[k].label} {v}" for k, v in versions.items())}.
  Licencia: [{config.CRTM_LICENSE_URL}]({config.CRTM_LICENSE_URL}).
- Red peatonal, red viaria y límites municipales: © colaboradores de OpenStreetMap (licencia ODbL), extracto de
  Geofabrik para la Comunidad de Madrid del {meta.get("osm_extract_mtime", "?")}.
- Última preparación de datos: {meta.get("updated", "?")}.

**Método**
- *Andando*: se recorre la red peatonal (mismo filtro que la red `walk` de OSMnx) desde todos los accesos de la
  estación; el área es el conjunto de calles alcanzables con un pasillo de {config.SETTINGS.isochrone_buffer_m:.0f} m,
  rellenando patios de manzana. Distancia = tiempo × velocidad.
- *Círculo*: radio en línea recta = tiempo × velocidad (sobrestima el área real).
- *Coche*: red viaria (filtro `drive` de OSMnx) con velocidades sin tráfico al estilo OSRM
  ({int(config.SETTINGS.drive_maxspeed_factor * 100)} % del límite señalizado, o valores típicos por tipo de vía)
  y sentidos únicos. En hora punta (8:30, aproximado) cada vía se ralentiza según su tipo y zona:
  {_traffic_summary()}. Calibrado a mano con tiempos de Google Maps (Sol, Aravaca, Moncloa); no son datos de
  tráfico medidos.

**Limitaciones**
- Los tiempos son estimaciones; no incluyen semáforos, esperas, pendientes ni el recorrido dentro de la estación.
- OpenStreetMap puede tener calles o pasos peatonales incompletos o desactualizados.
- La posición de los accesos procede del CRTM; las estaciones sin accesos publicados usan un único punto.
- El indicador de viviendas es experimental y no está validado.
"""
    )
