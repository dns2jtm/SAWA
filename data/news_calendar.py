"""
Economic Calendar Risk Filter
==============================
Fetches high-impact economic events from ForexFactory (scrape) and
the free Investing.com calendar RSS, then enforces the prop firm's
news trading rules:

  - No new trades N minutes before high-impact events
  - Close all open positions M minutes before high-impact events
  - Block trading during events affecting the active instrument

Rules are driven by config/prop_firms.py:
  close_before_news_min     → close positions this many min before event
  no_new_trades_news_min    → block new trades this many min before event
  news_trading              → if False, block ALL news-adjacent trading

Usage (standalone):
    python data/calendar.py                     # print today's events
    python data/calendar.py --date 2026-04-28   # specific date

Usage (in bot):
    from data.news_calendar import CalendarFilter
    cal = CalendarFilter()
    status = cal.get_status("EURGBP")           # returns CalendarStatus
    if status.block_new_trades:
        print(f"No new trades: {status.reason}")
    if status.close_positions:
        print(f"Close all positions: {status.reason}")
"""

import argparse
import json
import os
import re
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import time
import requests
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import Optional

from config.prop_firms import get_config, ACTIVE_FIRM

# ── Currency → instruments mapping ───────────────────────────────────────────
# An event affects your position if its currency is in the instrument string
CURRENCY_INSTRUMENT_MAP = {
    "GBP": ["EURGBP", "GBPUSD", "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD"],
    "EUR": ["EURGBP", "EURUSD", "EURJPY", "EURCHF", "EURAUD", "EURCAD"],
    "USD": ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "XAUUSD", "NAS100", "US30"],
    "JPY": ["USDJPY", "EURJPY", "GBPJPY"],
    "CHF": ["USDCHF", "EURCHF", "GBPCHF"],
    "AUD": ["AUDUSD", "EURAUD", "GBPAUD"],
    "CAD": ["USDCAD", "EURCAD", "GBPCAD"],
    "XAU": ["XAUUSD"],
    "NZD": ["NZDUSD"],
    "IDX": ["NAS100", "US30"],   # Index events (Fed, US data)
}

# High-impact keywords — any event matching these triggers maximum caution
HIGH_IMPACT_KEYWORDS = [
    "interest rate", "rate decision", "rate statement",
    "monetary policy", "press conference", "inflation",
    "cpi", "ppi", "gdp", "nonfarm", "non-farm", "nfp",
    "unemployment", "claimant", "retail sales", "pmi",
    "flash pmi", "consumer confidence", "trade balance",
    "current account", "housing", "fomc", "boe", "ecb",
    "fed chair", "governor", "boe governor", "lagarde",
    "bailey", "powell", "budget", "autumn statement",
    "spring statement", "ism", "adp", "jolts",
]


@dataclass
class EconomicEvent:
    datetime_utc:  datetime
    currency:      str
    impact:        str        # "high", "medium", "low"
    title:         str
    actual:        Optional[str] = None
    forecast:      Optional[str] = None
    previous:      Optional[str] = None
    source:        str        = "unknown"

    def affects_instrument(self, symbol: str) -> bool:
        """Return True if this event's currency affects the given symbol."""
        symbol_upper = symbol.upper()
        affected = CURRENCY_INSTRUMENT_MAP.get(self.currency.upper(), [])
        # Also catch USD events for gold/indices
        if self.currency.upper() == "USD" and symbol_upper in ("XAUUSD", "NAS100", "US30"):
            return True
        return symbol_upper in affected

    def is_high_impact(self) -> bool:
        title_lower = self.title.lower()
        return (
            self.impact.lower() == "high"
            or any(kw in title_lower for kw in HIGH_IMPACT_KEYWORDS)
        )

    def minutes_until(self, now: datetime = None) -> float:
        now = now or datetime.now(timezone.utc)
        if self.datetime_utc.tzinfo is None:
            event_dt = self.datetime_utc.replace(tzinfo=timezone.utc)
        else:
            event_dt = self.datetime_utc
        return (event_dt - now).total_seconds() / 60


@dataclass
class CalendarStatus:
    block_new_trades:  bool          = False
    close_positions:   bool          = False
    reason:            str           = ""
    next_event:        Optional[EconomicEvent] = None
    minutes_until:     float         = 999.0
    safe_until:        Optional[datetime] = None
    all_events_today:  list          = field(default_factory=list)


# ── Data sources ────────────────────────────────────────────────

def _fetch_lseg_calendar() -> list[EconomicEvent]:
    """
    Load the most recently cached LSEG economic calendar and convert to
    EconomicEvent objects.  This is the highest-quality source: it has
    official actual/forecast/previous values and a numeric impact score.
    Returns an empty list silently if no cache file exists.
    """
    events = []
    try:
        from data.lseg import load_calendar_cache
        df = load_calendar_cache()
        if df.empty:
            return events

        now    = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=7)

        for _, row in df.iterrows():
            try:
                dt = pd.to_datetime(row["datetime_utc"], utc=True).to_pydatetime()
                if dt < now - timedelta(hours=2) or dt > cutoff:
                    continue
                events.append(EconomicEvent(
                    datetime_utc = dt,
                    currency     = str(row.get("currency", "USD")).upper(),
                    impact       = str(row.get("impact", "low")).lower(),
                    title        = str(row.get("title", "")),
                    actual       = str(row.get("actual",   "") or ""),
                    forecast     = str(row.get("forecast", "") or ""),
                    previous     = str(row.get("previous", "") or ""),
                    source       = "lseg",
                ))
            except Exception:
                continue
    except Exception:
        pass
    return events


def _fetch_forexfactory(date: datetime = None) -> list[EconomicEvent]:
    """
    Scrape ForexFactory calendar JSON (unofficial, but stable since 2018).
    Falls back to empty list on failure — never crashes the bot.
    """
    events = []
    try:
        date = date or datetime.now(timezone.utc)
        url  = f"https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        r    = requests.get(url, timeout=10,
                            headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return events

        for item in r.json():
            try:
                dt_str  = item.get("date", "")
                time_str = item.get("time", "00:00am").strip()
                try:
                    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    dt = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    if time_str.lower() in ("all day", "tentative", ""):
                        time_str = "12:00am"
                    dt = datetime.strptime(
                        f"{dt_str} {time_str}", "%m-%d-%Y %I:%M%p"
                    ).replace(tzinfo=timezone.utc)

                impact   = item.get("impact", "low").lower()
                currency = item.get("country", "").upper()
                title    = item.get("title", "")

                events.append(EconomicEvent(
                    datetime_utc = dt,
                    currency     = currency,
                    impact       = impact,
                    title        = title,
                    actual       = item.get("actual"),
                    forecast     = item.get("forecast"),
                    previous     = item.get("previous"),
                    source       = "forexfactory",
                ))
            except Exception:
                continue

    except Exception:
        pass

    return events


def _fetch_investing_rss() -> list[EconomicEvent]:
    """
    Fetch Investing.com economic calendar RSS as a secondary source.
    Only captures what makes it into the RSS feed (major events).
    """
    events = []
    try:
        url = "https://www.investing.com/rss/economic_calendar.rss"
        r   = requests.get(url, timeout=8,
                           headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            return events

        root = ET.fromstring(r.content)
        for item in root.findall(".//item"):
            try:
                title    = item.findtext("title", "")
                pub_date = item.findtext("pubDate", "")
                # Try to extract currency from title: "[GBP]" or "GBP - ..."
                currency_match = re.search(r"\[([A-Z]{3})\]|^([A-Z]{3})\s*-", title)
                currency = (currency_match.group(1) or currency_match.group(2)) if currency_match else "USD"

                dt = parsedate_to_datetime(pub_date)
                dt = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

                events.append(EconomicEvent(
                    datetime_utc = dt,
                    currency     = currency,
                    impact       = "high" if any(kw in title.lower() for kw in HIGH_IMPACT_KEYWORDS) else "medium",
                    title        = title,
                    source       = "investing_rss",
                ))
            except Exception:
                continue

    except Exception:
        pass

    return events


def _fetch_fred_releases() -> list[EconomicEvent]:
    """
    FRED (Federal Reserve) release calendar — US data only, very reliable.
    Free, no API key needed for basic endpoint.
    """
    events = []
    try:
        today    = datetime.now(timezone.utc).date()
        end_date = today + timedelta(days=7)
        url = (
            f"https://api.stlouisfed.org/fred/releases/dates"
            f"?realtime_start={today}&realtime_end={end_date}"
            f"&include_release_dates_with_no_data=false"
            f"&file_type=json"
        )
        r = requests.get(url, timeout=8)
        if r.status_code != 200:
            return events

        for item in r.json().get("release_dates", []):
            try:
                name     = item.get("release_name", "")
                date_str = item.get("date", "")
                dt       = datetime.strptime(date_str, "%Y-%m-%d").replace(
                    hour=13, minute=30, tzinfo=timezone.utc  # Most US releases 8:30 ET
                )
                events.append(EconomicEvent(
                    datetime_utc = dt,
                    currency     = "USD",
                    impact       = "high" if any(kw in name.lower() for kw in HIGH_IMPACT_KEYWORDS) else "medium",
                    title        = name,
                    source       = "fred",
                ))
            except Exception:
                continue

    except Exception:
        pass

    return events


# ── Main filter class ─────────────────────────────────────────────────────────

class CalendarFilter:
    """
    Central economic calendar risk filter.
    Fetches events from multiple free sources, deduplicates,
    and exposes a simple get_status() interface for the bot.
    """

    def __init__(self, firm: str = None, cache_minutes: int = 30):
        self.cfg           = get_config(firm or ACTIVE_FIRM)
        self.cache_minutes = cache_minutes
        self._cache_time   = None
        self._events:      list[EconomicEvent] = []

    def _refresh_if_needed(self):
        now = datetime.now(timezone.utc)
        if (self._cache_time is None or
                (now - self._cache_time).total_seconds() > self.cache_minutes * 60):
            self._events    = self._load_all_events()
            self._cache_time = now

    def _load_all_events(self) -> list[EconomicEvent]:
        """Load from all sources, deduplicate, sort by time."""
        all_events = []
        all_events.extend(_fetch_lseg_calendar())    # primary: highest quality
        all_events.extend(_fetch_forexfactory())     # backup: current week
        all_events.extend(_fetch_investing_rss())    # backup: major events RSS
        all_events.extend(_fetch_fred_releases())    # backup: US releases only

        # Deduplicate: same currency + same hour → keep highest impact
        seen = {}
        for ev in all_events:
            key = (ev.currency, ev.datetime_utc.strftime("%Y-%m-%d %H"), ev.title[:20])
            if key not in seen or (ev.is_high_impact() and not seen[key].is_high_impact()):
                seen[key] = ev

        return sorted(seen.values(), key=lambda e: e.datetime_utc)

    def get_events(self, symbol: str = None, hours_ahead: int = 24,
                   high_impact_only: bool = True) -> list[EconomicEvent]:
        """Return upcoming events affecting the given instrument."""
        self._refresh_if_needed()
        now     = datetime.now(timezone.utc)
        cutoff  = now + timedelta(hours=hours_ahead)

        return [
            ev for ev in self._events
            if ev.datetime_utc >= now - timedelta(minutes=30)
            and ev.datetime_utc <= cutoff
            and (not high_impact_only or ev.is_high_impact())
            and (symbol is None or ev.affects_instrument(symbol))
        ]

    def get_status(self, symbol: str) -> CalendarStatus:
        """
        Return CalendarStatus for the given instrument right now.
        This is the primary interface called by the bot on every step.
        """
        self._refresh_if_needed()
        now    = datetime.now(timezone.utc)
        cfg    = self.cfg

        close_before    = cfg.get("close_before_news_min",     30)
        no_trade_before = cfg.get("no_new_trades_news_min",    60)
        news_allowed    = cfg.get("news_trading",              True)

        # Get relevant high-impact events in the next 4 hours
        upcoming = self.get_events(symbol=symbol, hours_ahead=4, high_impact_only=True)

        if not upcoming:
            return CalendarStatus(
                block_new_trades = False,
                close_positions  = False,
                reason           = "No high-impact events in next 4 hours",
                all_events_today = self.get_events(symbol=symbol, hours_ahead=24),
            )

        next_event   = upcoming[0]
        mins_until   = next_event.minutes_until(now)

        block_trades = False
        close_pos    = False
        reason       = ""

        # If firm disallows news trading entirely
        if not news_allowed and mins_until < no_trade_before:
            block_trades = True
            reason       = (f"{cfg['name']} disallows news trading. "
                           f"{next_event.title} ({next_event.currency}) "
                           f"in {mins_until:.0f} min.")

        # Close before threshold
        if mins_until <= close_before:
            close_pos    = True
            block_trades = True
            reason       = (f"CLOSE POSITIONS: {next_event.title} "
                           f"({next_event.currency}) in {mins_until:.0f} min. "
                           f"Threshold: {close_before} min.")

        # No new trades threshold
        elif mins_until <= no_trade_before:
            block_trades = True
            reason       = (f"NO NEW TRADES: {next_event.title} "
                           f"({next_event.currency}) in {mins_until:.0f} min. "
                           f"Threshold: {no_trade_before} min.")

        # Safe until = after the event + 30 min cooldown
        safe_until = next_event.datetime_utc + timedelta(minutes=30)

        return CalendarStatus(
            block_new_trades = block_trades,
            close_positions  = close_pos,
            reason           = reason,
            next_event       = next_event,
            minutes_until    = mins_until,
            safe_until       = safe_until,
            all_events_today = self.get_events(symbol=symbol, hours_ahead=24),
        )

    def print_schedule(self, symbol: str = "EURGBP"):
        """Print today's event schedule to console."""
        events = self.get_events(symbol=symbol, hours_ahead=48, high_impact_only=False)
        print(f"\n📅 Economic Calendar — {symbol} — next 48 hours")
        print("=" * 70)
        if not events:
            print("  No events found.")
            return
        for ev in events:
            mins   = ev.minutes_until()
            impact = "🔴" if ev.is_high_impact() else ("🟡" if ev.impact == "medium" else "⚪")
            timing = f"in {mins:.0f}m" if mins > 0 else f"{abs(mins):.0f}m ago"
            print(f"  {impact} {ev.datetime_utc.strftime('%a %d %b %H:%M UTC')}  "
                  f"[{ev.currency:3s}]  {timing:>10s}  {ev.title}")
        print()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol",   default="EURGBP")
    parser.add_argument("--status",   action="store_true", help="Show current trading status")
    args = parser.parse_args()

    cal = CalendarFilter()
    cal.print_schedule(symbol=args.symbol)

    if args.status:
        status = cal.get_status(args.symbol)
        print(f"\n🤖 Trading Status for {args.symbol}:")
        print(f"  Block new trades : {status.block_new_trades}")
        print(f"  Close positions  : {status.close_positions}")
        print(f"  Reason           : {status.reason or 'All clear'}")
        if status.next_event:
            print(f"  Next event       : {status.next_event.title} ({status.next_event.currency})")
            print(f"  Minutes until    : {status.minutes_until:.0f}")
            print(f"  Safe after       : {status.safe_until.strftime('%H:%M UTC') if status.safe_until else 'N/A'}")
