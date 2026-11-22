const COLORES = { dormitorio: '#f3dfb8', salon: '#efd3a8', csc: '#efd3a8', cocina: '#d9e7c8', bano: '#cfe3ef', hall: '#e8e1d4', terraza: '#e4e4e4' };
const NS = 'http://www.w3.org/2000/svg';
const params = new URLSearchParams(location.search);
const idPlano = params.get('id');
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
  const svg = el('svg', { viewBox: '-0.6 -0.5 10.4 9.5', xmlns: NS });
  const o = plano.original, s = o.px_por_m;
  const gFondo = el('g', {}, svg);
  for (const f of plano.fijos) el('polygon', { points: pts(f.poligono), fill: COLORES[f.tipo], stroke: '#666', 'stroke-width': 0.05, 'stroke-dasharray': '0.12 0.06' }, gFondo);
  for (const e of v.estancias) el('polygon', { points: pts(e.poligono), fill: COLORES[e.tipo] || '#eee', 'fill-opacity': 0.9 }, gFondo);
  el('polygon', { points: pts(plano.zona_humeda), fill: '#3a86ff', 'fill-opacity': 0.12, stroke: '#3a86ff', 'stroke-width': 0.04, 'stroke-dasharray': '0.15 0.08', id: 'capaHumeda' }, svg);
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
  const gTxt = el('g', { 'text-anchor': 'middle', fill: '#222' }, svg);
  for (const e of [...plano.fijos, ...v.estancias]) {
    const [cx, cy] = e.etiqueta || centroide(e.poligono);
    const n = el('text', { x: cx, y: cy, 'font-size': 0.24, 'font-weight': 600 }, gTxt); n.textContent = e.nombre;
    const a = el('text', { x: cx, y: cy + 0.3, 'font-size': 0.22 }, gTxt); a.textContent = fmt(areaUtil(e.poligono)) + ' m²';
  }
  el('image', { href: o.archivo, x: -o.origen_px[0] / s, y: -o.origen_px[1] / s, width: o.ancho_px / s, height: o.alto_px / s, opacity: 0.5 }, gFoto);
  svg.appendChild(gFoto);
  const gEsc = el('g', {}, svg);
  el('line', { x1: 0, y1: 8.85, x2: 1, y2: 8.85, stroke: '#222', 'stroke-width': 0.04 }, gEsc);
  const te = el('text', { x: 1.1, y: 8.92, 'font-size': 0.2 }, gEsc); te.textContent = '1 m';
  document.getElementById('plano').replaceChildren(svg);
  aplicarCapas();
}

function dibujarHueco(h, g, t) {
  const [ax, ay] = h.a, [bx, by] = h.b, dx = bx - ax, dy = by - ay, L = Math.hypot(dx, dy);
  el('line', { x1: ax, y1: ay, x2: bx, y2: by, stroke: '#fff', 'stroke-width': t + 0.02 }, g);
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

function aplicarCapas() {
  const ver = (id, capa) => { const c = document.getElementById(capa); if (c) c.style.display = document.getElementById(id).checked ? '' : 'none'; };
  ver('verOriginal', 'capaOriginal'); ver('verHumeda', 'capaHumeda'); ver('verMuebles', 'capaMuebles');
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
  const fuera = humedas.filter(([, p]) => !p.every(q => dentro(q, plano.zona_humeda))).map(([n]) => n);
  const r = [];
  const fila = (ok, texto, detalle, opcional) => r.push({ ok, texto, detalle, opcional });
  fila(dorms[0] >= req.dormitorio_grande_min, `Dormitorio de mínimo ${fmt(req.dormitorio_grande_min)} m²`, dorms[0] ? fmt(dorms[0]) + ' m²' : 'no hay');
  fila(dorms[1] >= req.dormitorio_segundo_min, `Otro dormitorio de mínimo ${fmt(req.dormitorio_segundo_min)} m²`, dorms[1] ? fmt(dorms[1]) + ' m²' : 'no hay');
  fila(csc[0] >= req.cocina_salon_comedor_min, `Cocina-salón-comedor de mínimo ${fmt(req.cocina_salon_comedor_min)} m²`, csc[0] ? fmt(csc[0]) + ' m²' : 'cocina cerrada');
  fila(banos[0] >= req.bano_principal_min, `Baño de mínimo ${fmt(req.bano_principal_min)} m²`, banos[0] ? fmt(banos[0]) + ' m²' : 'no hay');
  fila(true, 'Terraza fuera de la parte editable', 'se mantiene igual');
  fila(fuera.length === 0, 'Cuartos húmedos en la zona de bajantes', fuera.length ? 'fuera: ' + fuera.join(', ') : 'todos dentro');
  fila(banos[1] >= req.bano_segundo_min, `Segundo baño de ${fmt(req.bano_segundo_min)} m² (opcional)`, banos[1] ? fmt(banos[1]) + ' m²' : 'no hay', true);
  return r;
}

function mostrar(id) {
  actual = plano.variantes.find(v => v.id === id) || plano.variantes[0];
  document.querySelectorAll('#variantes button').forEach(b => b.classList.toggle('activo', b.dataset.id === actual.id));
  dibujar(actual);
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
    <p><strong>${precio}</strong> · ${a.superficie} m² útiles (${a.superficie_construida} construidos) · ${m2} €/m²</p>
    <p class="pequeno">${a.habitaciones} hab. · ${a.banos} baño · Planta ${a.planta}<br>
    ${a.direccion}, ${a.barrio}<br>${a.estado} · Orientación ${a.orientacion} · ${a.agencia}<br>${a.notas}</p>
    <p><a href="${a.url}" target="_blank" rel="noopener">Ver anuncio en ${a.portal}</a> ·
    <a href="https://www.google.com/maps?q=${a.coordenadas.join(',')}" target="_blank" rel="noopener">Mapa</a></p>`;
}

Promise.all([fetch(idPlano + '/plano.json').then(r => r.json()), fetch('requisitos.json').then(r => r.json())]).then(([p, r]) => {
  plano = p; req = r;
  plano.original.archivo = idPlano + '/' + plano.original.archivo;
  document.title = plano.titulo;
  document.getElementById('titulo').textContent = plano.titulo;
  document.getElementById('variantes').innerHTML = plano.variantes.map(v => `<button data-id="${v.id}">${v.nombre}</button>`).join('');
  document.querySelectorAll('#variantes button').forEach(b => b.onclick = () => mostrar(b.dataset.id));
  ['verOriginal', 'verHumeda', 'verMuebles'].forEach(i => document.getElementById(i).onchange = aplicarCapas);
  mostrarAnuncio(plano.anuncio);
  mostrar(params.get('v') || (plano.variantes[1] || plano.variantes[0]).id);
});
