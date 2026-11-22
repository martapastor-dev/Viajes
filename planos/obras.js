// Metros lineales de muro a tirar y a construir respecto al original.
// Cada muro es una recta; sobre ella se guarda el conjunto de tramos macizos (lados de polígonos menos huecos).
function clavesRecta(a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy);
  let ux = dx / L, uy = dy / L;
  if (ux < -1e-9 || (Math.abs(ux) < 1e-9 && uy < 0)) { ux = -ux; uy = -uy; }
  const off = -uy * a[0] + ux * a[1];
  return { clave: `${ux.toFixed(3)},${uy.toFixed(3)},${off.toFixed(2)}`, ux, uy, off };
}
function proyectar(r, p) { return r.ux * p[0] + r.uy * p[1]; }
function unir(tramos) {
  const t = tramos.filter(([i, f]) => f - i > 1e-6).sort((p, q) => p[0] - q[0]), out = [];
  for (const [i, f] of t) {
    if (out.length && i <= out[out.length - 1][1] + 1e-6) out[out.length - 1][1] = Math.max(out[out.length - 1][1], f);
    else out.push([i, f]);
  }
  return out;
}
function restar(a, b) {
  let res = a.map(x => x.slice());
  for (const [bi, bf] of b) {
    const nuevo = [];
    for (const [i, f] of res) {
      if (bf <= i || bi >= f) { nuevo.push([i, f]); continue; }
      if (bi > i) nuevo.push([i, bi]);
      if (bf < f) nuevo.push([bf, f]);
    }
    res = nuevo;
  }
  return res.filter(([i, f]) => f - i > 0.005);
}
function murosMacizos(poligonos, huecos) {
  const rectas = {};
  for (const p of poligonos) for (let k = 0; k < p.length; k++) {
    const a = p[k], b = p[(k + 1) % p.length], r = clavesRecta(a, b);
    const e = rectas[r.clave] || (rectas[r.clave] = { r, tramos: [] });
    const [i, f] = [proyectar(r, a), proyectar(r, b)].sort((x, y) => x - y);
    e.tramos.push([i, f]);
  }
  for (const k in rectas) rectas[k].tramos = unir(rectas[k].tramos);
  for (const h of huecos) {
    const r = clavesRecta(h.a, h.b), e = rectas[r.clave];
    if (!e) continue;
    const [i, f] = [proyectar(r, h.a), proyectar(r, h.b)].sort((x, y) => x - y);
    e.tramos = restar(e.tramos, [[i, f]]);
  }
  return rectas;
}
function compararMuros(original, variante, fijos) {
  const pol = v => [...fijos.map(f => f.poligono), ...v.estancias.map(e => e.poligono)];
  const mo = murosMacizos(pol(original), original.huecos), mv = murosMacizos(pol(variante), variante.huecos);
  const aSeg = (r, [i, f]) => [[r.ux * i - r.uy * r.off, r.uy * i + r.ux * r.off], [r.ux * f - r.uy * r.off, r.uy * f + r.ux * r.off]];
  const tirar = [], construir = [];
  for (const k of new Set([...Object.keys(mo), ...Object.keys(mv)])) {
    const r = (mo[k] || mv[k]).r, o = mo[k] ? mo[k].tramos : [], v = mv[k] ? mv[k].tramos : [];
    for (const t of restar(o, v)) tirar.push({ seg: aSeg(r, t), largo: t[1] - t[0] });
    for (const t of restar(v, o)) construir.push({ seg: aSeg(r, t), largo: t[1] - t[0] });
  }
  const suma = l => l.reduce((s, x) => s + x.largo, 0);
  return { tirar, construir, mTirar: suma(tirar), mConstruir: suma(construir) };
}
if (typeof module !== 'undefined') module.exports = { compararMuros };
