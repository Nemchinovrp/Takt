from datetime import datetime, timedelta, timezone

import pytest

from pyveighna.strategy import analyze_crossovers


def points(prices):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [(start + timedelta(minutes=5*i), price) for i, price in enumerate(prices)]


def test_crossovers_and_no_duplicate_signals():
    result = analyze_crossovers(points([5, 4, 3, 2, 3, 4, 5, 4, 3, 2]), 2, 3)
    assert [(e['index'], e['signal']) for e in result['events']] == [(5, 'buy'), (8, 'sell')]
    assert result['signal'] == 'hold'
    assert result['execution'] == 'signals_only'


def test_no_lookahead():
    prices = [5, 4, 3, 2, 3, 4, 5, 4, 3, 2]
    full = analyze_crossovers(points(prices), 2, 3)
    for length in range(1, len(prices)+1):
        partial = analyze_crossovers(points(prices[:length]), 2, 3)
        assert partial['series'] == full['series'][:length]
        assert partial['events'] == [e for e in full['events'] if e['index'] < length]


def test_warmup_flat_and_equality():
    assert analyze_crossovers([], 2, 3)['signal'] == 'warming_up'
    assert not analyze_crossovers(points([1, 2, 3]), 2, 3)['ready']
    assert analyze_crossovers(points([1, 2, 3, 4]), 2, 3)['events'] == []
    assert analyze_crossovers(points([2]*10), 2, 3)['events'] == []
    result = analyze_crossovers(points([3, 2, 1, 1, 1, 2, 3]), 2, 3)
    assert [(e['index'], e['signal']) for e in result['events']] == [(5, 'buy')]


@pytest.mark.parametrize('fast,slow', [(1, 30), (10, 10), (30, 10), (10, 201), (2.5, 30), (True, 30)])
def test_invalid_periods(fast, slow):
    with pytest.raises(ValueError):
        analyze_crossovers([], fast, slow)


def test_invalid_prices_and_duplicate_candles():
    for price in [0, -1, float('nan'), float('inf')]:
        with pytest.raises(ValueError):
            analyze_crossovers(points([price]), 2, 3)
    p = points([1])
    with pytest.raises(ValueError):
        analyze_crossovers(p+p, 2, 3)
