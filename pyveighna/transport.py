"""Verified, broker-scoped TLS transport for the archived Invest SDK."""
from contextlib import contextmanager
from pathlib import Path

import grpc
from tinkoff.invest.constants import MAX_RECEIVE_MESSAGE_LENGTH
from tinkoff.invest.services import Services

from .rpc import DeadlineInterceptor

ROOT_CA = Path(__file__).with_name("certs") / "russian_trusted_root_ca.pem"
TARGETS = {
    "readonly": "invest-public-api.tbank.ru:443",
    "sandbox": "sandbox-invest-public-api.tbank.ru:443",
}


@contextmanager
def broker_client(config, cancelled=None):
    # Explicit credentials apply only to this broker channel. Hostname and chain
    # verification remain enabled; no global trust or SDK monkeypatch is needed.
    credentials = grpc.ssl_channel_credentials(root_certificates=ROOT_CA.read_bytes())
    with grpc.secure_channel(
        TARGETS[config.mode], credentials,
        options=[("grpc.max_receive_message_length", MAX_RECEIVE_MESSAGE_LENGTH)],
    ) as channel:
        intercepted = grpc.intercept_channel(channel, DeadlineInterceptor(cancelled))
        yield Services(intercepted, token=config.token)
