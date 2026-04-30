"""
Data Downloader — XAUUSD Historical OHLCV
==========================================
Downloads free tick/OHLCV data from Dukascopy.

Sources:
  1. Dukascopy  — Free H1 OHLCV, 2004-present, institutional quality
                  Same data used by professional backtesting platforms
                  No API key required

Output:
  data/raw/XAUUSD_H1_<start>_<end>.parquet   — raw download
  data/raw/XAUUSD_H4_<start>_<end>.parquet
  data/raw/XAUUSD_D_<start>_<end>.parquet

Usage:
  python data/download.py                          # full download 2004-present
  python data/download.py --start 2020-01-01       # partial
  python data/download.py --tf H1 H4 D             # specific timeframes
  python data/download.py --verify                  # check data integrity
"""

import argparse
import io
import os
import sys
import time
import struct
import lzma
import calendar as cal_mod
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime, timedelta, timezone
from pathlib  import Path
from typing   import List, Optional

import numpy  as np
import pandas as pd
import requests
from tqdm import tqdm

from config.settings    import DATA, INSTRUMENT
from config.instruments import get_instrument, ACTIVE_INSTRUMENT

# ── Paths ─────────────────────────────────────────────────────────────────────
RAW_DIR = Path(__file__).parent / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

INST   = get_instrument(ACTIVE_INSTRUMENT)
SYMBOL = INST["symbol"]          # "XAUUSD"


# ════════════════════════════════════════════════════════════════════════════════
# DUKASCOPY DOWNLOADER
# ════════════════════════════════════════════════════════════════════════════════

# Dukascopy instrument codes
DUKASCOPY_INSTRUMENTS = {
    "XAUUSD": "XAUUSD",
    "EURGBP": "EURGBP",
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
}

# Dukascopy timeframe codes
DUKASCOPY_TF = {
    "M1":  "MIN",
    "M5":  "5MINS",
    "M15": "15MINS",
    "M30": "30MINS",
    "H1":  "1HOUR",
    "H4":  "4HOURS",
    "D":   "1DAY",
    "W":   "1WEEK",
}

DUKASCOPY_BASE = "https://datafeed.dukascopy.com/datafeed"


def _dukascopy_url(symbol: str, tf: str, year: int, month: int,
                   day: int = None, hour: int = None) -> str:
    """Build Dukascopy data URL for given period."""
    month_zero = f"{month - 1:02d}"  # Dukascopy month folders are zero-based
    if tf.upper() in ("TICK", "H1", "M1", "M5", "M15", "M30"):
        day_str = f"{day:02d}"
        hour_str = f"{hour:02d}h_ticks.bi5"
        return f"{DUKASCOPY_BASE}/{symbol}/{year}/{month_zero}/{day_str}/{hour_str}"
    raise ValueError(f"Unsupported direct fetch tf: {tf}")

def _parse_bi5(data: bytes, base_dt: datetime, symbol: str, tf: str = "TICK") -> pd.DataFrame:
    """
    Parse Dukascopy tick .bi5 binary format.
    Row format is 20 bytes: ms(u32), ask(u32), bid(u32), ask_vol(f32), bid_vol(f32).
    """
    if not data:
        return pd.DataFrame()

    try:
        raw = lzma.decompress(data)
    except Exception:
        return pd.DataFrame()

    record_size = 20
    if len(raw) % record_size != 0:
        return pd.DataFrame()

    divisor = 1000.0 if symbol in ("XAUUSD", "XAGUSD") else 100000.0
    records = []
    for i in range(0, len(raw), record_size):
        chunk = raw[i:i + record_size]
        try:
            ms, ask, bid, ask_vol, bid_vol = struct.unpack('>IIIff', chunk)
        except Exception:
            return pd.DataFrame()
        dt = base_dt + timedelta(milliseconds=ms)
        open_p = (ask + bid) / 2.0 / divisor
        vol = max(float(ask_vol), float(bid_vol), 0.0)
        records.append({
            'datetime': dt,
            'price': round(open_p, 2),
            'volume': vol,
        })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
    return df.set_index('datetime').sort_index()

def _fetch_dukascopy_day(symbol: str, year: int, month: int, day: int,
                          session: requests.Session) -> pd.DataFrame:
    """Fetch one day of tick data from Dukascopy and aggregate to H1."""
    frames = []
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.dukascopy.com/"}
    for hour in range(24):
        url = _dukascopy_url(symbol, "TICK", year, month, day, hour)
        base_dt = datetime(year, month, day, hour, 0, tzinfo=timezone.utc)
        try:
            r = session.get(url, timeout=20, headers=headers)
            if r.status_code == 200 and r.content:
                df_tick = _parse_bi5(r.content, base_dt, symbol, "TICK")
                if not df_tick.empty:
                    frames.append(df_tick)
        except Exception:
            continue
        time.sleep(0.02)

    if not frames:
        return pd.DataFrame()

    ticks = pd.concat(frames).sort_index()
    bars = ticks['price'].resample('1h').ohlc()
    vol = ticks['volume'].resample('1h').sum()
    df = bars.join(vol.rename('volume')).dropna()
    return df[['open','high','low','close','volume']]

def download_dukascopy_h1(symbol: str, start: str, end: str,
                           out_path: Path = None,
                           workers: int = 8) -> pd.DataFrame:
    """
    Download full H1 OHLCV history from Dukascopy.
    Uses a thread pool for parallel day fetching (~6-8x faster than sequential).

    Parameters
    ----------
    symbol   : str   e.g. "XAUUSD"
    start    : str   "YYYY-MM-DD"
    end      : str   "YYYY-MM-DD"
    out_path : Path  output parquet file
    workers  : int   parallel threads (default 8; >16 risks rate limiting)
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt   = datetime.strptime(end,   "%Y-%m-%d").replace(tzinfo=timezone.utc)

    if out_path is None:
        out_path = RAW_DIR / f"{symbol}_H1_{start}_{end}.parquet"

    # Resume: load existing data if partial download exists
    existing = pd.DataFrame()
    if out_path.exists():
        try:
            existing = pd.read_parquet(out_path)
            if not existing.empty:
                last_dt  = existing.index.max()
                start_dt = last_dt.replace(tzinfo=timezone.utc) + timedelta(days=1)
                print(f"  Resuming from {start_dt.date()} (have {len(existing):,} bars)")
        except Exception:
            pass

    if start_dt >= end_dt:
        print(f"  Data already complete: {len(existing):,} H1 bars")
        return existing

    # Generate list of weekdays to download
    days = []
    cur  = start_dt
    while cur <= end_dt:
        if cur.weekday() < 5:
            days.append((cur.year, cur.month, cur.day))
        cur += timedelta(days=1)

    print(f"  Downloading {symbol} H1 from {start_dt.date()} to {end_dt.date()}")
    print(f"  Total days: {len(days):,}  |  Workers: {workers}  |  Est. bars: ~{len(days) * 22:,}")

    # Thread-safe accumulators
    lock       = threading.Lock()
    all_frames = [existing] if not existing.empty else []
    failed_ct  = [0]
    done_ct    = [0]

    def fetch_day(args):
        """Each thread creates its own Session to avoid contention."""
        year, month, day = args
        s = requests.Session()
        try:
            return _fetch_dukascopy_day(symbol, year, month, day, s)
        finally:
            s.close()

    with tqdm(total=len(days), desc=f"  {symbol} H1", unit="day",
              bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]") as pbar:

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(fetch_day, d): d for d in days}
            for future in as_completed(futures):
                try:
                    df_day = future.result()
                    with lock:
                        if not df_day.empty:
                            all_frames.append(df_day)
                        else:
                            failed_ct[0] += 1
                        done_ct[0] += 1
                        # Checkpoint every 300 completed days
                        if done_ct[0] % 300 == 0 and all_frames:
                            ck = pd.concat(all_frames).sort_index()
                            ck = ck[~ck.index.duplicated(keep="last")]
                            ck.to_parquet(out_path)
                except Exception:
                    with lock:
                        failed_ct[0] += 1
                        done_ct[0] += 1
                pbar.update(1)

    if not all_frames:
        print(f"  ⚠ No data downloaded. Check symbol and date range.")
        return pd.DataFrame()

    df = pd.concat(all_frames).sort_index()
    df = df[~df.index.duplicated(keep="last")]

    df_h1 = df.resample("1h").agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna(subset=["open", "close"])

    df_h1.to_parquet(out_path)
    print(f"  ✅ Saved {len(df_h1):,} H1 bars → {out_path}")
    print(f"  ⚠ Failed days: {failed_ct[0]}")
    return df_h1




def download_dukascopy_htf(symbol: str, tf: str, start: str, end: str,
                            out_path: Path = None) -> pd.DataFrame:
    """Build H4 or Daily data by resampling downloaded H1 bars."""
    if tf not in ("H4", "D"):
        raise ValueError(f"Unsupported tf: {tf}")

    if out_path is None:
        out_path = RAW_DIR / f"{symbol}_{tf}_{start}_{end}.parquet"

    h1_path = RAW_DIR / f"{symbol}_H1_{start}_{end}.parquet"
    if not h1_path.exists():
        print(f"  H1 base file not found ({h1_path.name}) — downloading H1 first")
        df_h1 = download_dukascopy_h1(symbol, start, end, h1_path)
    else:
        df_h1 = pd.read_parquet(h1_path)
        if df_h1.index.tzinfo is None:
            df_h1.index = pd.to_datetime(df_h1.index, utc=True)

    if df_h1.empty:
        print(f"  ⚠ Cannot build {tf}; H1 data is empty.")
        return pd.DataFrame()

    rule = '4h' if tf == 'H4' else '1D'
    df = df_h1.resample(rule).agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }).dropna(subset=['open','close'])

    df.to_parquet(out_path)
    print(f"  ✅ Saved {len(df):,} {tf} bars → {out_path}")
    return df

def verify_data(df: pd.DataFrame, tf: str = "H1") -> dict:
    """
    Run data integrity checks on downloaded OHLCV data.
    Returns dict of issues found.
    """
    issues = {}

    if df.empty:
        return {"CRITICAL": "DataFrame is empty"}

    # Check required columns
    required = ["open", "high", "low", "close", "volume"]
    missing  = [c for c in required if c not in df.columns]
    if missing:
        issues["missing_columns"] = missing

    # Check OHLC logic
    bad_hl = (df["high"] < df["low"]).sum()
    bad_hc = (df["high"] < df["close"]).sum()
    bad_lo = (df["low"]  > df["open"]).sum()
    if bad_hl: issues["high_lt_low"]    = int(bad_hl)
    if bad_hc: issues["high_lt_close"]  = int(bad_hc)
    if bad_lo: issues["low_gt_open"]    = int(bad_lo)

    # Check for zeros
    zero_close = (df["close"] <= 0).sum()
    if zero_close: issues["zero_close"] = int(zero_close)

    # Check for NaN
    nan_count = df[required].isna().sum().sum()
    if nan_count: issues["nan_values"]  = int(nan_count)

    # Check gaps (H1 should have ~16-18 bars per weekday)
    if tf == "H1":
        df_copy  = df.copy()
        df_copy["gap_hours"] = df_copy.index.to_series().diff().dt.total_seconds() / 3600
        large_gaps = df_copy[df_copy["gap_hours"] > 6].shape[0]  # >6hr gap on weekday
        if large_gaps > 100:
            issues["large_gaps"] = large_gaps

    # Summary stats
    issues["_summary"] = {
        "total_bars":  len(df),
        "date_range":  f"{df.index.min().date()} → {df.index.max().date()}",
        "years":       round((df.index.max() - df.index.min()).days / 365.25, 1),
        "price_range": f"${df['close'].min():.2f} → ${df['close'].max():.2f}",
        "avg_volume":  round(df["volume"].mean(), 2),
    }

    return issues


def print_verify_report(df: pd.DataFrame, tf: str = "H1"):
    issues = verify_data(df, tf)
    summary = issues.pop("_summary", {})

    print(f"\n{'='*55}")
    print(f"  Data Verification Report — {SYMBOL} {tf}")
    print(f"{'='*55}")
    for k, v in summary.items():
        print(f"  {k:<18}: {v}")

    if issues:
        print(f"\n  ⚠ Issues found:")
        for k, v in issues.items():
            print(f"    {k}: {v}")
    else:
        print(f"\n  ✅ All integrity checks passed")
    print(f"{'='*55}")


# ════════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys as _sys
    parser = argparse.ArgumentParser(description="Download XAUUSD OHLCV data")
    parser.add_argument("--symbol",  default=SYMBOL)
    parser.add_argument("--start",   default="2004-01-01")
    parser.add_argument("--end",     default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--tf",      nargs="+", default=["H1"], choices=["H1","H4","D"])
    parser.add_argument("--workers", type=int, default=8,
                        help="Parallel download threads (default 8; max ~16)")
    parser.add_argument("--verify",  action="store_true")
    parser.add_argument("--lseg",    action="store_true",
                        help="Download LSEG OHLCV, macro, calendar and sentiment data")
    args = parser.parse_args()

    if args.lseg:
        try:
            from data.lseg_client import (
                open_session, download_ohlcv, download_macro,
                download_calendar, download_sentiment,
            )
            print("\nLSEG Workspace download starting...")
            if not open_session():
                print("  LSEG session unavailable — check credentials or lseg-data install")
                _sys.exit(1)
            for tf in args.tf:
                download_ohlcv(args.symbol, tf, args.start, args.end)
            download_macro(args.start, args.end)
            download_calendar(args.start, args.end)
            download_sentiment(args.start, args.end)
            print("  LSEG download complete — caches saved to data/cache/")
        except ImportError:
            print("  data/lseg.py not found or lseg-data not installed.")
            print("  Install: pip install lseg-data vaderSentiment")
        _sys.exit(0)

    print(f"\nData Downloader -- {args.symbol}")
    print(f"  Period : {args.start} to {args.end}")
    print(f"  TFs    : {args.tf}\n")

    if args.verify:
        for tf in args.tf:
            pattern = list(RAW_DIR.glob(f"{args.symbol}_{tf}_*.parquet"))
            if not pattern:
                print(f"  No {tf} data found in {RAW_DIR}")
                continue
            df = pd.read_parquet(sorted(pattern)[-1])
            print_verify_report(df, tf)
        _sys.exit(0)

    downloaded = {}
    for tf in args.tf:
        print(f"\n-- {args.symbol} {tf} from Dukascopy --")
        if tf == "H1":
            df = download_dukascopy_h1(args.symbol, args.start, args.end,
                                       workers=args.workers)
        else:
            df = download_dukascopy_htf(args.symbol, tf, args.start, args.end)
        downloaded[tf] = df

    for tf, df in downloaded.items():
        if not df.empty:
            print_verify_report(df, tf)
