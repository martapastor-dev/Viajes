#!/usr/bin/env python3
"""Sirve casas/ + API de configuración y ejecución de la búsqueda."""
import json, os, subprocess, sys, threading, time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)
import params as params_mod

DOCROOT = os.path.join(HOME, 'casas')
if not os.path.isdir(DOCROOT):
    DOCROOT = HOME  # en checkout del repo, config.html/index.html están junto al script
LOG = os.path.join(HOME, 'run_daily.log')
STATUS = os.path.join(HOME, 'run_status.json')
MARKS = os.path.join(DOCROOT, 'marks.json')
_lock = threading.Lock()
_marks_lock = threading.Lock()


def read_marks():
    try:
        m = json.load(open(MARKS))
        return {'fav': list(m.get('fav') or []), 'del': list(m.get('del') or []),
                'seen': list(m.get('seen') or []), 'notes': dict(m.get('notes') or {})}
    except Exception:
        return {'fav': [], 'del': [], 'seen': [], 'notes': {}}


def write_marks(m):
    clean = {k: m.get(k) for k in ('fav', 'del', 'seen', 'notes')}
    for k in ('fav', 'del', 'seen'):
        clean[k] = [str(u) for u in (clean.get(k) or []) if u]
    clean['notes'] = {str(u): str(t)[:2000] for u, t in (clean.get('notes') or {}).items() if u and str(t).strip()}
    with _marks_lock:
        tmp = MARKS + '.tmp'
        json.dump(clean, open(tmp, 'w'), ensure_ascii=False)
        os.replace(tmp, MARKS)
    return clean


def apply_mark_op(op):
    """Un cambio puntual (una marca o una nota) sobre el estado guardado."""
    o = op.get('op')
    u = str(op.get('url') or '')
    k = op.get('key')
    if not u or (o == 'set' and k not in ('fav', 'del', 'seen')) or o not in ('set', 'note'):
        return None
    with _marks_lock:
        m = read_marks()
        if o == 'set':
            s = set(m[k])
            if op.get('value'):
                s.add(u)
            else:
                s.discard(u)
            m[k] = sorted(s)
        else:
            t = str(op.get('text') or '')[:2000]
            if t.strip():
                m['notes'][u] = t
            else:
                m['notes'].pop(u, None)
        tmp = MARKS + '.tmp'
        json.dump(m, open(tmp, 'w'), ensure_ascii=False)
        os.replace(tmp, MARKS)
        return m


def read_status():
    try:
        return json.load(open(STATUS))
    except Exception:
        return {'state': 'idle'}


def tail_log(n=40):
    try:
        lines = open(LOG, errors='replace').read().splitlines()
        return lines[-n:]
    except Exception:
        return []


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=DOCROOT, **kw)

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ('/', ''):
            self.path = '/config.html'
            return super().do_GET()
        if self.path.startswith('/api/config'):
            return self._json({'params': params_mod.load(), 'defaults': params_mod.DEFAULTS})
        if self.path.startswith('/api/status'):
            s = read_status()
            s['log'] = tail_log()
            return self._json(s)
        if self.path.startswith('/api/marks'):
            return self._json(read_marks())
        return super().do_GET()

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n) if n else b'{}'
        try:
            data = json.loads(body or b'{}')
        except Exception:
            return self._json({'error': 'json inválido'}, 400)

        if self.path.startswith('/api/config'):
            cur = params_mod.save(data.get('params', data))
            return self._json({'ok': True, 'params': cur})

        if self.path.startswith('/api/marks'):
            if isinstance(data, dict) and data.get('op'):
                out = apply_mark_op(data)
                if out is None:
                    return self._json({'error': 'op inválida'}, 400)
                return self._json({'ok': True, 'marks': out})
            return self._json({'ok': True, 'marks': write_marks(data)})

        if self.path.startswith('/api/run'):
            with _lock:
                st = read_status()
                if st.get('state') == 'running':
                    return self._json({'error': 'ya hay una búsqueda en marcha', 'state': 'running'}, 409)
                if isinstance(data, dict) and data.get('params'):
                    params_mod.save(data['params'])
                json.dump({'state': 'running', 'started': time.time()}, open(STATUS, 'w'))
                threading.Thread(target=self._run, daemon=True).start()
                return self._json({'ok': True, 'state': 'running'})

        return self._json({'error': 'no encontrado'}, 404)

    @staticmethod
    def _run():
        t0 = time.time()
        try:
            with open(LOG, 'w') as f:
                r = subprocess.run(['bash', os.path.join(HOME, 'run_daily.sh')],
                                   cwd=HOME, stdout=f, stderr=subprocess.STDOUT)
            ok = r.returncode == 0 and 'PIPELINE_OK' in ''.join(tail_log(10))
            st = 'done' if ok else 'error'
            err = None if ok else f'run_daily.sh terminó con código {r.returncode}'
            json.dump({'state': st, 'started': t0, 'ended': time.time(), 'error': err}, open(STATUS, 'w'))
        except Exception as e:
            json.dump({'state': 'error', 'started': t0, 'ended': time.time(), 'error': str(e)},
                      open(STATUS, 'w'))


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get('PORT', 8310))
    print(f'sirviendo {DOCROOT} + API en :{port}')
    ThreadingHTTPServer(('0.0.0.0', port), H).serve_forever()
