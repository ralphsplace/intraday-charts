"""Chart studies. The interface is in base.py; each other module is one family of studies:

    overlays     moving averages, VWAP, bands, channels, Parabolic SAR, moving average cloud
    volume       volume and volume profile
    oscillators  RSI, MACD, Stochastic, ATR, ADX, CCI, Williams %R, OBV, VZO
    levels       prior day, support/resistance, session levels, ATR levels, events
    internals    NYSE TICK and cumulative TICK

Importing the package registers every study. To add one, see README, "Adding your own study".
"""
from .. import engine as en  # noqa: F401  (studies.en, used by the tests)
from .. import indicators as ind  # noqa: F401
from . import internals, levels, oscillators, overlays, volume  # noqa: F401  (registers the studies)
from .base import REGISTRY, catalog, coerce, run_study  # noqa: F401
from .levels import atr_ladder  # noqa: F401
from .volume import VP_MAX_ROWS  # noqa: F401

# the studies a new chart starts with: none (config.json "default_layout" can set others)
DEFAULT_LAYOUT: list[dict] = []
