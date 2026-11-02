# -*- coding: utf-8 -*-
"""
Inyecta en mapa.html las isocronas de transporte publico calculadas en
isocronas_tp.json (bandas <=30 / <=40 / <=50 min a Alonso Martinez):
tres FeatureGroup con estilo folium, entradas en el control de capas
del PRIMER mapa visible (map_5cfeaa...), marcador de Plaza Santa Barbara 2
y ampliacion de la leyenda.
Crea mapa_backup.html antes de modificar.
"""

import json
import os
import shutil

# Feature group de "Accesos de estacion" en el PRIMER mapa (map_5cfeaa)
ACCESOS_FG = "feature_group_90cbb72cd03223edbb9f937060a3d4d5"

BASE = os.path.dirname(os.path.abspath(__file__))
MAPA = os.path.join(BASE, "mapa.html")
BACKUP = os.path.join(BASE, "mapa_backup.html")

# El mapa visible es map_5cfeaa38b91dee9c8d02fa0fb259a75a
# Su control de capas: layer_control_a76a255605e3a529b99ddf6985f8c4bb_layers
# Ultimo overlay original: feature_group_90cbb72cd03223edbb9f937060a3d4d5 (Accesos)
MAP_VAR = "map_5cfeaa38b91dee9c8d02fa0fb259a75a"
LC_ANCHOR = "            var layer_control_a76a255605e3a529b99ddf6985f8c4bb_layers = {"
OVERLAY_ANCHOR = \
    '                    "Accesos de estaci\\u00f3n" : feature_group_90cbb72cd03223edbb9f937060a3d4d5,'

BANDS = [
    # (key, color, tooltip, nombre_capa)  -- orden: 50 primero (fondo), 30 encima
    ("50", "#c6dbef",
     "\u226450 min en transporte p\u00fablico a Alonso Mart\u00ednez",
     "En TP a Alonso Mart\u00ednez: \u226450 min"),
    ("40", "#6baed6",
     "\u226440 min en transporte p\u00fablico a Alonso Mart\u00ednez",
     "En TP a Alonso Mart\u00ednez: \u226440 min"),
    ("30", "#08519c",
     "\u226430 min en transporte p\u00fablico a Alonso Mart\u00ednez",
     "En TP a Alonso Mart\u00ednez: \u226430 min"),
]

PLAZA = (40.4279, -3.6964)

with open(os.path.join(BASE, "isocronas_tp.json"), encoding="utf-8") as f:
    iso = json.load(f)

with open(os.path.join(BASE, "accesos_tp.json"), encoding="utf-8") as f:
    acc = json.load(f)

# -- restaurar desde backup si ya habia una inyeccion fallida/anterior --
if os.path.exists(BACKUP):
    shutil.copyfile(BACKUP, MAPA)
    print("Restaurado desde mapa_backup.html")
else:
    shutil.copyfile(MAPA, BACKUP)
    print("Backup creado: mapa_backup.html")

with open(MAPA, encoding="utf-8") as f:
    html = f.read()

assert LC_ANCHOR in html, "no se encuentra el control de capas del primer mapa"
assert OVERLAY_ANCHOR in html, "no se encuentra entrada Accesos en primer control"


def geojson_block(key, color, tooltip, fg_name, gj_name, map_var):
    data = json.dumps(iso[key], separators=(",", ":"), ensure_ascii=False)
    return f"""
            var {fg_name} = L.featureGroup(
                {{
}}
            );


        function {gj_name}_styler(feature) {{
            switch(feature.id) {{
                default:
                    return {{"color": "{color}", "fillColor": "{color}", "fillOpacity": 0.35, "weight": 1}};
            }}
        }}

        function {gj_name}_onEachFeature(feature, layer) {{
            layer.on({{
            }});
        }};
        var {gj_name} = L.geoJson(null, {{
                onEachFeature: {gj_name}_onEachFeature,
                style: {gj_name}_styler,
            ...{{
}}
        }});

        function {gj_name}_add (data) {{
            {gj_name}
                .addData(data);
        }}
            {gj_name}_add({data});


            {gj_name}.bindTooltip(
                `<div>
                     {tooltip}
                 </div>`,
                {{
  "sticky": true,
}}
            );


            {gj_name}.addTo({fg_name});


            {fg_name}.addTo({map_var});

    """


blocks = []
for key, color, tooltip, _ in BANDS:
    blocks.append(geojson_block(
        key, color, tooltip,
        f"feature_group_tp{key}", f"geo_json_tp{key}",
        MAP_VAR
    ))

marker = f"""
            var marker_tp_dest = L.marker(
                [{PLAZA[0]}, {PLAZA[1]}],
                {{
}}
            ).addTo({MAP_VAR});


            var icon_tp_dest = L.AwesomeMarkers.icon(
                {{
  "markerColor": "blue",
  "iconColor": "white",
  "icon": "train",
  "prefix": "fa",
  "extraClasses": "fa-rotate-0",
}}
            );

            marker_tp_dest.bindTooltip(
                `<div>
                     Plaza Santa B\u00e1rbara 2 (Metro Alonso Mart\u00ednez)
                 </div>`,
                {{
  "sticky": true,
}}
            );

            marker_tp_dest.setIcon(icon_tp_dest);

    """

injection = "".join(blocks) + marker

# 1. Inyectar los bloques antes del primer layer control
html = html.replace(LC_ANCHOR, injection + "\n" + LC_ANCHOR, 1)

# 2. Añadir entradas al overlay del primer control (despues de Accesos)
new_entries = "".join(
    f'\n                    "{name}" : feature_group_tp{key},'
    for key, _, _, name in BANDS
)
html = html.replace(OVERLAY_ANCHOR, OVERLAY_ANCHOR + new_entries, 1)

# 3. Leyenda fija en HTML (encima de la leyenda de andando)
legend = (
    '\n    <div style="position:fixed;bottom:160px;left:12px;z-index:9999;'
    'background:white;padding:8px 10px;border-radius:6px;'
    'box-shadow:0 1px 4px rgba(0,0,0,.3);font-size:12px">'
    '<b>TP a Alonso Mart\u00ednez</b>'
    '<div><span style="background:#08519c;width:14px;height:14px;'
    'display:inline-block;margin-right:6px;opacity:.8"></span>'
    '\u2264 30 min</div>'
    '<div><span style="background:#6baed6;width:14px;height:14px;'
    'display:inline-block;margin-right:6px;opacity:.8"></span>'
    '\u2264 40 min</div>'
    '<div><span style="background:#c6dbef;width:14px;height:14px;'
    'display:inline-block;margin-right:6px;opacity:.8"></span>'
    '\u2264 50 min</div>'
    '<div style="margin-top:4px;color:#666">Metro/Cercan\u00edas+transbordos, \u00d70,9</div>'
    '</div>'
)
# Insertar antes del primer <div class="folium-map"
map_anchor = '            <div class="folium-map" id="map_5cfeaa38b91dee9c8d02fa0fb259a75a" ></div>'
assert map_anchor in html, "no se encuentra el div del primer mapa"
html = html.replace(map_anchor, legend + "\n" + map_anchor, 1)

# 4. Popups en accesos de estacion (itinerario hasta Alonso Martinez)
# Construir objeto JS compacto: {"lat4_lon4":{t:...,r:"...",n:"..."}, ...}
acc_js_entries = []
for key, info in acc.items():
    # Escapar comillas simples/backticks dentro del texto de la ruta
    r_esc = info["r"].replace("\\", "\\\\").replace("`", "\\`")
    n_esc = info["n"].replace("\\", "\\\\").replace("`", "\\`")
    acc_js_entries.append(
        f'"{key}":{{"t":{info["t"]},"r":"{r_esc}","n":"{n_esc}"}}'
    )

popup_js = """
        // -- Popups TP en accesos de estacion --
        (function(){{
            var _tpAcc = {{{entries}}};
            {fg}.eachLayer(function(l){{
                if (!l.getLatLng) return;
                var ll = l.getLatLng();
                var k4 = ll.lat.toFixed(4)+'_'+ll.lng.toFixed(4);
                var k5 = ll.lat.toFixed(5)+'_'+ll.lng.toFixed(5);
                var info = _tpAcc[k5] || _tpAcc[k4];
                if (!info) return;
                var tt = l.getTooltip();
                var nm = info.n;
                if (tt) {{ nm = tt.getContent().replace(/<[^>]+>/g,'').trim() || nm; }}
                l.bindPopup(
                    '<b>'+nm+'</b>'+
                    '<br><span style="color:#1a5276">\u23f1 <b>'+info.t+' min</b> hasta Alonso Mart\u00ednez</span>'+
                    (info.r ? '<br><small style="color:#555">'+info.r+'</small>' : '')
                );
            }});
        }})();
        """.format(
    entries=",".join(acc_js_entries),
    fg=ACCESOS_FG,
)

# 5. Logica de interseccion geometrica entre capas de sombreado (usa Turf.js)
# Nombre de los feature groups de area (poligonos) del PRIMER mapa
POLY_FGS = [
    "feature_group_90f55c943e695d146ab7a33286218c8b",   # En coche ≤20 min
    "feature_group_af7bc5696678c3d2e6239a20e7f833dc",   # En coche ≤30 min
    "feature_group_4cd8543b6db44c796b5b07436384ce80",   # En coche ≤35 min
    "feature_group_8ec6605c90c847eb69c1a84c37d2afaa",   # Andando 15 min
    "feature_group_85e59c1a260026d66e154a14a6313322",   # Andando 10 min
    "feature_group_560a04c6eedaf7d6f178d70d4cd1e4b9",   # Andando 5 min
    "feature_group_tp50",
    "feature_group_tp40",
    "feature_group_tp30",
]
poly_fgs_js = json.dumps(POLY_FGS)

intersection_js = f"""
        // =================== INTERSECCION DE CAPAS ===================
        (function() {{
            if (typeof turf === 'undefined') {{
                console.warn('Turf.js no disponible: el boton de interseccion estara deshabilitado.');
            }}
            var _m = {MAP_VAR};
            var _fgNames = {poly_fgs_js};
            var _iLayer = null, _savedVis = {{}}, _on = false;

            function _fg(n) {{ return window[n]; }}

            function _unionFeats(feats) {{
                if (!feats || !feats.length) return null;
                return feats.reduce(function(a, f) {{
                    if (!a) return f;
                    try {{ return turf.union(a, f); }} catch(e) {{ return a; }}
                }});
            }}

            function _computeIntersection() {{
                var active = _fgNames.filter(function(n) {{
                    var fg = _fg(n); return fg && _m.hasLayer(fg);
                }});
                var polys = active.map(function(n) {{
                    var gj = _fg(n).toGeoJSON();
                    var pf = (gj.features || []).filter(function(f) {{
                        return f.geometry && /Polygon/.test(f.geometry.type);
                    }});
                    return _unionFeats(pf);
                }}).filter(Boolean);
                if (!polys.length) return null;
                return polys.reduce(function(a, p) {{
                    if (!a) return null;
                    try {{ return turf.intersect(a, p); }} catch(e) {{ return null; }}
                }});
            }}

            var IntersectCtrl = L.Control.extend({{
                options: {{ position: 'bottomleft' }},
                onAdd: function(map) {{
                    var div = L.DomUtil.create('div', 'leaflet-bar leaflet-control');
                    div.style.cssText = 'margin-bottom:4px';
                    var btn = L.DomUtil.create('button', '', div);
                    btn.title = 'Mostrar solo la zona comun a todas las capas de sombreado activas';
                    btn.innerHTML = '\u2229 Intersecci\u00f3n';
                    btn.style.cssText = (
                        'background:white;padding:5px 9px;border:none;cursor:pointer;' +
                        'font-size:12px;font-weight:600;color:#333;display:block;' +
                        'border-radius:4px;white-space:nowrap;' +
                        'box-shadow:0 1px 5px rgba(0,0,0,.3);min-width:130px;'
                    );
                    if (typeof turf === 'undefined') {{
                        btn.disabled = true;
                        btn.style.opacity = '0.4';
                        btn.title = 'Error: Turf.js no cargado';
                    }}
                    L.DomEvent.disableClickPropagation(div);
                    L.DomEvent.on(btn, 'click', function() {{
                        if (_on) {{
                            // --- APAGAR: restaurar capas y eliminar interseccion ---
                            if (_iLayer) {{ _m.removeLayer(_iLayer); _iLayer = null; }}
                            _fgNames.forEach(function(n) {{
                                var fg = _fg(n);
                                if (fg && _savedVis[n] && !_m.hasLayer(fg)) fg.addTo(_m);
                            }});
                            _savedVis = {{}}; _on = false;
                            btn.innerHTML = '\u2229 Intersecci\u00f3n';
                            btn.style.background = 'white';
                            btn.style.color = '#333';
                        }} else {{
                            // --- ENCENDER: comprobar capas activas y calcular ---
                            var active = _fgNames.filter(function(n) {{
                                var fg = _fg(n); return fg && _m.hasLayer(fg);
                            }});
                            if (active.length < 2) {{
                                alert('Activa al menos 2 capas de sombreado (coche, andando o TP) para calcular la intersecci\u00f3n.');
                                return;
                            }}
                            var result = _computeIntersection();
                            // Ocultar todas las capas de area
                            _fgNames.forEach(function(n) {{
                                var fg = _fg(n);
                                if (!fg) return;
                                _savedVis[n] = _m.hasLayer(fg);
                                if (_m.hasLayer(fg)) _m.removeLayer(fg);
                            }});
                            if (!result) {{
                                // Sin interseccion: restaurar y avisar
                                _fgNames.forEach(function(n) {{
                                    var fg = _fg(n);
                                    if (fg && _savedVis[n] && !_m.hasLayer(fg)) fg.addTo(_m);
                                }});
                                _savedVis = {{}};
                                alert('No hay zona com\u00fan a todas las capas de sombreado activas.');
                                return;
                            }}
                            _iLayer = L.geoJson(result, {{
                                style: {{
                                    color: '#4A235A',
                                    fillColor: '#7D3C98',
                                    fillOpacity: 0.65,
                                    weight: 2
                                }}
                            }}).bindTooltip('Zona de intersecci\u00f3n', {{sticky: true}})
                              .addTo(_m);
                            _on = true;
                            btn.innerHTML = '\u00d7 Ocultar intersecci\u00f3n';
                            btn.style.background = '#e8d5f5';
                            btn.style.color = '#4A235A';
                        }}
                    }});
                    return div;
                }}
            }});
            new IntersectCtrl().addTo(_m);
        }})();
        """

# Turf.js CDN para calcular intersecciones en el navegador
turf_tag = '<script src="https://cdn.jsdelivr.net/npm/@turf/turf@6.5.0/turf.min.js"></script>\n'
assert '</head>' in html, "no se encuentra </head>"
html = html.replace('</head>', turf_tag + '</head>', 1)

# Inyectar justo antes del cierre </script> del bloque principal
end_script_anchor = "        \n</script>"
if end_script_anchor not in html:
    end_script_anchor = "\n</script>"
assert end_script_anchor in html, "no se encuentra </script> final"
html = html.replace(end_script_anchor, popup_js + intersection_js + end_script_anchor, 1)

with open(MAPA, "w", encoding="utf-8") as f:
    f.write(html)
print("mapa.html actualizado correctamente.")
print(f"  Capas TP: {html.count('feature_group_tp30')} refs a tp30")
print(f"  Overlays nuevos: {'En TP a Alonso' in html}")
print(f"  Leyenda: {'TP a Alonso' in html}")
print(f"  Marcador: {'marker_tp_dest' in html}")
print(f"  Popups accesos: {'_tpAcc' in html}")
print(f"  Boton interseccion: {'IntersectCtrl' in html}")
print(f"  Turf.js: {'turf.min.js' in html}")
