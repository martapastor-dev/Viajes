import numpy as np
import pandas as pd
import pytest

from accesibilidad import seguridad


def test_norm_name():
    assert seguridad.norm_name("Fuencarral-El Pardo") == "FUENCARRAL EL PARDO"
    assert seguridad.norm_name("  Puerto  de   Vallecas ") == "PUERTO DE VALLECAS"
    assert seguridad.norm_name("Tetuán") == "TETUAN"
    assert seguridad.norm_name("") == ""


def test_match_name_articles():
    candidates = {"LAS ROZAS DE MADRID", "GETAFE", "BOADILLA DEL MONTE"}
    assert seguridad.match_name("Rozas de Madrid", candidates) == "LAS ROZAS DE MADRID"
    assert seguridad.match_name("Getafe", candidates) == "GETAFE"
    assert seguridad.match_name("Boadilla del Monte", candidates) == "BOADILLA DEL MONTE"
    assert seguridad.match_name("Inexistente", candidates) is None


def _corona_csv(tmp_path):
    rows = [
        # año, concepto, municipio, valor
        ("2023", "Hechos conocidos de hurtos de tipología penal en Boadilla del Monte", "Boadilla del Monte", "100"),
        ("2024", "Hechos conocidos de hurtos de tipología penal en Boadilla del Monte", "Boadilla del Monte", "200"),
        ("2025", "Hechos conocidos de hurtos de tipología penal en Boadilla del Monte", "Boadilla del Monte", "300"),
        (
            "2025",
            "Hechos conocidos de robos con violencia e intimidación de tipología penal en Boadilla del Monte",
            "Boadilla del Monte",
            "10",
        ),
        ("2023", "Hechos conocidos de tráfico de drogas de tipología penal en Boadilla del Monte", "Boadilla del Monte", "5"),
        ("2025", "Hechos conocidos de secuestro de tipología penal en Boadilla del Monte", "Boadilla del Monte", "2"),
        ("2025", "Total hechos conocidos de infracciones penales en Boadilla del Monte", "Boadilla del Monte", "9999"),
        ("2025", "Hechos conocidos de hurtos de tipología penal en Madrid", "Madrid", "99999"),
        ("2022", "Hechos conocidos de hurtos de tipología penal en Boadilla del Monte", "Boadilla del Monte", "50"),
    ]
    header = "Año;Concepto;Tipo territorio;Código territorio;Territorio;Municipio;Valor;Unidad;Estado dato"
    body = "\n".join(";".join([a, b, "Otros", "", "", m, v, "Número", ""]) for a, b, m, v in rows)
    p = tmp_path / "corona.csv"
    p.write_text(header + "\n" + body + "\n", encoding="latin-1")
    return p


def test_parse_corona(tmp_path):
    df = seguridad.parse_corona(_corona_csv(tmp_path))
    assert len(df) == 2  # Boadilla y Madrid (años filtrados fuera 2022)
    bo = df.set_index("municipio_raw").loc["Boadilla del Monte"]
    assert bo["count_patrimonio"] == pytest.approx(600)  # hurtos 100+200+300; el total no cuenta
    assert bo["count_violencia"] == pytest.approx(10)
    assert bo["count_drogas"] == pytest.approx(5)
    assert bo["count_otro"] == pytest.approx(2)  # secuestro
    assert bo["years"] == "2023,2024,2025"


def _ayto_xlsx(tmp_path, name, rows):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SEGURIDAD"
    ws.append(["SEGURIDAD CIUDADANA"])
    ws.append([])
    ws.append(
        [
            "DISTRITOS",
            "RELACIONADAS CON LAS PERSONAS",
            "RELACIONADAS CON EL PATRIMONIO",
            "POR TENENCIA DE ARMAS",
            "POR TENENCIA DE DROGAS",
            "POR CONSUMO DE DROGAS",
        ]
    )
    for r in rows:
        ws.append(r)
    ws.append(["SIN DISTRITO ASIGNADO", 0, 0, 0, 0, 0])
    ws.append(["TOTAL", 1, 1, 1, 1, 1])
    p = tmp_path / name
    wb.save(p)
    return p


def test_parse_capital(tmp_path):
    m1 = _ayto_xlsx(tmp_path, "2023-01.xlsx", [["CENTRO", 10, 20, 1, 2, 3], ["RETIRO", 5, 6, 0, 1, 0]])
    m2 = _ayto_xlsx(tmp_path, "2023-02.xlsx", [["CENTRO", 30, 40, 0, 4, 1], ["RETIRO", 7, 8, 1, 1, 2]])
    df = seguridad.parse_capital([m1, m2])
    assert set(df["distrito_raw"]) == {"CENTRO", "RETIRO"}
    centro = df.set_index("distrito_raw").loc["CENTRO"]
    assert centro["personas"] == 40 and centro["patrimonio"] == 60
    assert centro["tenencia_drogas"] == 6 and centro["consumo_drogas"] == 4
    assert centro["months"] == 2 and centro["years"] == "2023"


def test_capital_rows_rates():
    agg = pd.DataFrame(
        {
            "distrito_raw": ["CENTRO"],
            "personas": [100.0],
            "patrimonio": [200.0],
            "armas": [1.0],
            "tenencia_drogas": [10.0],
            "consumo_drogas": [5.0],
            "months": [12],
            "years": "2023",
        }
    )
    pob = pd.DataFrame({"pob": [100_000.0, 50_000.0], "distrito_key": ["CENTRO", "RETIRO"], "bar_key": [1, 2]})
    rows = seguridad._capital_rows(agg, pob)
    assert len(rows) == 1
    r = rows[0]
    assert r["population"] == 100_000
    assert r["count_drug"] == 15
    assert r["rate_pat"] == pytest.approx(200 / 1 / 100_000 * 1000)


def test_rank_index_bounds_and_nan():
    df = pd.DataFrame(
        {
            "source": ["corona", "corona", "capital", "capital"],
            "population": [1000.0, 2000.0, 3000.0, np.nan],
            "count_pat": [1, 2, 3, 4],
            "count_viol": [1, 1, 1, 1],
            "count_drug": [1, 1, 1, 1],
            "count_other": [0, 0, 0, 0],
            "rate_pat": [10.0, 20.0, 5.0, np.nan],
            "rate_viol": [1.0, 1.0, 1.0, np.nan],
            "rate_drug": [1.0, 1.0, 1.0, np.nan],
        }
    )
    idx = seguridad._rank_index(df)
    assert idx.iloc[0] > 0 and idx.iloc[1] > idx.iloc[0]
    assert idx.iloc[3] != idx.iloc[3]  # NaN sin población
    assert (idx.dropna() <= 100).all() and (idx.dropna() >= 0).all()
