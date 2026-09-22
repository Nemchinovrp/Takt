"""Loopback-only web dashboard; credentials never leave the Python process."""
import json
from collections import deque
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, RLock, Thread
from urllib.parse import parse_qs, urlsplit

from .engine import InvestmentEngine, EVENT_SNAPSHOT, EVENT_STATUS, EVENT_LOG, EVENT_HISTORY
from vnpy.trader.event import EVENT_TICK
from .strategy import analyze_crossovers, validate_periods

STATIC = Path(__file__).with_name('web')


def encode(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


class Dashboard:
    def __init__(self, config):
        self.config = config
        self.lock = RLock()
        self.snapshot = None
        self.status = 'loading'
        self.logs = deque(maxlen=300)
        self.histories = {}
        self.ticks = 0
        self.stop = Event()
        self.engine = InvestmentEngine(config, self.receive)
        self.worker = Thread(target=self.poll, daemon=True)
        self.worker.start()

    def receive(self, event):
        with self.lock:
            if event.type == EVENT_SNAPSHOT:
                self.snapshot = asdict(event.data)
            elif event.type == EVENT_STATUS:
                self.status = event.data
            elif event.type == EVENT_LOG:
                when, level, message = event.data
                self.logs.append(dict(time=when, level=level, message=message))
            elif event.type == EVENT_HISTORY:
                figi, points, error = event.data
                self.histories[figi] = dict(points=points, error=error, pending=False)
            elif event.type == EVENT_TICK:
                self.ticks += 1

    def poll(self):
        while not self.stop.is_set():
            self.engine.refresh()
            self.stop.wait(self.config.poll_seconds)

    def state(self):
        with self.lock:
            return dict(mode=self.config.mode, status=self.status, snapshot=self.snapshot,
                        logs=list(self.logs), ticks=self.ticks, poll_seconds=self.config.poll_seconds)

    def history(self, figi, refresh=False):
        with self.lock:
            allowed = set(self.config.figis)
            if self.snapshot:
                allowed.update(p['instrument']['figi'] for p in self.snapshot['positions'])
            if figi not in allowed:
                raise ValueError('Неизвестный инструмент')
            current = self.histories.get(figi)
            if current is None or (refresh and not current.get('pending')):
                if self.engine.history(figi):
                    self.histories[figi] = dict(points=(current or {}).get('points', []), error=None, pending=True)
            return self.histories.get(figi, dict(points=[], error=None, pending=True))

    def close(self):
        self.stop.set()
        self.worker.join(timeout=2)
        self.engine.close()


def make_server(dashboard, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, body, content_type='application/json; charset=utf-8', status=200):
            if not isinstance(body, bytes):
                body = json.dumps(body, default=encode, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            host = self.headers.get('Host', '')
            if host not in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}:
                return self.reply({'error': 'Invalid host'}, status=403)
            path = urlsplit(self.path)
            if path.path == '/api/state':
                return self.reply(dashboard.state())
            if path.path == '/api/history':
                query = parse_qs(path.query)
                try:
                    fast = int(query.get('fast', ['10'])[0])
                    slow = int(query.get('slow', ['30'])[0])
                    validate_periods(fast, slow)
                    result = dict(dashboard.history(query.get('figi', [''])[0], query.get('refresh') == ['1']))
                    result['strategy'] = None
                    if not result.get('pending') and not result.get('error'):
                        result['strategy'] = analyze_crossovers(result['points'], fast, slow)
                    return self.reply(result)
                except ValueError as error:
                    return self.reply({'error': str(error)}, status=400)
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path.path in files:
                name, mime = files[path.path]
                return self.reply((STATIC / name).read_bytes(), mime)
            self.reply({'error': 'Not found'}, status=404)

        def do_POST(self):
            expected = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
            if self.headers.get('Origin') not in expected or self.headers.get('X-PyVeighNa') != '1':
                return self.reply({'error': 'Forbidden'}, status=403)
            if self.path == '/api/refresh':
                dashboard.engine.refresh()
                return self.reply({'ok': True})
            self.reply({'error': 'Not found'}, status=404)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def run(config, port=3729):
    dashboard = Dashboard(config)
    try:
        server = make_server(dashboard, port)
    except Exception:
        dashboard.close()
        raise
    print(f'PyVeighNa: http://127.0.0.1:{port} • {config.mode}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        dashboard.close()
