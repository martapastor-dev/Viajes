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
_lock = threading.Lock()


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
