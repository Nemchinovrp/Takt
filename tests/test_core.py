from datetime import datetime, timezone
from decimal import Decimal
from threading import Event as ThreadEvent
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, create_autospec

import pytest
from tinkoff.invest import AccountStatus
from tinkoff.invest.services import OperationsService

from pyveighna.config import Config
from pyveighna.engine import EVENT_SNAPSHOT, EVENT_STATUS, InvestmentEngine
from pyveighna.models import decimal_value
from pyveighna.providers import DemoProvider, TinkoffProvider
from pyveighna.rpc import CallDetails, DeadlineInterceptor
from vnpy.trader.event import EVENT_TICK
from vnpy.trader.object import TickData


def money(units=0, nano=0, currency="rub"):
    return NS(units=units, nano=nano, currency=currency)


def test_money_keeps_nano_precision_and_sign():
    assert decimal_value(money(-1, -123456789)) == Decimal("-1.123456789")
    assert decimal_value(money(999999999, 1)) == Decimal("999999999.000000001")


@pytest.mark.parametrize("kwargs", [dict(mode="live"), dict(mode="readonly"),
                                  dict(poll_seconds=1), dict(figis=())])
def test_invalid_config(kwargs):
    with pytest.raises(ValueError):
        Config(**kwargs)


def test_token_not_in_config_repr():
    assert "secret123" not in repr(Config(token="secret123"))


def test_demo_portfolio_reconciles():
    provider = DemoProvider()
    snapshot = provider.snapshot()
    assert snapshot.total == snapshot.currencies + sum(p.quantity * p.current for p in snapshot.positions)
    assert all(p.pnl == (p.current - p.average) * p.quantity for p in snapshot.positions)
    points = provider.candles(snapshot.quotes[0].instrument.figi)
    assert len(points) == 120
    assert points[0][0] < points[-1][0]
    assert not snapshot.orders


def sdk_fixture(mode="sandbox", account_id=""):
    provider = TinkoffProvider(Config(mode=mode, token="secret", account_id=account_id, figis=("FIGI",)))
    client = MagicMock()
    client.operations = create_autospec(OperationsService, instance=True)
    client.users.get_accounts.return_value.accounts = [NS(id="one", name="Счёт", status=AccountStatus.ACCOUNT_STATUS_OPEN)]
    client.operations.get_portfolio.return_value = NS(
        total_amount_portfolio=money(500), total_amount_currencies=money(100), expected_yield=money(5),
        positions=[NS(figi="FIGI", quantity=money(2), average_position_price=money(180),
                      current_price=money(200), expected_yield=money(40))],
    )
    client.instruments.get_instrument_by.return_value.instrument = NS(ticker="TEST", name="Test", currency="rub", lot=10)
    client.market_data.get_last_prices.return_value.last_prices = [NS(figi="FIGI", price=money(200), time=datetime.now(timezone.utc))]
    client.orders.get_orders.return_value.orders = []
    context = MagicMock()
    context.__enter__.return_value = client
    provider.client = MagicMock(return_value=context)
    return provider, client


@pytest.mark.parametrize("mode", ["sandbox", "readonly"])
def test_sdk_portfolio_mapping_and_read_only_calls(mode):
    provider, client = sdk_fixture(mode)
    snapshot = provider.snapshot()
    assert snapshot.total == 500
    assert snapshot.return_percent == 5
    assert snapshot.positions[0].pnl == 40
    assert snapshot.positions[0].instrument.lot == 10
    client.operations.get_portfolio.assert_called_once_with(account_id="one")
    assert not client.orders.post_order.called
    assert not client.orders.cancel_order.called
    assert not client.sandbox.open_sandbox_account.called


def test_invalid_account_is_not_silently_replaced():
    provider, client = sdk_fixture(account_id="missing")
    with pytest.raises(ValueError, match="не найден"):
        provider.snapshot()
    client.operations.get_portfolio.assert_not_called()


def test_empty_accounts():
    provider, client = sdk_fixture()
    client.users.get_accounts.return_value.accounts = []
    with pytest.raises(ValueError, match="Нет открытых счетов"):
        provider.snapshot()


def test_unavailable_instrument_keeps_position():
    provider, client = sdk_fixture()
    client.instruments.get_instrument_by.side_effect = RuntimeError("Unavailable")
    client.market_data.get_last_prices.return_value.last_prices = []
    snapshot = provider.snapshot()
    assert len(snapshot.positions) == 1
    assert snapshot.positions[0].instrument.ticker == "FIGI"
    assert snapshot.warnings


def test_candle_request_filters_incomplete():
    provider, client = sdk_fixture()
    now = datetime.now(timezone.utc)
    client.market_data.get_candles.return_value.candles = [
        NS(time=now, close=money(123, 100_000_000), is_complete=True),
        NS(time=now, close=money(124), is_complete=False),
    ]
    assert provider.candles("FIGI") == [(now, 123.1)]


@pytest.mark.parametrize("mode,target", [
    ("sandbox", "sandbox-invest-public-api.tbank.ru:443"),
    ("readonly", "invest-public-api.tbank.ru:443"),
])
def test_client_verified_tls_and_targets(monkeypatch, mode, target):
    from pyveighna import transport
    secure = MagicMock()
    credentials = MagicMock()
    services = MagicMock()
    monkeypatch.setattr(transport.grpc, "secure_channel", secure)
    monkeypatch.setattr(transport.grpc, "ssl_channel_credentials", credentials)
    monkeypatch.setattr(transport.grpc, "intercept_channel", MagicMock())
    monkeypatch.setattr(transport, "Services", services)
    provider = TinkoffProvider(Config(mode=mode, token="test"))
    with provider.client() as client:
        assert client is services.return_value
    secure.assert_called_once_with(target, credentials.return_value,
        options=[("grpc.max_receive_message_length", transport.MAX_RECEIVE_MESSAGE_LENGTH)])
    assert b"BEGIN CERTIFICATE" in credentials.call_args.kwargs["root_certificates"]
    secure.return_value.__exit__.assert_called_once()


def test_bundled_ca_is_valid_and_pinned():
    import hashlib
    import ssl
    from pyveighna.transport import ROOT_CA
    pem = ROOT_CA.read_text()
    der = ssl.PEM_cert_to_DER_cert(pem)
    assert hashlib.sha256(der).hexdigest() == "d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31"
    context = ssl.create_default_context(cadata=pem)
    assert context.check_hostname
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_deadline_and_cancellation():
    cancelled = ThreadEvent()
    interceptor = DeadlineInterceptor(cancelled)
    continuation = MagicMock()
    details = CallDetails("method", None, (), None, None, None)
    interceptor.intercept_unary_unary(continuation, details, "request")
    assert continuation.call_args.args[0].timeout == 12
    cancelled.set()
    with pytest.raises(RuntimeError, match="закрыто"):
        interceptor.intercept_unary_unary(continuation, details, "request")


def test_real_vnpy_events_and_failure_recovery():
    done = ThreadEvent()
    received = []

    def callback(event):
        received.append(event)
        if event.type == EVENT_STATUS and event.data in {"ready", "error"}:
            done.set()

    engine = InvestmentEngine(Config(token="sensitive"), callback)
    try:
        engine.refresh()
        assert done.wait(3)
        assert any(e.type == EVENT_SNAPSHOT for e in received)
        ticks = [e.data for e in received if e.type == EVENT_TICK]
        assert len(ticks) == 4 and all(isinstance(t, TickData) for t in ticks)
        assert "sensitive" not in engine.safe_error(RuntimeError("token sensitive"))
        engine.provider.snapshot = MagicMock(side_effect=RuntimeError("offline"))
        done.clear()
        engine.refresh()
        assert done.wait(3)
        assert any(e.type == EVENT_STATUS and e.data == "error" for e in received)
    finally:
        engine.close()
