#!/usr/bin/env python3
"""Parámetros configurables de la búsqueda (pantalla de configuración)."""
import json, os, unicodedata

HOME = os.path.dirname(os.path.abspath(__file__))
PARAMS_FILE = os.path.join(HOME, 'params.json')

DEFAULTS = {
    # precio
    'precio_max': 280000,     # tope del coste total
    'nego': 0.9,              # factor negociación sobre anuncio
    'itp': 0.06,              # ITP sobre precio negociado
    'com_redpiso': 0.0484,    # comisión Redpiso
    'com_agencia': 0.0363,    # comisión otras inmobiliarias
    'extra_sin_cal': 10000,   # coste extra si no hay calefacción
    'eurm2_max': 3800,        # €/m² máximo (sin calefacción ni ITP)
    'm2_min': 70,             # superficie mínima
    # filtros
    'min_fotos': 2,
    'ascensor_desde': 3,      # desde esta planta exige ascensor
    'no_bajos': True,
    'no_ocupadas': True,      # ocupada, alquilada, nuda propiedad, subasta...
    'no_interiores': True,
    'orient_reject': 'norte,noroeste',
    'barrios_excl': 'villaverde,usera,orcasitas,orcasur,san fermín,almendrales,moscardó,zofío,pradolongo,los ángeles,san andrés,butarque,los rosales,san cristóbal',
    # zona (recalcula el mapa si cambian)
    'walk_max': 12,           # min andando a estación
    'tp_max': 40,             # min TP a Alonso Martínez
    'car_max': 25,            # min coche hora punta a Cd. Financiera
    # puntuación (base 100)
    'sc_oeste': 10,
    'sc_sin_cal': 2,
    'sc_sin_aire': 5,
    'car_u1': 25, 'sc_car_25': 5,   # >=car_u1 min -> -sc_car_25
    'car_u2': 20, 'sc_car_20': 2,   # >car_u2 min -> -sc_car_20
    'tp_u': 35, 'sc_tp_35': 5,      # >tp_u min -> -sc_tp_35
    'm2_u1': 75, 'sc_m2_75': 3,     # <m2_u1 -> -sc_m2_75
    'm2_u2': 80, 'sc_m2_80': 0,     # <m2_u2 -> -sc_m2_80
    'sc_sin_asc': 5,
    # reglas personalizadas: [{'tipo':'descartar'|'puntos','campo':'anuncio'|'barrio','texto':str,'puntos':int}]
    'reglas': [],
}

def load():
    p = dict(DEFAULTS)
    try:
        p.update(json.load(open(PARAMS_FILE)))
    except Exception:
        pass
    return p

def save(p):
    cur = dict(DEFAULTS)
    cur.update({k: v for k, v in (p or {}).items() if k in DEFAULTS})
    json.dump(cur, open(PARAMS_FILE, 'w'), ensure_ascii=False, indent=1)
    return cur

def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD', (s or '').lower())
                   if unicodedata.category(c) != 'Mn')

def bad_hood_fn(p):
    toks = [norm(t) for t in str(p['barrios_excl']).split(',') if t.strip()]
    return lambda h: bool(h) and any(t in norm(h) for t in toks)

def rej_orient(p):
    return {norm(t) for t in str(p['orient_reject']).split(',') if t.strip()}

def reglas(p):
    """[(campo, texto_norm, tipo, puntos)] de params['reglas']."""
    out = []
    for g in (p.get('reglas') or []):
        try:
            tx = norm(str(g.get('texto') or ''))
            if not tx:
                continue
            out.append((g.get('campo') or 'anuncio', tx,
                        g.get('tipo') or 'puntos', max(0, int(g.get('puntos') or 0))))
        except Exception:
            continue
    return out

def regla_pen_y_drop(rules, txt_n, hood_n):
    """(puntos a restar, descartar) para un anuncio con texto y barrio normalizados."""
    pen = 0
    for cp, tx, tp, pts in rules:
        src = hood_n if cp == 'barrio' else txt_n
        if tx in src:
            if tp == 'descartar':
                return pen, True
            pen += pts
    return pen, False
