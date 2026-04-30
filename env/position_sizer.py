"""
ATR-Based Position Sizer — XAUUSD Optimised
=============================================
Replaces fixed lot sizing with volatility-adjusted sizing.

Core logic:
    stop_distance = ATR * atr_stop_multiplier
    lot_size      = risk_per_trade_£ / (stop_distance * pip_value_per_lot)

This means:
  - Calm market  → ATR small → stop tight → lot LARGER → captures more
  - Volatile day → ATR large → stop wider → lot SMALLER → account protected
  - Risk per trade stays CONSTANT regardless of market conditions

For XAUUSD specifically:
  - ATR in USD (e.g. $25 on H1)
  - pip_value = $1 per pip per 0.01 lot on Gold
  - stop_pips = stop_usd / pip_size = stop_usd / 0.01
  - lot = risk_usd / (stop_pips * pip_value_per_lot)

Usage:
    from env.position_sizer import PositionSizer
    sizer = PositionSizer(firm="ftmo_swing", instrument="XAUUSD")
    lot   = sizer.calculate(atr_h1=25.0, account_equity=70000)
    sl    = sizer.stop_distance(atr_h1=25.0)   # in USD
    tp    = sizer.target_distance(atr_h1=25.0) # in USD
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.prop_firms  import get_config,     ACTIVE_FIRM
from config.instruments import get_instrument, ACTIVE_INSTRUMENT


class PositionSizer:
    """
    Volatility-adjusted position sizer.
    Keeps £ risk per trade constant; lot size adapts to ATR.
    """

    def __init__(self, firm: str = None, instrument: str = None):
        self.cfg  = get_config(firm or ACTIVE_FIRM)
        self.inst = get_instrument(instrument or ACTIVE_INSTRUMENT)

        self.risk_pct         = self.cfg["risk_per_trade_pct"]      # e.g. 0.005
        self.atr_stop_mult    = self.inst["atr_stop_multiplier"]    # e.g. 1.5
        self.atr_target_mult  = self.inst["atr_target_multiplier"]  # e.g. 2.5
        self.max_stop_usd     = self.inst["max_stop_usd"]           # e.g. $150
        self.min_stop_usd     = self.inst["min_stop_usd"]           # e.g. $10
        self.pip_size         = self.inst["pip_size"]               # e.g. 0.01
        self.pip_value        = self.inst["pip_value_per_lot"]      # e.g. 1.0 $/pip/0.01lot
        self.min_lot          = self.inst["min_lot"]                # e.g. 0.01
        self.max_lot          = self.inst["max_lot"]                # e.g. 5.0
        self.lot_step         = self.inst["lot_step"]               # e.g. 0.01

    def _risk_amount(self, equity: float) -> float:
        """£ / $ risk for this trade."""
        return equity * self.risk_pct

    def stop_distance(self, atr_h1: float) -> float:
        """
        Stop loss distance in USD (price units for Gold).
        Clamped between min_stop and max_stop.
        """
        stop = atr_h1 * self.atr_stop_mult
        return max(self.min_stop_usd, min(stop, self.max_stop_usd))

    def target_distance(self, atr_h1: float) -> float:
        """Take profit distance in USD."""
        return atr_h1 * self.atr_target_mult

    def risk_reward(self, atr_h1: float) -> float:
        """Risk:Reward ratio for current ATR."""
        stop   = self.stop_distance(atr_h1)
        target = self.target_distance(atr_h1)
        return round(target / stop, 2) if stop > 0 else 0.0

    def calculate(self, atr_h1: float, account_equity: float) -> float:
        """
        Calculate lot size for a trade.

        Parameters
        ----------
        atr_h1 : float
            Current H1 ATR value in price units (USD for Gold).
        account_equity : float
            Current account equity in base currency.

        Returns
        -------
        float
            Lot size rounded to lot_step, clamped to [min_lot, max_lot].
        """
        risk_usd  = self._risk_amount(account_equity)
        stop_usd  = self.stop_distance(atr_h1)
        stop_pips = stop_usd / self.pip_size        # e.g. $25 / 0.01 = 2500 pips

        # lot = risk$ / (stop_pips * pip_value_per_lot)
        # For XAUUSD: pip_value = $1/pip/0.01lot → so 1 pip on 1.0 lot = $100
        # Adjust: pip_value_per_lot already in units of 0.01 lot
        raw_lot = risk_usd / (stop_pips * self.pip_value)

        # Round to lot step
        lot = round(round(raw_lot / self.lot_step) * self.lot_step, 2)

        # Clamp
        lot = max(self.min_lot, min(lot, self.max_lot))

        # Hard safety: never risk more than 2× intended (volatility spike guard)
        max_allowed_risk = risk_usd * 2.0
        actual_risk      = stop_pips * self.pip_value * lot
        if actual_risk > max_allowed_risk:
            lot = round(max_allowed_risk / (stop_pips * self.pip_value + 1e-9), 2)
            lot = max(self.min_lot, round(round(lot / self.lot_step) * self.lot_step, 2))

        return lot

    def sl_price(self, entry: float, direction: int, atr_h1: float) -> float:
        """
        Calculate stop loss price.
        direction: +1 = long, -1 = short
        """
        dist = self.stop_distance(atr_h1)
        return entry - direction * dist

    def tp_price(self, entry: float, direction: int, atr_h1: float) -> float:
        """Calculate take profit price."""
        dist = self.target_distance(atr_h1)
        return entry + direction * dist

    def summary(self, atr_h1: float, equity: float, entry: float = 3000.0,
                direction: int = 1) -> dict:
        """Full trade plan summary for a given ATR and equity."""
        lot  = self.calculate(atr_h1, equity)
        stop = self.stop_distance(atr_h1)
        tgt  = self.target_distance(atr_h1)
        sl   = self.sl_price(entry, direction, atr_h1)
        tp   = self.tp_price(entry, direction, atr_h1)

        stop_pips    = stop / self.pip_size
        risk_usd     = stop_pips * self.pip_value * lot
        reward_usd   = (tgt  / self.pip_size) * self.pip_value * lot

        return {
            "instrument":    self.inst["symbol"],
            "firm":          self.cfg["name"],
            "equity":        equity,
            "atr_h1":        atr_h1,
            "lot_size":      lot,
            "stop_usd":      round(stop, 2),
            "target_usd":    round(tgt,  2),
            "sl_price":      round(sl,   2),
            "tp_price":      round(tp,   2),
            "stop_pips":     round(stop_pips),
            "risk_usd":      round(risk_usd,   2),
            "reward_usd":    round(reward_usd, 2),
            "risk_pct":      round(risk_usd / equity * 100, 3),
            "rr_ratio":      self.risk_reward(atr_h1),
        }

    def __repr__(self):
        return (f"PositionSizer(firm={self.cfg['name']}, "
                f"instrument={self.inst['symbol']}, "
                f"risk={self.risk_pct:.1%})")


# ── Drawdown-aware scaling ────────────────────────────────────────────────────

class AdaptiveSizer(PositionSizer):
    """
    Extends PositionSizer with drawdown-aware scaling.
    Reduces lot size as drawdown increases — protects the account
    automatically as losses accumulate.

    Scale table:
      0-20% of personal daily limit used  → 100% risk
      20-40%                              → 80%  risk
      40-60%                              → 60%  risk
      60-80%                              → 40%  risk
      80-100%                             → 25%  risk (survival mode)
    """

    DRAWDOWN_SCALE = [
        (0.20, 1.00),
        (0.40, 0.80),
        (0.60, 0.60),
        (0.80, 0.40),
        (1.00, 0.25),
    ]

    def calculate(self, atr_h1: float, account_equity: float,
                  daily_dd_used: float = 0.0) -> float:
        base_lot     = super().calculate(atr_h1, account_equity)
        daily_limit  = account_equity * self.cfg["personal_daily_limit"]
        dd_ratio     = daily_dd_used / (daily_limit + 1e-9)

        scale = 1.00
        for threshold, factor in self.DRAWDOWN_SCALE:
            if dd_ratio <= threshold:
                scale = factor
                break

        scaled_lot = base_lot * scale
        scaled_lot = round(round(scaled_lot / self.lot_step) * self.lot_step, 2)
        return max(self.min_lot, scaled_lot)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--atr",    type=float, default=25.0,    help="H1 ATR in USD")
    parser.add_argument("--equity", type=float, default=70000.0, help="Account equity")
    parser.add_argument("--entry",  type=float, default=3300.0,  help="Entry price")
    parser.add_argument("--long",   action="store_true",         help="Long trade (default)")
    parser.add_argument("--adaptive", action="store_true",       help="Use AdaptiveSizer")
    parser.add_argument("--daily-dd", type=float, default=0.0,   help="Daily DD used ($)")
    args = parser.parse_args()

    direction = 1 if args.long or True else -1

    if args.adaptive:
        sizer = AdaptiveSizer()
        lot   = sizer.calculate(args.atr, args.equity, args.daily_dd)
        print(f"AdaptiveSizer | DD used: ${args.daily_dd:.0f} | Lot: {lot}")
    else:
        sizer = PositionSizer()

    s = sizer.summary(args.atr, args.equity, args.entry, direction)

    print(f"\n{'='*55}")
    print(f"  {s['instrument']} Trade Plan — {s['firm']}")
    print(f"{'='*55}")
    print(f"  Equity          : ${s['equity']:>12,.2f}")
    print(f"  ATR (H1)        : ${s['atr_h1']:>12.2f}")
    print(f"  Lot size        :  {s['lot_size']:>11.2f}")
    print(f"  Stop distance   : ${s['stop_usd']:>12.2f}  ({s['stop_pips']:,.0f} pips)")
    print(f"  Target distance : ${s['target_usd']:>12.2f}")
    print(f"  SL price        : ${s['sl_price']:>12.2f}")
    print(f"  TP price        : ${s['tp_price']:>12.2f}")
    print(f"  Risk            : ${s['risk_usd']:>12.2f}  ({s['risk_pct']:.3f}%)")
    print(f"  Reward          : ${s['reward_usd']:>12.2f}")
    print(f"  R:R ratio       :  {s['rr_ratio']:>11.2f}")
    print(f"{'='*55}")

    print(f"\nDrawdown scaling demonstration (AdaptiveSizer):")
    adaptive = AdaptiveSizer()
    equity   = args.equity
    daily_lim = equity * adaptive.cfg["personal_daily_limit"]
    print(f"  Daily limit: ${daily_lim:,.0f}")
    for dd_pct in [0, 0.15, 0.30, 0.50, 0.70, 0.90]:
        dd_usd = daily_lim * dd_pct
        lot    = adaptive.calculate(args.atr, equity, dd_usd)
        print(f"  DD used {dd_pct:.0%} (${dd_usd:,.0f}) → lot {lot:.2f}")
