import json
from datetime import datetime, timezone
from decimal import Decimal
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from pyveighna.webserver import encode, make_server


class StubDashboard:
    def __init__(self):
        self.engine = self
        self.refreshes = 0

    def state(self):
        return {'total': Decimal('123.45'), 'time': datetime(2026, 1, 1, tzinfo=timezone.utc)}

    def refresh(self):
        self.refreshes += 1

    def history(self, figi, refresh):
        if figi != 'SBER':
            raise ValueError('Неизвестный инструмент')
        return {'points': [], 'pending': True}


@pytest.fixture
def server():
    dashboard = StubDashboard()
    http = make_server(dashboard, 0)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{http.server_port}', dashboard
    http.shutdown()
    http.server_close()
    thread.join()


def test_web_assets_and_data(server):
    base, _ = server
    for path, mime in [('/', 'text/html'), ('/app.js', 'text/javascript'), ('/style.css', 'text/css')]:
        with urlopen(base + path) as response:
            assert response.headers['Content-Type'].startswith(mime)
            assert response.headers['Cache-Control'] == 'no-store'
            assert response.read()
    with urlopen(base + '/api/state') as response:
        assert json.load(response)['total'] == '123.45'
    with pytest.raises(HTTPError) as error:
        urlopen(base + '/.env')
    assert error.value.code == 404


def test_origin_and_host_protection(server):
    base, dashboard = server
    with pytest.raises(HTTPError) as error:
        urlopen(Request(base + '/api/state', headers={'Host': 'attacker.example'}))
    assert error.value.code == 403
    with pytest.raises(HTTPError) as error:
        urlopen(Request(base + '/api/refresh', method='POST', headers={'Origin':'https://attacker.example'}))
    assert error.value.code == 403
    with urlopen(Request(base + '/api/refresh', method='POST', headers={'Origin': base, 'X-PyVeighNa':'1'})) as response:
        assert json.load(response)['ok']
    assert dashboard.refreshes == 1


def test_history_validation(server):
    base, _ = server
    with pytest.raises(HTTPError) as error:
        urlopen(base + '/api/history?figi=unknown')
    assert error.value.code == 400
    with urlopen(base + '/api/history?figi=SBER') as response:
        assert json.load(response)['pending']
