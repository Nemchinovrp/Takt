"""A finite deadline for every synchronous gRPC call, including SDK calls."""
from collections import namedtuple

import grpc

CallDetails = namedtuple("CallDetails", "method timeout metadata credentials wait_for_ready compression")


class DeadlineInterceptor(grpc.UnaryUnaryClientInterceptor):
    def __init__(self, cancelled=None):
        self.cancelled = cancelled

    def intercept_unary_unary(self, continuation, details, request):
        if self.cancelled is not None and self.cancelled.is_set():
            raise RuntimeError("Подключение закрыто")
        updated = CallDetails(
            details.method, min(details.timeout or 12, 12), details.metadata,
            details.credentials, getattr(details, "wait_for_ready", None),
            getattr(details, "compression", None),
        )
        return continuation(updated, request)
