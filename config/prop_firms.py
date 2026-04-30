"""
Universal Prop Firm Configuration
==================================
Change ACTIVE_FIRM to switch the entire bot's constraint system.
All reward shaping, position sizing, and risk management pulls from here.

Supported firms:
  ftmo_swing      - FTMO Swing account (current focus)
  ftmo_normal     - FTMO Normal account
  funded_trader   - The Funded Trader
  apex_futures    - Apex Trader Funding (futures)
  myfundedfx      - MyFundedFX
  topstep         - TopStep (futures)
  e8_funding      - E8 Funding
"""

# ── Active firm — change this one line to switch everything ──────────────────
ACTIVE_FIRM = "ftmo_swing"

# ── Firm definitions ─────────────────────────────────────────────────────────
PROP_FIRMS = {

    # ── FTMO ─────────────────────────────────────────────────────────────────
    "ftmo_swing": {
        "name":                 "FTMO Swing",
        "account_size":         70_000,        # £ — update to match your account
        "profit_target_pct":    0.10,          # 10% = £7,000
        "max_daily_loss_pct":   0.05,          # 5%  = £3,500
        "max_total_loss_pct":   0.10,          # 10% = £7,000
        "min_trading_days":     10,
        "max_leverage":         30,
        "weekend_holding":      True,
        "news_trading":         True,
        "ea_allowed":           True,
        "instruments":          ["XAUUSD", "EURUSD", "GBPUSD", "EURGBP", "US30", "NAS100"],
        # Conservative personal limits — buffer below FTMO hard limits
        "personal_daily_limit": 0.030,         # 3% personal vs 5% FTMO
        "personal_total_limit": 0.070,         # 7% personal vs 10% FTMO
        # Optimal pacing to hit target in minimum days
        "daily_target_pct":     0.010,         # 1% per day = done in 10 days
        "risk_per_trade_pct":   0.005,         # 0.5% per trade
        "max_trades_per_day":   3,
        # News event behaviour
        "close_before_news_min": 30,           # Close positions 30min before high-impact news
        "no_new_trades_news_min": 60,          # No new trades 60min before high-impact news
        # Phase 2 (funded account) — more conservative
        "funded_daily_target_pct":  0.05,
        "funded_risk_per_trade_pct": 0.01,
    },

    "ftmo_normal": {
        "name":                 "FTMO Normal",
        "account_size":         70_000,
        "profit_target_pct":    0.10,
        "max_daily_loss_pct":   0.05,
        "max_total_loss_pct":   0.10,
        "min_trading_days":     4,
        "max_leverage":         100,
        "weekend_holding":      False,
        "news_trading":         False,
        "ea_allowed":           True,
        "instruments":          ["EURUSD", "GBPUSD", "XAUUSD", "EURGBP"],
        "personal_daily_limit": 0.025,
        "personal_total_limit": 0.065,
        "daily_target_pct":     0.025,         # Faster — hit in 4 days
        "risk_per_trade_pct":   0.010,
        "max_trades_per_day":   5,
        "close_before_news_min": 60,
        "no_new_trades_news_min": 120,
        "funded_daily_target_pct":  0.05,
        "funded_risk_per_trade_pct": 0.005,
    },

    # ── The Funded Trader ─────────────────────────────────────────────────────
    "funded_trader": {
        "name":                 "The Funded Trader",
        "account_size":         100_000,
        "profit_target_pct":    0.08,          # 8%
        "max_daily_loss_pct":   0.05,
        "max_total_loss_pct":   0.10,
        "min_trading_days":     5,
        "max_leverage":         200,
        "weekend_holding":      False,
        "news_trading":         True,
        "ea_allowed":           True,
        "instruments":          ["EURUSD", "XAUUSD", "GBPUSD", "NAS100"],
        "personal_daily_limit": 0.030,
        "personal_total_limit": 0.070,
        "daily_target_pct":     0.016,
        "risk_per_trade_pct":   0.007,
        "max_trades_per_day":   4,
        "close_before_news_min": 30,
        "no_new_trades_news_min": 60,
        "funded_daily_target_pct":  0.04,
        "funded_risk_per_trade_pct": 0.007,
    },

    # ── Apex Trader Funding (Futures) ─────────────────────────────────────────
    "apex_futures": {
        "name":                 "Apex Trader Funding",
        "account_size":         50_000,
        "profit_target_pct":    0.06,          # $3,000 static on $50k
        "max_daily_loss_pct":   0.026,         # $1,300 static
        "max_total_loss_pct":   0.060,         # $3,000 trailing
        "min_trading_days":     7,
        "max_leverage":         50,
        "weekend_holding":      False,
        "news_trading":         False,
        "ea_allowed":           True,
        "instruments":          ["MNQ", "MES", "MGC"],
        "personal_daily_limit": 0.015,
        "personal_total_limit": 0.040,
        "daily_target_pct":     0.009,
        "risk_per_trade_pct":   0.004,
        "max_trades_per_day":   3,
        "close_before_news_min": 60,
        "no_new_trades_news_min": 120,
        "funded_daily_target_pct":  0.03,
        "funded_risk_per_trade_pct": 0.003,
    },

    # ── MyFundedFX ────────────────────────────────────────────────────────────
    "myfundedfx": {
        "name":                 "MyFundedFX",
        "account_size":         100_000,
        "profit_target_pct":    0.08,
        "max_daily_loss_pct":   0.05,
        "max_total_loss_pct":   0.10,
        "min_trading_days":     5,
        "max_leverage":         100,
        "weekend_holding":      False,
        "news_trading":         True,
        "ea_allowed":           True,
        "instruments":          ["EURUSD", "XAUUSD", "GBPUSD"],
        "personal_daily_limit": 0.025,
        "personal_total_limit": 0.065,
        "daily_target_pct":     0.016,
        "risk_per_trade_pct":   0.007,
        "max_trades_per_day":   4,
        "close_before_news_min": 30,
        "no_new_trades_news_min": 60,
        "funded_daily_target_pct":  0.04,
        "funded_risk_per_trade_pct": 0.005,
    },

    # ── TopStep (Futures) ─────────────────────────────────────────────────────
    "topstep": {
        "name":                 "TopStep",
        "account_size":         50_000,
        "profit_target_pct":    0.06,
        "max_daily_loss_pct":   0.020,         # $1,000 static on $50k
        "max_total_loss_pct":   0.060,
        "min_trading_days":     5,
        "max_leverage":         50,
        "weekend_holding":      False,
        "news_trading":         False,
        "ea_allowed":           True,
        "instruments":          ["MNQ", "MES"],
        "personal_daily_limit": 0.012,
        "personal_total_limit": 0.040,
        "daily_target_pct":     0.012,
        "risk_per_trade_pct":   0.004,
        "max_trades_per_day":   3,
        "close_before_news_min": 60,
        "no_new_trades_news_min": 120,
        "funded_daily_target_pct":  0.03,
        "funded_risk_per_trade_pct": 0.003,
    },

    # ── E8 Funding ────────────────────────────────────────────────────────────
    "e8_funding": {
        "name":                 "E8 Funding",
        "account_size":         100_000,
        "profit_target_pct":    0.08,
        "max_daily_loss_pct":   0.05,
        "max_total_loss_pct":   0.08,
        "min_trading_days":     3,
        "max_leverage":         100,
        "weekend_holding":      False,
        "news_trading":         True,
        "ea_allowed":           True,
        "instruments":          ["EURUSD", "XAUUSD", "GBPUSD", "NAS100"],
        "personal_daily_limit": 0.030,
        "personal_total_limit": 0.055,
        "daily_target_pct":     0.027,
        "risk_per_trade_pct":   0.010,
        "max_trades_per_day":   5,
        "close_before_news_min": 30,
        "no_new_trades_news_min": 60,
        "funded_daily_target_pct":  0.04,
        "funded_risk_per_trade_pct": 0.007,
    },
}


def get_config(firm: str = None) -> dict:
    """Return the active prop firm config. Raises KeyError if firm not found."""
    firm = firm or ACTIVE_FIRM
    if firm not in PROP_FIRMS:
        raise KeyError(f"Unknown prop firm: {firm}. Available: {list(PROP_FIRMS.keys())}")
    cfg = PROP_FIRMS[firm].copy()
    # Derived absolute values for convenience
    cfg["profit_target_abs"]    = cfg["account_size"] * cfg["profit_target_pct"]
    cfg["max_daily_loss_abs"]   = cfg["account_size"] * cfg["max_daily_loss_pct"]
    cfg["max_total_loss_abs"]   = cfg["account_size"] * cfg["max_total_loss_pct"]
    cfg["personal_daily_abs"]   = cfg["account_size"] * cfg["personal_daily_limit"]
    cfg["personal_total_abs"]   = cfg["account_size"] * cfg["personal_total_limit"]
    cfg["risk_per_trade_abs"]   = cfg["account_size"] * cfg["risk_per_trade_pct"]
    return cfg


if __name__ == "__main__":
    import json
    cfg = get_config()
    print(f"Active firm: {cfg['name']}")
    print(f"  Account size:        £{cfg['account_size']:,}")
    print(f"  Profit target:       £{cfg['profit_target_abs']:,.0f} ({cfg['profit_target_pct']:.0%})")
    print(f"  Max daily loss:      £{cfg['max_daily_loss_abs']:,.0f} ({cfg['max_daily_loss_pct']:.0%})")
    print(f"  Max total loss:      £{cfg['max_total_loss_abs']:,.0f} ({cfg['max_total_loss_pct']:.0%})")
    print(f"  Personal daily cap:  £{cfg['personal_daily_abs']:,.0f} ({cfg['personal_daily_limit']:.0%})")
    print(f"  Risk per trade:      £{cfg['risk_per_trade_abs']:,.0f} ({cfg['risk_per_trade_pct']:.1%})")
    print(f"  Daily target:        {cfg['daily_target_pct']:.1%}")
    print(f"  Min trading days:    {cfg['min_trading_days']}")
    print(f"  Weekend holding:     {cfg['weekend_holding']}")
    print(f"  News trading:        {cfg['news_trading']}")
