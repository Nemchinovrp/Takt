"""Educational SMA crossover signals on completed closes; no order execution."""
from collections import deque
from decimal import Decimal


def validate_periods(fast, slow):
    if type(fast) is not int or type(slow) is not int or not 2 <= fast < slow <= 200:
        raise ValueError('Периоды должны быть целыми: 2 ≤ быстрая < медленная ≤ 200')


class MovingAverageCross:
    """Replayable signal strategy. Equality retains the preceding strict side."""
    def __init__(self, fast=10, slow=30):
        validate_periods(fast, slow)
        self.fast, self.slow = fast, slow
        self.closes = deque(maxlen=slow)
        self.previous_side = 0
        self.previous_time = None

    def on_close(self, when, price):
        if self.previous_time is not None and when <= self.previous_time:
            raise ValueError('Свечи должны идти по времени без повторов')
        value = Decimal(str(price))
        if not value.is_finite() or value <= 0:
            raise ValueError('Цена закрытия должна быть положительной и конечной')
        self.previous_time = when
        self.closes.append(value)
        values = list(self.closes)
        fast = sum(values[-self.fast:]) / self.fast if len(values) >= self.fast else None
        slow = sum(values) / self.slow if len(values) >= self.slow else None
        signal = None
        if slow is not None:
            side = (fast > slow) - (fast < slow)
            if side and self.previous_side and side != self.previous_side:
                signal = 'buy' if side > 0 else 'sell'
            if side:
                self.previous_side = side
        return dict(time=when, close=value, fast=fast, slow=slow, signal=signal)


def analyze_crossovers(points, fast=10, slow=30):
    strategy = MovingAverageCross(fast, slow)
    series = [strategy.on_close(when, close) for when, close in points]
    events = [dict(index=i, time=row['time'], price=row['close'], signal=row['signal'])
              for i, row in enumerate(series) if row['signal']]
    last = series[-1] if series else None
    ready = len(series) >= slow + 1
    return dict(fast_period=fast, slow_period=slow, bars=len(series), required=slow+1,
                ready=ready, latest=last, signal=(last['signal'] or 'hold') if ready else 'warming_up',
                series=series, events=events, execution='signals_only')
