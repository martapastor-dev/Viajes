"""Construcción del mapa interactivo con Folium."""

from __future__ import annotations

import html

import folium
import geopandas as gpd
from folium.plugins import Draw, Fullscreen, MeasureControl

from . import config

# Colores por tiempo (de menor a mayor). Las bandas más cortas se dibujan encima.
TIME_COLORS = {5: "#1a9850", 10: "#91cf60", 15: "#fee08b", 20: "#fc8d59"}
OVERLAP_COLORS = {2: "#9e9ac8", 3: "#756bb1", 4: "#54278f"}
MODE_ICON = {"metro": "M", "cercanias": "C", "metro_ligero": "ML"}


def time_color(minutes: int) -> str:
    return TIME_COLORS.get(minutes, "#fdae61")


def base_map(center=(40.42, -3.75), zoom=11) -> folium.Map:
    m = folium.Map(location=center, zoom_start=zoom, tiles=None, control_scale=True, prefer_canvas=True)
    folium.TileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        name="Mapa gris claro (Esri)",
        attr="Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors",
        max_zoom=16,
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", show=False).add_to(m)
    Fullscreen().add_to(m)
    MeasureControl(primary_length_unit="meters", secondary_length_unit="kilometers").add_to(m)
    return m


def add_drawing(m: folium.Map) -> None:
    Draw(
        export=False,
        draw_options={"polyline": False, "circlemarker": False, "marker": False},
        edit_options={"edit": False},
    ).add_to(m)


def add_scope(m: folium.Map, scope: gpd.GeoDataFrame, name: str, color: str = "#555555", show=True) -> None:
    if scope is None or scope.empty:
        return
    folium.GeoJson(
        scope.to_crs(config.CRS_WGS84).__geo_interface__,
        name=name,
        show=show,
        style_function=lambda _: {"color": color, "weight": 2, "dashArray": "6 4", "fillOpacity": 0.03},
        interactive=False,
    ).add_to(m)


def add_lines(m: folium.Map, lines: gpd.GeoDataFrame) -> None:
    if lines.empty:
        return
    fg = folium.FeatureGroup(name="Líneas", show=True)
    for _, row in lines.iterrows():
        folium.GeoJson(
            row.geometry.__geo_interface__,
            style_function=lambda _, c=row["color"]: {"color": c, "weight": 4, "opacity": 0.85},
            tooltip=row["line"],
        ).add_to(fg)
    fg.add_to(m)


def add_isochrones(
    m: folium.Map, polys_by_time: dict[int, gpd.GeoDataFrame], stations: gpd.GeoDataFrame, individual: bool, label: str
) -> None:
    names = dict(zip(stations["station_id"], stations["name"]))
    for minutes in sorted(polys_by_time, reverse=True):
        polys = polys_by_time[minutes]
        if polys.empty:
            continue
        color = time_color(minutes)
        fg = folium.FeatureGroup(name=f"{label} {minutes} min", show=True)
        style = {"color": color, "weight": 1, "fillColor": color, "fillOpacity": 0.35}
        # Geometrías simplificadas solo para dibujar: reduce mucho el tamaño del mapa.
        wgs = polys.assign(geometry=polys.geometry.simplify(10)).to_crs(config.CRS_WGS84)
        if individual:
            wgs = wgs.assign(station=wgs["station_id"].map(names), minutes=minutes)
            folium.GeoJson(
                wgs[["station", "minutes", "geometry"]].__geo_interface__,
                style_function=lambda _, s=style: s,
                tooltip=folium.GeoJsonTooltip(["station", "minutes"], aliases=["Estación", "Minutos"]),
            ).add_to(fg)
        else:
            merged = wgs.geometry.union_all().simplify(0.0001)
            folium.GeoJson(
                merged.__geo_interface__, style_function=lambda _, s=style: s, tooltip=f"{label} {minutes} min"
            ).add_to(fg)
        fg.add_to(m)


def add_overlaps(m: folium.Map, overlaps: gpd.GeoDataFrame, minutes: int) -> None:
    if overlaps.empty:
        return
    fg = folium.FeatureGroup(name=f"Solapes ({minutes} min)", show=True)
    for _, row in overlaps.to_crs(config.CRS_WGS84).iterrows():
        n = int(row["n_stations"])
        c = OVERLAP_COLORS.get(n, "#54278f")
        label = f"{n}+ estaciones a ≤{minutes} min" if n >= 4 else f"{n} estaciones a ≤{minutes} min"
        folium.GeoJson(
            row.geometry.__geo_interface__,
            style_function=lambda _, c=c: {"color": c, "weight": 0.5, "fillColor": c, "fillOpacity": 0.45},
            tooltip=label,
        ).add_to(fg)
    fg.add_to(m)


def _station_popup(row) -> str:
    lines = ", ".join(row["lines"]) if len(row["lines"]) else "-"
    extra = ""
    if "drive_min" in row and row["drive_min"] == row["drive_min"]:
        extra = f"<br>En coche al punto de referencia: {row['drive_min']:.0f} min"
    return (
        f"<b>{html.escape(row['name'])}</b><br>{config.TRANSIT_NETWORKS[row['mode']].label}: {html.escape(lines)}"
        f"<br>Municipio: {html.escape(str(row.get('municipality') or '-'))}"
        f"<br>Accesos: {row['n_accesses']}{extra}"
    )


def add_stations(m: folium.Map, stations: gpd.GeoDataFrame, access: gpd.GeoDataFrame | None) -> None:
    fg = folium.FeatureGroup(name="Estaciones", show=True)
    for _, row in stations.iterrows():
        net = config.TRANSIT_NETWORKS[row["mode"]]
        folium.CircleMarker(
            location=(row.geometry.y, row.geometry.x),
            radius=6,
            color="white",
            weight=2,
            fill=True,
            fill_color=net.color,
            fill_opacity=1,
            tooltip=f"{row['name']} ({', '.join(row['lines'])})",
            popup=folium.Popup(_station_popup(row), max_width=300),
        ).add_to(fg)
    fg.add_to(m)
    if access is not None and not access.empty:
        fa = folium.FeatureGroup(name="Accesos de estación", show=False)
        for _, row in access.iterrows():
            folium.CircleMarker(
                location=(row.geometry.y, row.geometry.x),
                radius=2,
                color="#333",
                fill=True,
                fill_opacity=1,
                tooltip=row["name"],
            ).add_to(fa)
        fa.add_to(m)


def add_origin(m: folium.Map, lat: float, lon: float, name: str) -> None:
    folium.Marker((lat, lon), tooltip=name, icon=folium.Icon(color="red", icon="briefcase", prefix="fa")).add_to(m)


def add_housing(m: folium.Map, homes: gpd.GeoDataFrame) -> None:
    if homes is None or homes.empty:
        return
    fg = folium.FeatureGroup(name="Viviendas", show=True)
    for _, r in homes.iterrows():
        if r.geometry is None or r.geometry.is_empty:
            continue
        popup = [f"<b>{html.escape(str(r.get('titulo') or r.get('direccion') or 'Vivienda'))}</b>"]
        if r.get("precio") == r.get("precio"):
            popup.append(f"Precio: {r['precio']:,.0f} €".replace(",", "."))
        if r.get("superficie") == r.get("superficie"):
            popup.append(f"Superficie: {r['superficie']:.0f} m²")
        if r.get("eur_m2") == r.get("eur_m2"):
            popup.append(f"€/m²: {r['eur_m2']:,.0f}".replace(",", "."))
        if r.get("estacion_mas_cercana"):
            popup.append(f"Más cercana: {html.escape(r['estacion_mas_cercana'])} ({r['min_a_estacion']:.0f} min)")
        if r.get("lineas"):
            popup.append(f"Líneas a ≤ tiempo elegido: {html.escape(r['lineas'])}")
        if r.get("indicador_experimental") == r.get("indicador_experimental"):
            popup.append(f"Indicador experimental: {r['indicador_experimental']:.0f}/100")
        folium.Marker(
            (r.geometry.y, r.geometry.x),
            tooltip=str(r.get("titulo") or r.get("direccion") or "Vivienda"),
            popup=folium.Popup("<br>".join(popup), max_width=320),
            icon=folium.Icon(color="darkblue", icon="home", prefix="fa"),
        ).add_to(fg)
    fg.add_to(m)


def add_legend(m: folium.Map, minutes: list[int], show_overlaps: bool) -> None:
    items = "".join(
        f'<div><span style="background:{time_color(t)};width:14px;height:14px;display:inline-block;'
        f'margin-right:6px;opacity:.8"></span>≤ {t} min</div>'
        for t in sorted(minutes)
    )
    if show_overlaps:
        items += "".join(
            f'<div><span style="background:{c};width:14px;height:14px;display:inline-block;margin-right:6px">'
            f"</span>{n}{'+' if n == 4 else ''} estaciones</div>"
            for n, c in OVERLAP_COLORS.items()
        )
    legend = (
        '<div style="position:fixed;bottom:24px;left:12px;z-index:9999;background:white;padding:8px 10px;'
        'border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);font-size:12px">'
        f"<b>Tiempo andando</b>{items}"
        '<div style="margin-top:4px;color:#666">Estimaciones, no tiempos garantizados</div></div>'
    )
    m.get_root().html.add_child(folium.Element(legend))


def finish(m: folium.Map) -> folium.Map:
    folium.LayerControl(collapsed=True).add_to(m)
    return m
