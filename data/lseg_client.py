"""
LSEG (London Stock Exchange Group) Workspace Integration
=========================================================
Wraps the lseg-data Python library to provide four data streams:

  1. OHLCV history  — XAUUSD H1/H4/D via XAU= RIC
  2. Macro series   — real DXY (.DXY), VIX (.VIX), US 10Y TIPS real yield
  3. Economic calendar — EcoRelease with actual/forecast/surprise
  4. News sentiment — Reuters headlines scored with VADER or keyword lexicon

All functions are:
  - OPTIONAL  : degrade gracefully when Workspace is not running or
                lseg-data is not installed; callers receive an empty
                DataFrame and continue using Dukascopy / FRED / scrape data.
  - CACHED    : results saved to data/cache/lseg_*.parquet so the feature
                pipeline can run offline after a one-time download.
  - ADDITIVE  : existing column names in FeaturePipeline are preserved;
                LSEG data replaces the *values* of the proxy features
                (dxy_proxy, real_yield_proxy, vix_proxy, sentiment_score …)
                without changing the 65-column OBS_COLUMNS schema.

Prerequisites:
  pip install lseg-data            # LSEG Python library
  pip install vaderSentiment       # optional — improves sentiment scoring

  LSEG Workspace must be running on the local machine to open a session.
  After a download, the cache works without Workspace.

CLI (one-off download):
  python data/lseg.py --ohlcv --macro --calendar --sentiment
  python data/lseg.py --macro --start 2004-01-01 --end 2026-04-27
  python data/lseg.py --status   # check whether a session can be opened

In-pipeline usage:
  from data.lseg import load_macro_cache, load_sentiment_cache
  macro_df = load_macro_cache()          # returns cached daily DataFrame
  sent_df  = load_sentiment_cache()      # returns cached hourly DataFrame
"""

import logging
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import warnings
warnings.filterwarnings("ignore")

from datetime import datetime, timedelta, timezone
from pathlib  import Path
from typing   import Optional

import numpy  as np
import pandas as pd

log = logging.getLogger("lseg")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

# ── Paths ─────────────────────────────────────────────────────────────────────

RAW_DIR   = Path(__file__).parent / "raw"
CACHE_DIR = Path(__file__).parent / "cache"
RAW_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# ── RIC / interval definitions ────────────────────────────────────────────────

OHLCV_RICS = {
    "XAUUSD_H1": ("XAU=", "1h"),
    "XAUUSD_D":  ("XAU=", "1D"),
}

MACRO_RICS = {
    "dxy":        ".DXY",         # US Dollar Index          → replaces dxy_proxy
    "real_yield": "US10YTIP=RR",  # US 10Y TIPS real yield   → replaces real_yield_proxy
    "vix":        ".VIX",         # CBOE VIX                 → replaces vix_proxy
    "us10y":      "US10YT=RR",    # US 10Y nominal yield     (bonus)
    "gold_spot":  "XAU=",         # Gold spot (daily close)  (bonus)
    "silver":     "XAG=",         # Silver spot              (for gold/silver ratio)
}

NEWS_QUERY = "XAU gold FOMC Federal Reserve inflation CPI dollar"

# ── Session management ────────────────────────────────────────────────────────

_SESSION_OPEN = False


def open_session() -> bool:
    """Open LSEG Workspace desktop session. Returns True on success."""
    global _SESSION_OPEN
    if _SESSION_OPEN:
        return True
    try:
        import lseg.data as ld        # noqa: F401
        ld.open_session()
        _SESSION_OPEN = True
        log.info("LSEG session opened")
        return True
    except ImportError as e:
        log.warning(f"lseg-data not installed or missing dependency: {e}")
        return False
    except Exception as exc:
        log.warning(f"LSEG session failed (is Workspace running?): {exc}")
        return False


def close_session() -> None:
    """Close the active LSEG session."""
    global _SESSION_OPEN
    if _SESSION_OPEN:
        try:
            import lseg.data as ld
            ld.close_session()
        except Exception:
            pass
        _SESSION_OPEN = False


def _ld():
    """Return the lseg.data module, or raise a clear RuntimeError."""
    try:
        import lseg.data as ld
        return ld
    except ImportError:
        raise RuntimeError(
            "lseg-data is not installed.  Run: pip install lseg-data"
        )


def session_available() -> bool:
    """Return True if a session can be opened (Workspace running + library installed)."""
    return open_session()


# ════════════════════════════════════════════════════════════════════════════════
# 1. OHLCV HISTORY
# ════════════════════════════════════════════════════════════════════════════════

def download_ohlcv(
    symbol: str = "XAUUSD",
    tf:     str = "H1",
    start:  str = "2004-01-01",
    end:    str = None,
    force:  bool = False,
) -> pd.DataFrame:
    """
    Download OHLCV bars from LSEG Workspace and cache to Parquet.

    Parameters
    ----------
    symbol : "XAUUSD"
    tf     : "H1", "H4", or "D"
    start  : ISO date string
    end    : ISO date string (defaults to today)
    force  : re-download even if a cache file exists

    Returns
    -------
    pd.DataFrame with UTC index and columns [open, high, low, close, volume],
    or an empty DataFrame if LSEG is unavailable.
    """
    end = end or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"{symbol}_{tf}"
    if key not in OHLCV_RICS:
        raise ValueError(
            f"Unsupported symbol/tf '{key}'.  Choices: {list(OHLCV_RICS)}"
        )

    out_path = RAW_DIR / f"lseg_{symbol}_{tf}_{start[:4]}_{end[:4]}.parquet"
    if out_path.exists() and not force:
        try:
            df = pd.read_parquet(out_path)
            if not df.empty:
                log.info(f"LSEG OHLCV  [{key}]  loaded from cache: {len(df):,} bars")
                return df
        except Exception:
            pass

    if not open_session():
        return pd.DataFrame()

    ric, interval = OHLCV_RICS[key]
    try:
        lib = _ld()
        log.info(f"Downloading {key} from LSEG  {start} → {end} ...")
        raw = lib.get_history(
            universe = ric,
            interval = interval,
            start    = start,
            end      = end,
        )
        if raw is None or raw.empty:
            log.warning(f"LSEG returned empty data for {ric}")
            return pd.DataFrame()

        raw.index  = pd.to_datetime(raw.index, utc=True)
        log.info(f"LSEG Raw columns: {list(raw.columns)}")
        
        # Flatten MultiIndex if necessary, and handle tuples
        raw.columns = [str(c).lower() for c in raw.columns]
        
        # Robustly map varying LSEG column names to standard indicator names
        rename_dict = {}
        def _find(keywords, prioritize_mid=True):
            cols = list(raw.columns)
            if prioritize_mid:
                for k in keywords:
                    for c in cols:
                        if k in c and "mid" in c: return c
            for k in keywords:
                if k in cols: return k
            for k in keywords:
                for c in cols:
                    if k in c: return c
            return None
            
        c_open = _find(["open"])
        c_high = _find(["high"])
        c_low  = _find(["low"])
        c_close = _find(["close", "price", "prc", "last", "bid", "ask"])
        c_vol  = _find(["volume", "vol"])
        
        if c_open: rename_dict[c_open] = "open"
        if c_high: rename_dict[c_high] = "high"
        if c_low: rename_dict[c_low] = "low"
        if c_close: rename_dict[c_close] = "close"
        if c_vol: rename_dict[c_vol] = "volume"
        
        raw.rename(columns=rename_dict, inplace=True)
        
        # Deduplicate columns if any (keep first)
        raw = raw.loc[:, ~raw.columns.duplicated()]

        # Check standard fields
        for col in ["open", "high", "low", "close", "volume"]:
            if col not in raw.columns:
                if col == "volume": raw["volume"] = 0.0
                else: raw[col] = raw.get("close", np.nan) # Forward fill any missing OHL from close

        df = raw[["open", "high", "low", "close", "volume"]].dropna(
            subset=["close"]
        )
        df.to_parquet(out_path)
        log.info(f"  ✅  {key}: {len(df):,} bars  →  {out_path.name}")
        return df

    except Exception as exc:
        log.warning(f"LSEG OHLCV download error: {exc}")
        return pd.DataFrame()


# ════════════════════════════════════════════════════════════════════════════════
# 2. MACRO SERIES  (DXY · VIX · Real Yield · US10Y · Gold/Silver)
# ════════════════════════════════════════════════════════════════════════════════

def download_macro(
    start: str = "2004-01-01",
    end:   str = None,
    force: bool = False,
) -> pd.DataFrame:
    """
    Download real macro time-series from LSEG at daily frequency.

    Columns returned
    ----------------
    dxy          : US Dollar Index (.DXY)
    real_yield   : US 10Y TIPS yield — the primary gold inverse driver
    vix          : CBOE VIX spot level
    us10y        : US 10Y nominal Treasury yield
    gold_spot    : LSEG gold daily close (quality check vs Dukascopy)
    silver       : Silver spot close (for gold/silver ratio)
    gold_silver  : Gold / silver ratio  (derived)
    real_yield_chg5 : 5-day change in real yield  (derived)
    vix_z        : VIX z-score vs trailing 252-day window  (derived)
    dxy_z        : DXY z-score vs trailing 252-day window  (derived)

    Returns empty DataFrame if LSEG unavailable; caller uses proxy features.
    """
    end = end or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = CACHE_DIR / f"lseg_macro_{start[:4]}_{end[:4]}.parquet"

    if out_path.exists() and not force:
        try:
            df = pd.read_parquet(out_path)
            if not df.empty:
                if df.index.tzinfo is None:
                    df.index = df.index.tz_localize("UTC")
                log.info(f"LSEG macro  loaded from cache: {len(df)} rows, {len(df.columns)} cols")
                return df
        except Exception:
            pass

    if not open_session():
        return pd.DataFrame()

    lib = _ld()
    series = {}
    for col, ric in MACRO_RICS.items():
        try:
            raw = lib.get_history(
                universe = ric,
                interval = "1D",
                start    = start,
                end      = end,
            )
            if raw is not None and not raw.empty:
                raw.index = pd.to_datetime(raw.index, utc=True)
                raw.columns = [c.lower() for c in raw.columns]
                close_col = "close" if "close" in raw.columns else raw.columns[0]
                series[col] = raw[close_col].rename(col)
                log.info(f"  ✅  {col:15s} ({ric}): {series[col].notna().sum():,} obs")
        except Exception as exc:
            log.warning(f"  ⚠   {col:15s} ({ric}): {exc}")

    if not series:
        log.warning("LSEG macro: no series downloaded")
        return pd.DataFrame()

    df = pd.concat(series.values(), axis=1).sort_index()

    # ── Derived features ──────────────────────────────────────────────────────
    if "gold_spot" in df.columns and "silver" in df.columns:
        df["gold_silver"] = (df["gold_spot"] / (df["silver"] + 1e-9)).clip(0, 200)

    if "real_yield" in df.columns:
        df["real_yield_chg5"] = df["real_yield"].diff(5)

    if "vix" in df.columns:
        df["vix_z"] = (
            (df["vix"] - df["vix"].rolling(252, min_periods=30).mean())
            / (df["vix"].rolling(252, min_periods=30).std() + 1e-9)
        ).clip(-3, 3)

    if "dxy" in df.columns:
        df["dxy_z"] = (
            (df["dxy"] - df["dxy"].rolling(252, min_periods=30).mean())
            / (df["dxy"].rolling(252, min_periods=30).std() + 1e-9)
        ).clip(-3, 3)

    df.to_parquet(out_path)
    log.info(f"LSEG macro  saved  →  {out_path.name}  | {len(df)} rows")
    return df


# ════════════════════════════════════════════════════════════════════════════════
# 3. ECONOMIC CALENDAR
# ════════════════════════════════════════════════════════════════════════════════

def download_calendar(
    start: str = None,
    end:   str = None,
    force: bool = False,
) -> pd.DataFrame:
    """
    Download economic calendar events from LSEG EcoRelease.

    Columns returned
    ----------------
    datetime_utc  : event timestamp (UTC)
    currency      : affected currency (USD, EUR, GBP, ...)
    title         : event name
    impact        : "high" / "medium" / "low"
    actual        : actual reported value (str)
    forecast      : consensus forecast  (str)
    previous      : prior value         (str)
    surprise      : actual_f - forecast_f (float)
    source        : "lseg"

    Returns empty DataFrame if LSEG unavailable.
    """
    today = datetime.now(timezone.utc)
    start = start or today.strftime("%Y-%m-%d")
    end   = end   or (today + timedelta(days=14)).strftime("%Y-%m-%d")

    fname    = f"lseg_calendar_{start[:10].replace('-','')}_{end[:10].replace('-','')}.parquet"
    out_path = CACHE_DIR / fname
    if out_path.exists() and not force:
        try:
            df = pd.read_parquet(out_path)
            if not df.empty:
                return df
        except Exception:
            pass

    if not open_session():
        return pd.DataFrame()

    try:
        lib = _ld()
        raw, err = lib.get_data(
            universe   = ["ECOREL"],
            fields     = [
                "TR.ECOREL_DT",
                "TR.ECOREL_NAME",
                "TR.ECOREL_ACT",
                "TR.ECOREL_FORE",
                "TR.ECOREL_PRIOR",
                "TR.ECOREL_IMP",
                "TR.ECOREL_CURR",
            ],
            parameters = {"SDate": start, "EDate": end},
        )
        if raw is None or raw.empty:
            return pd.DataFrame()

        raw.columns = [
            "datetime_utc", "title", "actual", "forecast",
            "previous", "impact", "currency",
        ]
        raw["datetime_utc"] = pd.to_datetime(raw["datetime_utc"], utc=True)

        # Map LSEG numeric impact codes → strings
        imp_map = {1: "low", 2: "medium", 3: "high",
                   "1": "low", "2": "medium", "3": "high"}
        raw["impact"] = raw["impact"].map(imp_map).fillna("low")

        def _f(s):
            return pd.to_numeric(s, errors="coerce")

        raw["surprise"] = _f(raw["actual"]) - _f(raw["forecast"])
        raw["source"]   = "lseg"

        raw.to_parquet(out_path)
        log.info(f"LSEG calendar  {len(raw)} events  →  {out_path.name}")
        return raw

    except Exception as exc:
        msg = str(exc)
        if "ECOREL" in msg or "resolve" in msg:
            log.info("LSEG calendar ('ECOREL') not available on this tier. Falling back to ForexFactory/RSS.")
        else:
            log.warning(f"LSEG calendar download error: {exc}")
        return pd.DataFrame()


# ════════════════════════════════════════════════════════════════════════════════
# 4. NEWS SENTIMENT
# ════════════════════════════════════════════════════════════════════════════════

_VADER_ANALYZER = None


def _score(text: str) -> float:
    """Score a headline in [-1, +1]. Uses VADER if available, else gold lexicon."""
    global _VADER_ANALYZER
    if not isinstance(text, str) or not text:
        return 0.0

    if _VADER_ANALYZER is None:
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            _VADER_ANALYZER = SentimentIntensityAnalyzer()
        except ImportError:
            _VADER_ANALYZER = False

    if _VADER_ANALYZER:
        return float(_VADER_ANALYZER.polarity_scores(text)["compound"])

    # Keyword lexicon — gold-specific
    t = text.lower()
    BULLISH = [
        "rise", "rally", "surge", "jump", "gain", "record high", "safe haven",
        "uncertainty", "inflation", "rate cut", "dovish", "stimulus",
        "geopolitical", "war", "crisis", "recession", "flight to safety",
        "safe-haven", "haven demand",
    ]
    BEARISH = [
        "fall", "drop", "decline", "tumble", "sell-off", "risk-on",
        "rate hike", "hawkish", "strong dollar", "tightening",
        "recovery optimism", "easing tension", "risk appetite",
    ]
    sc = sum(0.25 for w in BULLISH if w in t) - sum(0.25 for w in BEARISH if w in t)
    return float(np.clip(sc, -1.0, 1.0))


def download_sentiment(
    start:         str = "2022-01-01",
    end:           str = None,
    force:         bool = False,
    max_headlines: int  = 20_000,
) -> pd.DataFrame:
    """
    Fetch Reuters news headlines for gold/macro keywords and aggregate to
    hourly sentiment features.

    Columns returned (hourly UTC index)
    ------------------------------------
    sentiment_score    : mean compound score  [-1, +1]
    sentiment_novelty  : std dev of scores in the hour  [0, 1]
    sentiment_momentum : 6-hour EMA of sentiment_score
    news_volume        : log-normalised headline count   [0, ~1]
    event_flag         : 1 when news volume z-score > 2 (unusual burst)

    Returns empty DataFrame if LSEG unavailable.
    """
    end = end or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fname    = f"lseg_sentiment_{start[:7].replace('-','')}_{end[:7].replace('-','')}.parquet"
    out_path = CACHE_DIR / fname

    if out_path.exists() and not force:
        try:
            df = pd.read_parquet(out_path)
            if not df.empty:
                if df.index.tzinfo is None:
                    df.index = df.index.tz_localize("UTC")
                log.info(f"LSEG sentiment  loaded from cache: {len(df):,} hourly rows")
                return df
        except Exception:
            pass

    if not open_session():
        return pd.DataFrame()

    try:
        lib = _ld()
        log.info(f"Fetching Reuters headlines  {start} → {end} ...")
        raw = lib.news.get_headlines(
            query     = NEWS_QUERY,
            count     = max_headlines,
        )
        if raw is None or len(raw) == 0:
            return pd.DataFrame()

        df_n = pd.DataFrame(raw)

        # Normalise timestamp column name across API versions
        ts_col = next(
            (c for c in ["versionCreated", "publishedAt", "storyDate"] if c in df_n.columns),
            None,
        )
        if ts_col is None:
            return pd.DataFrame()

        df_n["dt"]    = pd.to_datetime(df_n[ts_col], utc=True)
        # Filter by requested dates
        start_dt = pd.to_datetime(start, utc=True)
        end_dt   = pd.to_datetime(end, utc=True)
        df_n     = df_n[(df_n["dt"] >= start_dt) & (df_n["dt"] <= end_dt)]
        if df_n.empty:
            return pd.DataFrame()
            
        text_col      = next((c for c in ["text", "headline", "title"] if c in df_n.columns), None)
        df_n["score"] = df_n[text_col].apply(_score) if text_col else 0.0

        df_n = df_n.set_index("dt").sort_index()
        h = df_n["score"].resample("1h").agg(["mean", "count", "std"]).rename(
            columns={"mean": "sentiment_score", "count": "_vol_raw", "std": "sentiment_novelty"}
        )
        h["sentiment_novelty"] = h["sentiment_novelty"].fillna(0).clip(0, 1)
        h["sentiment_score"]   = h["sentiment_score"].clip(-1, 1).fillna(0)
        h["news_volume"]       = (np.log1p(h["_vol_raw"]) / 6).clip(0, 1)
        h["sentiment_momentum"] = (
            h["sentiment_score"].ewm(span=6, adjust=False).mean()
        )
        # Event flag: unusually high news burst
        vol_ma  = h["news_volume"].rolling(24, min_periods=4).mean()
        vol_std = h["news_volume"].rolling(24, min_periods=4).std() + 1e-6
        h["event_flag"] = ((h["news_volume"] - vol_ma) / vol_std > 2.0).astype(float)
        h = h.drop(columns=["_vol_raw"]).fillna(0)

        h.to_parquet(out_path)
        log.info(f"LSEG sentiment  {len(df_n):,} headlines  →  {len(h):,} hourly rows  →  {out_path.name}")
        return h

    except Exception as exc:
        log.warning(f"LSEG sentiment download error: {exc}")
        return pd.DataFrame()


# ════════════════════════════════════════════════════════════════════════════════
# CACHE LOADERS  (used by features.py without opening a session)
# ════════════════════════════════════════════════════════════════════════════════

def load_macro_cache(start: str = None, end: str = None) -> pd.DataFrame:
    """
    Load the most recent cached LSEG macro parquet.
    Returns empty DataFrame when no cache exists.
    """
    files = sorted(CACHE_DIR.glob("lseg_macro_*.parquet"))
    if not files:
        return pd.DataFrame()
    df = pd.read_parquet(files[-1])
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")
    if start:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df.index <= pd.Timestamp(end, tz="UTC")]
    return df


def load_sentiment_cache(start: str = None, end: str = None) -> pd.DataFrame:
    """
    Load the most recent cached LSEG sentiment parquet.
    Returns empty DataFrame when no cache exists.
    """
    files = sorted(CACHE_DIR.glob("lseg_sentiment_*.parquet"))
    if not files:
        return pd.DataFrame()
    df = pd.read_parquet(files[-1])
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")
    if start:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df.index <= pd.Timestamp(end, tz="UTC")]
    return df


def load_calendar_cache() -> pd.DataFrame:
    """Load the most recent cached LSEG calendar parquet."""
    files = sorted(CACHE_DIR.glob("lseg_calendar_*.parquet"))
    if not files:
        return pd.DataFrame()
    return pd.read_parquet(files[-1])


# ════════════════════════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LSEG data downloader")
    parser.add_argument("--ohlcv",     action="store_true", help="Download XAUUSD H1/H4/D OHLCV")
    parser.add_argument("--macro",     action="store_true", help="Download macro series (DXY/VIX/TIPS)")
    parser.add_argument("--calendar",  action="store_true", help="Download economic calendar")
    parser.add_argument("--sentiment", action="store_true", help="Download Reuters news sentiment")
    parser.add_argument("--all",       action="store_true", help="Download everything")
    parser.add_argument("--status",    action="store_true", help="Check LSEG session status")
    parser.add_argument("--start",     default="2004-01-01")
    parser.add_argument("--end",       default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--force",     action="store_true", help="Force re-download (ignore cache)")
    args = parser.parse_args()

    if args.status:
        ok = session_available()
        print(f"LSEG session: {'✅ available' if ok else '❌ unavailable'}")
        if ok:
            close_session()
        sys.exit(0 if ok else 1)

    do_all = args.all

    if do_all or args.macro:
        print("\n── Macro series ───────────────────────────────")
        df = download_macro(args.start, args.end, force=args.force)
        if not df.empty:
            print(df.tail(5).to_string())

    if do_all or args.ohlcv:
        print("\n── OHLCV ──────────────────────────────────────")
        for tf in ("H1", "H4", "D"):
            df = download_ohlcv("XAUUSD", tf, args.start, args.end, force=args.force)
            if not df.empty:
                print(f"  {tf}: {len(df):,} bars  {df.index.min().date()} → {df.index.max().date()}")

    if do_all or args.calendar:
        print("\n── Economic calendar ──────────────────────────")
        df = download_calendar(args.start, args.end, force=args.force)
        if not df.empty:
            hi = df[df["impact"] == "high"]
            print(f"  Total events: {len(df)}  |  High-impact: {len(hi)}")
            print(hi[["datetime_utc","currency","title","surprise"]].head(10).to_string(index=False))

    if do_all or args.sentiment:
        print("\n── News sentiment ─────────────────────────────")
        sent_start = max(args.start, "2020-01-01")  # LSEG news history practical limit
        df = download_sentiment(sent_start, args.end, force=args.force)
        if not df.empty:
            print(df.tail(5).to_string())

    close_session()
