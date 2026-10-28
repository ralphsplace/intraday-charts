"""Ralph's three-chart window (the screenshot of 2026-10-26), used by the tests as a "must not break" layout.
SPY stands in for RSP: the tests only have synthetic QQQ and SPY bars."""

TREND = [  # left and right charts
    {"type": "vwap", "params": {}},
    {"type": "sma", "params": {"length": 200}},
    {"type": "sma", "params": {"length": 50}},
    {"type": "ma_cloud", "params": {}},
    {"type": "bollinger", "params": {}},
    {"type": "vzo", "params": {}},
]
LEVELS = [  # middle chart: current price line over levels
    {"type": "saty_atr", "params": {}},
    {"type": "volume_profile", "params": {"row_mode": "Tick size", "ticks": 1}},
    {"type": "session_levels", "params": {}},
]


def configs():
    def chart(symbol, tf, price, studies):
        return {"symbol": symbol, "tf": tf, "days": 1, "price": {"type": price, "params": {}},
                "studies": [{"uid": f"{symbol}{tf}-{i}", "visible": True, **s} for i, s in enumerate(studies)]}
    return [chart("QQQ", 3, "candles", TREND + [{"type": "events", "params": {}}]),
            chart("QQQ", 1, "current", LEVELS),
            chart("SPY", 3, "candles", TREND)]
