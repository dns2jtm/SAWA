"""
Instrument Configuration
=========================
Single source of truth for the traded instrument.

Current focus: XAUUSD (Gold)
Rationale:
  - $150-500 daily range vs 40-80 pips for EURGBP
  - 5-8x more daily movement under identical FTMO leverage
  - Consistent trend structure — RL agent has genuine signal to learn
  - Multiple macro drivers (DXY, real yields, risk-off, CB demand)
  - Passes FTMO 10% target in 10-15 days vs 30-45 days on EURGBP

To switch instrument: change ACTIVE_INSTRUMENT below.
All downstream modules import from here — one change propagates everywhere.
"""

ACTIVE_INSTRUMENT = "XAUUSD"

INSTRUMENTS = {

    "XAUUSD": {
        "symbol":           "XAUUSD",
        "display_name":     "Gold / US Dollar",
        "oanda_symbol":     "XAU_USD",
        "mt5_symbol":       "XAUUSD",
        "dukascopy_symbol": "XAUUSD",

        # Pricing
        "pip_size":         0.01,       # 1 pip = $0.01
        "pip_value_per_lot":1.0,        # $1 per pip per 0.01 lot
        "contract_size":    100,        # 100 troy oz per standard lot
        "min_lot":          0.01,
        "max_lot":          5.0,        # Conservative cap for prop accounts
        "lot_step":         0.01,
        "spread_typical":   0.30,       # $0.30 typical spread
        "commission_rt":    0.00,       # FTMO: no separate commission on spot gold

        # Volatility profile (2024-2026 averages)
        "avg_daily_range_usd":  180.0,  # $180 typical daily range
        "avg_atr_h1":           25.0,   # $25 typical H1 ATR
        "avg_atr_h4":           60.0,   # $60 typical H4 ATR

        # Session behaviour — Gold specific
        "best_sessions":    ["london", "new_york", "overlap"],
        "avoid_sessions":   ["asian_late"],   # Low volume 22:00-01:00 UTC
        "london_open_range": (7, 9),    # UTC — high breakout probability
        "ny_open_range":    (13, 15),   # UTC — highest volume

        # Key news drivers (calendar filter watches these)
        "primary_currencies": ["USD", "XAU"],
        "key_events": [
            "fomc", "fed", "powell", "non-farm", "nfp", "cpi",
            "ppi", "gdp", "ism", "jolts", "adp", "retail sales",
            "geopolitical", "central bank", "gold reserves",
        ],

        # ATR-based position sizing parameters
        "atr_stop_multiplier":  1.5,    # Stop = 1.5 × H1 ATR
        "atr_target_multiplier":2.5,    # Target = 2.5 × H1 ATR (1:1.67 RR)
        "max_stop_usd":         150.0,  # Hard cap on stop distance ($150 = 1,500 pips)
        "min_stop_usd":         10.0,   # Minimum stop ($10 = 100 pips)

        # Data sources
        "dukascopy_instrument": "XAUUSD",
        "lseg_ric":             "XAU=",
        "oanda_granularities":  ["H1", "H4", "D"],
    },

    # ── Keep EURGBP as reference (not traded) ────────────────────────────────
    "EURGBP": {
        "symbol":           "EURGBP",
        "display_name":     "Euro / British Pound",
        "oanda_symbol":     "EUR_GBP",
        "mt5_symbol":       "EURGBP",
        "dukascopy_symbol": "EURGBP",
        "pip_size":         0.0001,
        "pip_value_per_lot":6.5,        # ~£6.50 per pip per lot (GBP account)
        "contract_size":    100_000,
        "min_lot":          0.01,
        "max_lot":          5.0,
        "lot_step":         0.01,
        "spread_typical":   0.8,
        "commission_rt":    0.00,
        "avg_daily_range_usd":  55.0,
        "avg_atr_h1":           8.0,
        "avg_atr_h4":           22.0,
        "best_sessions":    ["london", "overlap"],
        "primary_currencies": ["EUR", "GBP"],
        "atr_stop_multiplier":  1.5,
        "atr_target_multiplier":2.5,
        "max_stop_usd":         30.0,
        "min_stop_usd":         5.0,
        "dukascopy_instrument": "EURGBP",
        "lseg_ric":             "EURGBP=",
        "oanda_granularities":  ["H1", "H4", "D"],
    },
}


def get_instrument(symbol: str = None) -> dict:
    symbol = symbol or ACTIVE_INSTRUMENT
    if symbol not in INSTRUMENTS:
        raise KeyError(f"Unknown instrument: {symbol}. Available: {list(INSTRUMENTS.keys())}")
    return INSTRUMENTS[symbol].copy()


if __name__ == "__main__":
    inst = get_instrument()
    print(f"Active instrument : {inst['display_name']} ({inst['symbol']})")
    print(f"OANDA symbol      : {inst['oanda_symbol']}")
    print(f"MT5 symbol        : {inst['mt5_symbol']}")
    print(f"Pip size          : {inst['pip_size']}")
    print(f"Pip value/lot     : ${inst['pip_value_per_lot']}")
    print(f"Typical spread    : ${inst['spread_typical']}")
    print(f"Avg daily range   : ${inst['avg_daily_range_usd']}")
    print(f"ATR stop mult     : {inst['atr_stop_multiplier']}x")
    print(f"Best sessions     : {inst['best_sessions']}")
    print(f"Key news events   : {inst['key_events'][:5]} ...")
