import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point

from accesibilidad import config, drive, housing, isochrones, osm, transit
from accesibilidad.graph import WalkGraph


def test_line_labels():
    assert transit.line_label("metro", "7a") == "L7"
    assert transit.line_label("metro", "12-1") == "L12"
    assert transit.line_label("metro", "R") == "R"
    assert transit.line_label("cercanias", "C-4a") == "C4a"
    assert transit.line_label("metro_ligero", "4-1") == "ML4"


def test_pretty_name():
    assert transit.pretty_name("ALFONSO XIII") == "Alfonso XIII"
    assert transit.pretty_name("PUERTA DE BOADILLA") == "Puerta de Boadilla"
    assert transit.pretty_name("Aguilas, las") == "Las Aguilas"
    assert transit.pretty_name("ROZAS, LAS") == "Las Rozas"


def test_expand_lines():
    assert transit._expand_lines(["C4", "C5"], ["C4a", "C4b", "C5"]) == ["C4a", "C4b", "C5"]


def test_walk_and_drive_filters():
    assert osm._passes({"highway": "footway"}, osm._WALK_RE)
    assert not osm._passes({"highway": "motorway"}, osm._WALK_RE)
    assert not osm._passes({"highway": "primary", "sidewalk": "separate"}, osm._WALK_RE)
    assert not osm._passes({"highway": "residential", "foot": "no"}, osm._WALK_RE)
    assert osm._passes({"highway": "motorway"}, osm._DRIVE_RE)
    assert not osm._passes({"highway": "footway"}, osm._DRIVE_RE)
    assert not osm._passes({"highway": "service", "service": "parking_aisle"}, osm._DRIVE_RE)


def test_drive_speed_and_direction():
    assert osm.drive_speed_kmh({"highway": "residential", "maxspeed": "50"}, 0.8) == pytest.approx(40)
    assert osm.drive_speed_kmh({"highway": "motorway"}, 0.8) == 90
    assert osm.drive_speed_kmh({"highway": "primary", "maxspeed": "ES:urban"}, 0.8) == pytest.approx(40)
    assert osm.drive_direction({"oneway": "yes"}) == 1
    assert osm.drive_direction({"oneway": "-1"}) == -1
    assert osm.drive_direction({"junction": "roundabout"}) == 1
    assert osm.drive_direction({"highway": "motorway", "oneway": "no"}) == 0
    assert osm.drive_direction({"highway": "residential"}) == 0


@pytest.fixture
def grid_graph():
    """Malla de 11x11 calles separadas 100 m (origen en 440000, 4474000, EPSG:25830)."""
    n = 11
    xs, ys = np.meshgrid(np.arange(n) * 100.0 + 440000, np.arange(n) * 100.0 + 4474000)
    nodes = pd.DataFrame({"osmid": np.arange(n * n), "x": xs.ravel(), "y": ys.ravel()})
    idx = np.arange(n * n).reshape(n, n)
    u = np.concatenate([idx[:, :-1].ravel(), idx[:-1, :].ravel()])
    v = np.concatenate([idx[:, 1:].ravel(), idx[1:, :].ravel()])
    edges = pd.DataFrame({"u": u, "v": v, "length": np.full(len(u), 100.0, dtype=np.float32)})
    return WalkGraph(nodes, edges), idx


def test_reach_is_manhattan_distance(grid_graph):
    wg, idx = grid_graph
    centre = idx[5, 5]
    nodes, dist = wg.reach_from([wg.x[centre]], [wg.y[centre]], 350)
    d = dict(zip(nodes, dist, strict=True))
    assert d[centre] == pytest.approx(0, abs=0.01)
    assert d[idx[5, 7]] == pytest.approx(200, abs=0.01)
    assert d[idx[6, 7]] == pytest.approx(300, abs=0.01)
    assert idx[7, 7] not in d  # 400 m > límite


def test_reach_multiple_sources_uses_nearest(grid_graph):
    wg, idx = grid_graph
    a, b = idx[0, 0], idx[10, 10]
    nodes, dist = wg.reach_from(wg.x[[a, b]], wg.y[[a, b]], 2000)
    d = dict(zip(nodes, dist, strict=True))
    assert d[idx[9, 10]] == pytest.approx(100, abs=0.01)
    assert d[idx[1, 0]] == pytest.approx(100, abs=0.01)


def test_polygon_grows_with_budget_and_contains_partial_edges(grid_graph):
    wg, idx = grid_graph
    centre = idx[5, 5]
    nodes, dist = wg.reach_from([wg.x[centre]], [wg.y[centre]], 600)
    small = isochrones.reach_polygon(wg, nodes, dist, 150, buffer_m=10, fill_holes_m2=0)
    big = isochrones.reach_polygon(wg, nodes, dist, 450, buffer_m=10, fill_holes_m2=0)
    assert big.area > small.area > 0
    assert small.contains(Point(wg.x[centre] + 140, wg.y[centre]))  # tramo parcial a 140 m
    assert not small.contains(Point(wg.x[centre] + 180, wg.y[centre]))


def test_overlap_zones_counts():
    polys = gpd.GeoDataFrame(
        {"station_id": ["a", "b", "c"]},
        geometry=[Point(0, 0).buffer(100), Point(120, 0).buffer(100), Point(240, 0).buffer(100)],
        crs=config.CRS_METRIC,
    )
    ov = isochrones.overlap_zones(polys)
    assert set(ov["n_stations"]) == {2}
    assert ov.geometry.iloc[0].contains(Point(60, 0))
    assert not ov.geometry.iloc[0].contains(Point(0, 0))


def test_read_listings_semicolon_and_aliases():
    data = "Título;Dirección;Latitud;Longitud;Precio;Superficie\nA;Calle 1;40,41;-3,70;300.000 €;80\n".encode()
    df = housing.read_listings(data, "x.csv")
    assert {"titulo", "direccion", "lat", "lon", "precio", "superficie"} <= set(df.columns)
    assert df.loc[0, "lat"] == pytest.approx(40.41)


def test_experimental_score_bounds():
    summary = pd.DataFrame(
        {
            "min_a_estacion": [2.0, np.nan],
            "n_estaciones": [5, 0],
            "lineas": ["L1, L2, L3, L4, L5, L6, C1", ""],
            "redes": ["Cercanías, Metro", ""],
        }
    )
    s = housing.experimental_score(summary, max_minutes=10)
    assert 0 <= s.iloc[1] <= s.iloc[0] <= 100
    assert s.iloc[1] == 0


def test_road_class():
    assert osm.road_class({"highway": "motorway", "ref": "M-30"}) == osm.ROAD_M30
    assert osm.road_class({"highway": "motorway_link", "ref": "A-6;M-40"}) == osm.ROAD_M40
    assert osm.road_class({"highway": "trunk", "ref": "M-503"}) == osm.ROAD_HIGHWAY
    assert osm.road_class({"highway": "secondary"}) == osm.ROAD_ARTERIAL
    assert osm.road_class({"highway": "residential"}) == osm.ROAD_LOCAL


def test_rush_hour_factors_by_zone():
    from accesibilidad.graph import to_metric

    p = config.RUSH_HOUR
    pts = {"sol": p.city_center, "lejos": (40.60, -3.40), "origen": (config.DEFAULT_ORIGIN.lat, config.DEFAULT_ORIGIN.lon)}
    xs, ys = zip(*(to_metric(lon, lat) for lat, lon in pts.values()), strict=True)
    nodes = pd.DataFrame({"x": np.concatenate(xs), "y": np.concatenate(ys)})
    edges = pd.DataFrame(
        {"u": [0, 1, 1, 2], "v": [0, 1, 1, 2], "road_class": [osm.ROAD_LOCAL, osm.ROAD_LOCAL, osm.ROAD_M30, osm.ROAD_HIGHWAY]}
    )
    f = drive.rush_hour_factors(edges, nodes, p, (config.DEFAULT_ORIGIN.lon, config.DEFAULT_ORIGIN.lat))
    road = dict(p.road_factors)
    assert f[0] == max(f for _, f in p.urban_rings_m)
    assert f[1] == road[osm.ROAD_LOCAL]
    assert f[2] == road[osm.ROAD_M30]
    assert f[3] == max(road[osm.ROAD_HIGHWAY], p.near_origin_factor)
