const COLORES = { dormitorio: '#f3dfb8', salon: '#efd3a8', csc: '#efd3a8', cocina: '#d9e7c8', bano: '#cfe3ef', hall: '#e8e1d4', terraza: '#e4e4e4' };
const NS = 'http://www.w3.org/2000/svg';
const params = new URLSearchParams(location.search);
const idPlano = /^[a-z0-9-]+$/.test(params.get('id') || '') ? params.get('id') : '';
let plano, req, actual;

function areaBruta(p) {
  let s = 0;
  for (let i = 0; i < p.length; i++) { const [x1, y1] = p[i], [x2, y2] = p[(i + 1) % p.length]; s += x1 * y2 - x2 * y1; }
  return Math.abs(s) / 2;
}
function perimetro(p) {
  let s = 0;
  for (let i = 0; i < p.length; i++) { const [x1, y1] = p[i], [x2, y2] = p[(i + 1) % p.length]; s += Math.hypot(x2 - x1, y2 - y1); }
  return s;
}
// Polígonos a eje de muro: se descuenta medio muro en todo el perímetro.
function areaUtil(p) { const t = plano.grosor_muro; return areaBruta(p) - perimetro(p) * t / 2 + t * t; }
function centroide(p) {
  let a = 0, cx = 0, cy = 0;
  for (let i = 0; i < p.length; i++) {
    const [x1, y1] = p[i], [x2, y2] = p[(i + 1) % p.length], f = x1 * y2 - x2 * y1;
    a += f; cx += (x1 + x2) * f; cy += (y1 + y2) * f;
  }
  return [cx / (3 * a), cy / (3 * a)];
}
function enBorde(pt, p, eps) {
  for (let i = 0; i < p.length; i++) {
    const [ax, ay] = p[i], [bx, by] = p[(i + 1) % p.length];
    const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
    const t = Math.max(0, Math.min(1, ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / L2));
    if (Math.hypot(pt[0] - ax - t * dx, pt[1] - ay - t * dy) < eps) return true;
  }
  return false;
}
const zonasHumedas = () => Array.isArray(plano.zona_humeda[0][0]) ? plano.zona_humeda : [plano.zona_humeda];

function dentro(pt, p) {
  if (enBorde(pt, p, 0.03)) return true;
  let c = false;
  for (let i = 0, j = p.length - 1; i < p.length; j = i++) {
    const [xi, yi] = p[i], [xj, yj] = p[j];
    if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi) c = !c;
  }
  return c;
}
const fmt = n => n.toLocaleString('es-ES', { minimumFractionDigits: 1, maximumFractionDigits: 1 });

function el(tag, attrs, padre) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (padre) padre.appendChild(e);
  return e;
}
const pts = p => p.map(q => q.join(',')).join(' ');

function dibujar(v) {
  const t = plano.grosor_muro;
  const todos = [...plano.fijos, ...plano.variantes.flatMap(x => x.estancias)].flatMap(e => e.poligono);
  const xs = todos.map(q => q[0]), ys = todos.map(q => q[1]);
  const x0 = Math.min(...xs) - 0.6, y0 = Math.min(...ys) - 0.5, yMax = Math.max(...ys);
  const svg = el('svg', { viewBox: `${x0} ${y0} ${Math.max(...xs) + 0.6 - x0} ${yMax + 0.9 - y0}`, xmlns: NS });
  const o = plano.original, s = o.px_por_m;
  const gFondo = el('g', {}, svg);
  for (const f of plano.fijos) el('polygon', { points: pts(f.poligono), fill: COLORES[f.tipo], stroke: '#666', 'stroke-width': 0.05, 'stroke-dasharray': '0.12 0.06' }, gFondo);
  for (const e of v.estancias) el('polygon', { points: pts(e.poligono), fill: COLORES[e.tipo] || '#eee', 'fill-opacity': 0.9 }, gFondo);
  const gHumeda = el('g', { id: 'capaHumeda' }, svg);
  for (const z of zonasHumedas()) el('polygon', { points: pts(z), fill: '#3a86ff', 'fill-opacity': 0.12, stroke: '#3a86ff', 'stroke-width': 0.04, 'stroke-dasharray': '0.15 0.08' }, gHumeda);
  const gMuebles = el('g', { id: 'capaMuebles' }, svg);
  const gFoto = el('g', { id: 'capaOriginal', 'pointer-events': 'none' });
  for (const m of v.muebles || []) {
    if (m.forma === 'fregadero') {
      el('rect', { x: m.x, y: m.y, width: m.w, height: m.h, rx: 0.08, fill: '#fff', stroke: '#3a86ff', 'stroke-width': 0.03 }, gMuebles);
    } else {
      el('rect', { x: m.x, y: m.y, width: m.w, height: m.h, fill: '#fff', 'fill-opacity': 0.75, stroke: '#888', 'stroke-width': 0.02 }, gMuebles);
    }
    if (m.nombre && m.forma !== 'fregadero') {
      const tx = el('text', { x: m.x + m.w / 2, y: m.y + m.h / 2 + 0.06, 'font-size': 0.16, 'text-anchor': 'middle', fill: '#777' }, gMuebles);
      tx.textContent = m.nombre;
    }
  }
  const gMuros = el('g', { fill: 'none', stroke: '#222', 'stroke-width': t, 'stroke-linejoin': 'miter', 'stroke-linecap': 'square' }, svg);
  for (const e of v.estancias) el('polygon', { points: pts(e.poligono) }, gMuros);
  const gHuecos = el('g', {}, svg);
  for (const h of v.huecos) dibujarHueco(h, gHuecos, t);
  const gObras = el('g', { id: 'capaObras', 'stroke-linecap': 'butt' }, svg);
  const obras = obrasDe(v);
  for (const o of obras.tirar) el('line', { x1: o.seg[0][0], y1: o.seg[0][1], x2: o.seg[1][0], y2: o.seg[1][1], stroke: '#d62828', 'stroke-width': t, 'stroke-dasharray': '0.1 0.06', opacity: 0.85 }, gObras);
  for (const o of obras.construir) el('line', { x1: o.seg[0][0], y1: o.seg[0][1], x2: o.seg[1][0], y2: o.seg[1][1], stroke: '#2a9d8f', 'stroke-width': t + 0.02 }, gObras);
  const gTxt = el('g', { 'text-anchor': 'middle', fill: '#222' }, svg);
  for (const e of [...plano.fijos, ...v.estancias]) {
    const [cx, cy] = e.etiqueta || centroide(e.poligono);
    const n = el('text', { x: cx, y: cy, 'font-size': 0.24, 'font-weight': 600 }, gTxt); n.textContent = e.nombre;
    const a = el('text', { x: cx, y: cy + 0.3, 'font-size': 0.22 }, gTxt); a.textContent = fmt(areaUtil(e.poligono)) + ' m²';
  }
  el('image', { href: o.archivo, x: -o.origen_px[0] / s, y: -o.origen_px[1] / s, width: o.ancho_px / s, height: o.alto_px / s, opacity: 0.5 }, gFoto);
  svg.appendChild(gFoto);
  const gEsc = el('g', {}, svg);
  el('line', { x1: 0, y1: yMax + 0.27, x2: 1, y2: yMax + 0.27, stroke: '#222', 'stroke-width': 0.04 }, gEsc);
  const te = el('text', { x: 1.1, y: yMax + 0.34, 'font-size': 0.2 }, gEsc); te.textContent = '1 m';
  document.getElementById('plano').replaceChildren(svg);
  aplicarCapas();
}

function dibujarHueco(h, g, t) {
  const [ax, ay] = h.a, [bx, by] = h.b, dx = bx - ax, dy = by - ay, L = Math.hypot(dx, dy);
  el('line', { x1: ax, y1: ay, x2: bx, y2: by, stroke: '#fff', 'stroke-width': t + 0.02 }, g);
  if (h.tipo === 'paso') return;
  if (h.tipo === 'ventana' || h.tipo === 'balconera') {
    const nx = -dy / L * t / 3, ny = dx / L * t / 3;
    for (const k of [-1, 0, 1]) el('line', { x1: ax + k * nx, y1: ay + k * ny, x2: bx + k * nx, y2: by + k * ny, stroke: '#7a8b99', 'stroke-width': 0.02 }, g);
    for (const [x, y] of [h.a, h.b]) el('line', { x1: x - nx * 1.6, y1: y - ny * 1.6, x2: x + nx * 1.6, y2: y + ny * 1.6, stroke: '#222', 'stroke-width': 0.03 }, g);
    return;
  }
  let nx = -dy / L, ny = dx / L;
  if (h.hacia && ((h.hacia[0] - ax) * nx + (h.hacia[1] - ay) * ny) < 0) { nx = -nx; ny = -ny; }
  const hx = ax + nx * L, hy = ay + ny * L;
  const barrido = (dx * ny - dy * nx) > 0 ? 0 : 1;
  const color = h.tipo === 'entrada' ? '#b3261e' : '#555';
  el('line', { x1: ax, y1: ay, x2: hx, y2: hy, stroke: color, 'stroke-width': 0.035 }, g);
  el('path', { d: `M ${hx} ${hy} A ${L} ${L} 0 0 ${barrido} ${bx} ${by}`, fill: 'none', stroke: color, 'stroke-width': 0.02 }, g);
}

function obrasDe(v) {
  const original = plano.variantes[0];
  if (v === original) return { tirar: [], construir: [], mTirar: 0, mConstruir: 0 };
  return compararMuros(original, v, plano.fijos);
}

function entre(seg, estancias) {
  const m = [(seg[0][0] + seg[1][0]) / 2, (seg[0][1] + seg[1][1]) / 2];
  const n = [...plano.fijos, ...estancias].filter(e => enBorde(m, e.poligono, 0.03)).map(e => e.nombre);
  return n.length > 1 ? n.join(' – ') : (n[0] || '') + ' (fachada)';
}

function trocear(seg, estancias) {
  const [a, b] = seg, dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy;
  const ts = [0, 1];
  for (const e of [...plano.fijos, ...estancias]) for (const q of e.poligono) {
    const t = ((q[0] - a[0]) * dx + (q[1] - a[1]) * dy) / L2;
    const d = Math.abs((q[0] - a[0]) * dy - (q[1] - a[1]) * dx) / Math.sqrt(L2);
    if (t > 1e-6 && t < 1 - 1e-6 && d < 0.03) ts.push(t);
  }
  ts.sort((x, y) => x - y);
  const p = t => [a[0] + dx * t, a[1] + dy * t];
  return ts.slice(1).map((t, i) => [p(ts[i]), p(t)]).filter(([u, w]) => Math.hypot(w[0] - u[0], w[1] - u[1]) > 1e-4);
}

function mostrarObras(v) {
  const o = obrasDe(v), caja = document.getElementById('obras');
  if (v === plano.variantes[0]) { caja.innerHTML = '<p class="pequeno">Distribución original: sin obras.</p>'; return; }
  const fmt2 = n => n.toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const lista = (items, estancias) => {
    const grupos = {};
    for (const x of items) for (const s of trocear(x.seg, estancias)) {
      const k = entre(s, estancias); grupos[k] = (grupos[k] || 0) + Math.hypot(s[1][0] - s[0][0], s[1][1] - s[0][1]);
    }
    return Object.entries(grupos).sort((a, b) => b[1] - a[1])
      .map(([k, m]) => `<tr><td>${k}</td><td class="num">${fmt2(m)} m</td></tr>`).join('');
  };
  caja.innerHTML = `
    <p><span style="color:#d62828">▬ Tirar: <strong>${fmt2(o.mTirar)} m</strong></span> ·
       <span style="color:#2a9d8f">▬ Construir: <strong>${fmt2(o.mConstruir)} m</strong></span></p>
    <table>
      <tr><th colspan="2" style="color:#d62828">Tirar (entre estancias originales)</th></tr>${lista(o.tirar, plano.variantes[0].estancias)}
      <tr><th colspan="2" style="color:#2a9d8f">Construir (entre estancias nuevas)</th></tr>${lista(o.construir, v.estancias)}
    </table>
    <p class="pequeno">Metros lineales por el eje del muro, sin contar huecos de puertas y ventanas. Cerrar una puerta antigua cuenta como construir; abrir una nueva en un muro que se queda, como tirar.</p>`;
}

function aplicarCapas() {
  const ver = (id, capa) => { const c = document.getElementById(capa); if (c) c.style.display = document.getElementById(id).checked ? '' : 'none'; };
  ver('verOriginal', 'capaOriginal'); ver('verHumeda', 'capaHumeda'); ver('verMuebles', 'capaMuebles'); ver('verObras', 'capaObras');
}

const esquinas = m => [[m.x, m.y], [m.x + m.w, m.y], [m.x + m.w, m.y + m.h], [m.x, m.y + m.h]];

function conflictos(v) {
  const muebles = (v.muebles || []).filter(m => m.forma !== 'fregadero');
  const solapa = (a, b) => Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > 0.01 && Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y) > 0.01;
  const r = [];
  for (let i = 0; i < muebles.length; i++) for (let j = i + 1; j < muebles.length; j++)
    if (solapa(muebles[i], muebles[j])) r.push(`${muebles[i].nombre || 'Encimera'} y ${muebles[j].nombre || 'Encimera'}`);
  for (const h of v.huecos.filter(h => h.tipo === 'puerta' || h.tipo === 'entrada')) {
    const [ax, ay] = h.a, [bx, by] = h.b, L = Math.hypot(bx - ax, by - ay);
    let nx = -(by - ay) / L, ny = (bx - ax) / L;
    if (h.hacia && ((h.hacia[0] - ax) * nx + (h.hacia[1] - ay) * ny) < 0) { nx = -nx; ny = -ny; }
    const xs = [ax, bx, ax + nx * L, bx + nx * L], ys = [ay, by, ay + ny * L, by + ny * L];
    const caja = { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
    for (const m of muebles) {
      if (!solapa(caja, m)) continue;
      const x0 = Math.max(caja.x, m.x), x1 = Math.min(caja.x + caja.w, m.x + m.w), y0 = Math.max(caja.y, m.y), y1 = Math.min(caja.y + caja.h, m.y + m.h);
      const cx = Math.max(x0, Math.min(ax, x1)), cy = Math.max(y0, Math.min(ay, y1));
      if (Math.hypot(cx - ax, cy - ay) < L - 0.01) r.push(`${m.nombre || 'Encimera'} tapa una puerta`);
    }
  }
  return r;
}

function puertasBanoACocina(v) {
  const cocinas = v.estancias.flatMap(e => e.tipo === 'cocina' ? [e.poligono] : e.zona_cocina ? [e.zona_cocina] : []);
  const r = [];
  for (const h of v.huecos.filter(h => h.tipo === 'puerta' || h.tipo === 'paso')) {
    const [ax, ay] = h.a, [bx, by] = h.b, L = Math.hypot(bx - ax, by - ay);
    const mx = (ax + bx) / 2, my = (ay + by) / 2, nx = -(by - ay) / L * 0.3, ny = (bx - ax) / L * 0.3;
    const lados = [[mx + nx, my + ny], [mx - nx, my - ny]];
    for (const [i, q] of lados.entries()) {
      const bano = v.estancias.find(e => e.tipo === 'bano' && dentro(q, e.poligono));
      if (bano && cocinas.some(c => dentro(lados[1 - i], c))) r.push(bano.nombre);
    }
  }
  return r;
}

function evaluar(v) {
  const area = e => areaUtil(e.poligono);
  const dorms = v.estancias.filter(e => e.tipo === 'dormitorio').map(area).sort((a, b) => b - a);
  const banos = v.estancias.filter(e => e.tipo === 'bano').map(area).sort((a, b) => b - a);
  const csc = v.estancias.filter(e => e.tipo === 'csc').map(area).sort((a, b) => b - a);
  const humedas = [];
  for (const e of v.estancias) {
    if (e.tipo === 'bano' || e.tipo === 'cocina') humedas.push([e.nombre, e.poligono]);
    if (e.zona_cocina) humedas.push(['Cocina', e.zona_cocina]);
  }
  const fuera = humedas.filter(([, p]) => !zonasHumedas().some(z => p.every(q => dentro(q, z)))).map(([n]) => n);
  const r = [];
  const fila = (ok, texto, detalle, opcional) => r.push({ ok, texto, detalle, opcional });
  fila(dorms[0] >= req.dormitorio_grande_min, `Dormitorio de mínimo ${fmt(req.dormitorio_grande_min)} m²`, dorms[0] ? fmt(dorms[0]) + ' m²' : 'no hay');
  fila(dorms[1] >= req.dormitorio_segundo_min, `Otro dormitorio de mínimo ${fmt(req.dormitorio_segundo_min)} m²`, dorms[1] ? fmt(dorms[1]) + ' m²' : 'no hay');
  fila(csc[0] >= req.cocina_salon_comedor_min, `Cocina-salón-comedor de mínimo ${fmt(req.cocina_salon_comedor_min)} m²`, csc[0] ? fmt(csc[0]) + ' m²' : 'cocina cerrada');
  fila(banos[0] >= req.bano_principal_min, `Baño de mínimo ${fmt(req.bano_principal_min)} m²`, banos[0] ? fmt(banos[0]) + ' m²' : 'no hay');
  const dormsE = v.estancias.filter(e => e.tipo === 'dormitorio').sort((a, b) => area(b) - area(a));
  const muebles = v.muebles || [];
  const cabe = (m, [l, f]) => Math.max(m.w, m.h) >= l - 1e-6 && Math.min(m.w, m.h) >= f - 1e-6;
  const metido = (m, p) => esquinas(m).every(q => dentro(q, p));
  const cm = ([l, f]) => `${Math.round(l * 100)} × ${Math.round(f * 100)} cm`;
  const escritorio = (e, med) => e && muebles.some(m => m.tipo === 'escritorio' && cabe(m, med) && metido(m, e.poligono));
  const textoEsc = (e, med) => muebles.filter(m => m.tipo === 'escritorio' && e && metido(m, e.poligono)).map(m => cm([Math.max(m.w, m.h), Math.min(m.w, m.h)]))[0] || 'no hay';
  fila(escritorio(dormsE[0], req.escritorio_dormitorio_grande), `Escritorio de mínimo ${cm(req.escritorio_dormitorio_grande)} en el dormitorio grande`, textoEsc(dormsE[0]));
  fila(escritorio(dormsE[1], req.escritorio_dormitorio_segundo), `Escritorio de mínimo ${cm(req.escritorio_dormitorio_segundo)} en el otro dormitorio`, textoEsc(dormsE[1]));
  const encimeras = muebles.filter(m => m.tipo === 'encimera');
  const fondos = encimeras.map(m => Math.min(m.w, m.h));
  fila(encimeras.length > 0 && fondos.every(f => f >= req.encimera_fondo - 1e-6), `Encimeras de ${Math.round(req.encimera_fondo * 100)} cm de fondo`, encimeras.length ? [...new Set(fondos.map(f => Math.round(f * 100) + ' cm'))].join(', ') : 'no hay');
  const cocinas = v.estancias.filter(e => e.tipo === 'cocina' || e.tipo === 'csc').map(e => e.zona_cocina || e.poligono);
  const nevera = muebles.find(m => m.tipo === 'nevera' && cocinas.some(p => metido(m, p)));
  fila(!!nevera && cabe(nevera, [Math.max(...req.nevera), Math.min(...req.nevera)]), `Nevera estándar (${cm(req.nevera)}) en la cocina`, nevera ? cm([nevera.w, nevera.h]) : 'no hay');
  const choques = conflictos(v);
  fila(choques.length === 0, 'Muebles sin tapar puertas ni solaparse', choques.length ? choques.join('; ') : 'todo libre');
  fila(true, 'Terraza fuera de la parte editable', 'se mantiene igual');
  fila(fuera.length === 0, 'Cuartos húmedos en la zona de bajantes', fuera.length ? 'fuera: ' + fuera.join(', ') : 'todos dentro');
  if (req.bano_sin_puerta_a_cocina) {
    const malas = puertasBanoACocina(v);
    fila(malas.length === 0, 'Ninguna puerta de baño da a la cocina', malas.length ? 'da a la cocina: ' + malas.join(', ') : 'ninguna');
  }
  fila(banos[1] >= req.bano_segundo_min, `Segundo baño de ${fmt(req.bano_segundo_min)} m² (opcional)`, banos[1] ? fmt(banos[1]) + ' m²' : 'no hay', true);
  return r;
}

function mostrar(id) {
  actual = plano.variantes.find(v => v.id === id) || plano.variantes[0];
  document.querySelectorAll('#variantes button').forEach(b => b.classList.toggle('activo', b.dataset.id === actual.id));
  dibujar(actual);
  mostrarObras(actual);
  document.getElementById('descripcion').textContent = actual.descripcion || '';
  document.getElementById('notas').innerHTML = (actual.notas || []).map(n => `<li>${n}</li>`).join('');
  document.getElementById('checks').innerHTML = evaluar(actual).map(c => {
    const cls = c.ok ? 'cumple' : (c.opcional ? 'opcional' : 'falla');
    return `<li class="${cls}">${c.ok ? '✔' : (c.opcional ? '–' : '✘')} ${c.texto}: <strong>${c.detalle}</strong></li>`;
  }).join('');
  const filas = actual.estancias.map(e => [e.nombre, areaUtil(e.poligono)]);
  const total = filas.reduce((s, f) => s + f[1], 0);
  const terr = plano.fijos.map(f => [f.nombre + ' (fija)', areaUtil(f.poligono)]);
  document.getElementById('tabla').innerHTML =
    filas.map(([n, a]) => `<tr><td>${n}</td><td class="num">${fmt(a)} m²</td></tr>`).join('') +
    `<tr><th>Total interior</th><th class="num">${fmt(total)} m²</th></tr>` +
    terr.map(([n, a]) => `<tr><td>${n}</td><td class="num">${fmt(a)} m²</td></tr>`).join('');
  const u = new URL(location); u.searchParams.set('v', actual.id); history.replaceState(null, '', u);
}

function mostrarAnuncio(a) {
  const precio = a.precio.toLocaleString('es-ES') + ' €';
  const m2 = Math.round(a.precio / a.superficie).toLocaleString('es-ES');
  document.getElementById('anuncio').innerHTML = `
    <p><strong>${precio}</strong> · ${a.superficie} m²${a.superficie_construida ? ` útiles (${a.superficie_construida} construidos)` : ''} · ${m2} €/m²</p>
    <p class="pequeno">${a.habitaciones} hab. · ${a.banos} baño · Planta ${a.planta}<br>
    ${a.direccion}, ${a.barrio}<br>${a.estado}${a.orientacion ? ' · Orientación ' + a.orientacion : ''} · ${a.agencia}<br>${a.notas}</p>
    <p><a href="${a.url}" target="_blank" rel="noopener">Ver anuncio en ${a.portal}</a> ·
    <a href="https://www.google.com/maps?q=${a.coordenadas.join(',')}" target="_blank" rel="noopener">Mapa</a></p>`;
}

Promise.all([fetch(idPlano + '/plano.json', { cache: 'no-cache' }).then(r => r.json()), fetch('requisitos.json', { cache: 'no-cache' }).then(r => r.json())]).then(([p, r]) => {
  plano = p; req = { ...r, ...(p.requisitos || {}) };
  plano.original.archivo = idPlano + '/' + plano.original.archivo;
  document.title = plano.titulo;
  document.getElementById('titulo').textContent = plano.titulo;
  document.getElementById('variantes').innerHTML = plano.variantes.map(v => `<button data-id="${v.id}">${v.nombre}</button>`).join('');
  document.querySelectorAll('#variantes button').forEach(b => b.onclick = () => mostrar(b.dataset.id));
  ['verOriginal', 'verHumeda', 'verMuebles', 'verObras'].forEach(i => document.getElementById(i).onchange = aplicarCapas);
  mostrarAnuncio(plano.anuncio);
  mostrar(params.get('v') || (plano.variantes[1] || plano.variantes[0]).id);
});
