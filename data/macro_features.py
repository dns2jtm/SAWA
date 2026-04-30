"""
Macro feature pipeline for EURGBP RL agent.

Sources (all free, no API key required):
  - FRED (Federal Reserve): VIX, US-UK rate spread, DXY
  - Bank of England: Official base rate
  - ECB: Deposit facility rate
  - ONS: UK CPI, GDP surprises (via FRED proxies)

These features give the agent macro regime awareness — the single
strongest driver of EURGBP directional bias is the BOE/ECB rate differential.

Usage:
    from data.macro_features import build_macro_df, merge_macro
    macro_df = build_macro_df("2003-01-01", "2025-12-31")
    full_df  = merge_macro(price_df, macro_df)
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

FRED_SERIES = {
    # Interest rates — the #1 EURGBP driver
    "boe_rate"        : "BOERUKM",      # Bank of England base rate (monthly)
    "ecb_rate"        : "ECBDFR",       # ECB deposit facility rate (daily)

    # Risk sentiment
    "vix"             : "VIXCLS",       # CBOE VIX — risk-off proxy (daily)

    # UK macro
    "uk_cpi_yoy"      : "GBRCPIALLMINMEI",  # UK CPI YoY (monthly)
    "uk_gdp_growth"   : "CLVMNACSCAB1GQUK", # UK real GDP QoQ (quarterly)

    # EUR macro
    "eu_cpi_yoy"      : "CP0000EZ19M086NEST",  # Eurozone CPI YoY (monthly)

    # FX context
    "dxy"             : "DTWEXBGS",     # USD broad index — risk-on/off proxy (daily)
    "gbpusd"          : "DEXUSUK",      # GBP/USD — EURGBP cross context (daily)
    "eurusd"          : "DEXUSEU",      # EUR/USD — needed to compute EURGBP (daily)
}


# ── FRED downloader ───────────────────────────────────────────────────────────

def _fetch_fred(series_id: str, start: str, end: str) -> pd.Series:
    """Fetch a single FRED series. No API key required for public series."""
    try:
        import fredapi
        # Try with API key from env first, fall back to no-key
        api_key = os.getenv("FRED_API_KEY", "")
        fred = fredapi.Fred(api_key=api_key) if api_key else fredapi.Fred()
        s = fred.get_series(series_id, observation_start=start, observation_end=end)
        s.name = series_id
        return s
    except ImportError:
        # fredapi not installed — use direct FRED API (no key needed for most series)
        import urllib.request, json
        url = (
            f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
            f"&vintage_date={end[:10]}"
        )
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                from io import StringIO
                text = resp.read().decode()
                df_s = pd.read_csv(StringIO(text), index_col=0, parse_dates=True)
                s = df_s.iloc[:, 0]
                s.name = series_id
                mask = (s.index >= start) & (s.index <= end)
                return s[mask]
        except Exception as e:
            print(f"[FRED] Could not fetch {series_id}: {e}")
            return pd.Series(dtype=float, name=series_id)


def build_macro_df(start: str, end: str, force_refresh: bool = False) -> pd.DataFrame:
    """
    Build a daily macro feature DataFrame covering start → end.
    Cached to Parquet. Forward-fills lower-frequency series (monthly/quarterly)
    to daily so it can be merged with H1 price data.
    """
    cache_file = os.path.join(
        CACHE_DIR,
        f"macro_{start[:10]}_{end[:10]}.parquet".replace("-", "")
    )
    if os.path.exists(cache_file) and not force_refresh:
        df = pd.read_parquet(cache_file)
        print(f"[MACRO] Loaded from cache: {len(df):,} daily rows")
        return df

    print(f"[MACRO] Downloading macro features ({start} → {end}) ...")
    daily_idx = pd.date_range(start, end, freq="D", tz="UTC")
    df = pd.DataFrame(index=daily_idx)

    for col, series_id in FRED_SERIES.items():
        try:
            s = _fetch_fred(series_id, start, end)
            if s.empty:
                continue
            # Ensure UTC DatetimeIndex
            if s.index.tz is None:
                s.index = s.index.tz_localize("UTC")
            else:
                s.index = s.index.tz_convert("UTC")
            # Replace FRED missing value sentinel
            s = s.replace(".", np.nan).astype(float)
            df[col] = s.reindex(daily_idx, method="ffill")
            print(f"  ✅ {col} ({series_id}): {s.notna().sum():,} observations")
        except Exception as e:
            print(f"  ⚠️  {col} ({series_id}): {e}")

    # ── Derived features ──────────────────────────────────────────────────────
    # Rate differential — the primary EURGBP driver
    if "boe_rate" in df.columns and "ecb_rate" in df.columns:
        df["rate_differential"] = df["boe_rate"] - df["ecb_rate"]

    # EURGBP cross-check from GBP/USD and EUR/USD
    if "gbpusd" in df.columns and "eurusd" in df.columns:
        df["eurgbp_macro"] = df["eurusd"] / df["gbpusd"]

    # Inflation differential
    if "uk_cpi_yoy" in df.columns and "eu_cpi_yoy" in df.columns:
        df["inflation_differential"] = df["uk_cpi_yoy"] - df["eu_cpi_yoy"]

    # VIX regime flag (>20 = elevated risk, >30 = crisis)
    if "vix" in df.columns:
        df["vix_elevated"] = (df["vix"] > 20).astype(np.float32)
        df["vix_crisis"]   = (df["vix"] > 30).astype(np.float32)

    df.dropna(how="all", inplace=True)
    df.to_parquet(cache_file, index=True)
    print(f"[MACRO] Saved → {os.path.basename(cache_file)} | {len(df):,} rows, {len(df.columns)} features")
    return df


def merge_macro(price_df: pd.DataFrame, macro_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge macro daily features into H1 price DataFrame.
    Forward-fills macro values across intraday bars.

    Args:
        price_df  : H1 OHLCV DataFrame with UTC DatetimeIndex
        macro_df  : Daily macro DataFrame from build_macro_df()

    Returns:
        Merged DataFrame with macro columns appended.
    """
    if price_df.index.tz is None:
        price_df.index = price_df.index.tz_localize("UTC")

    # Resample macro to H1 via forward-fill
    macro_h1 = macro_df.resample("1h").ffill()

    merged = price_df.join(macro_h1, how="left")
    macro_cols = macro_df.columns.tolist()

    # Forward-fill any remaining gaps at market open
    merged[macro_cols] = merged[macro_cols].ffill()

    # Normalise macro features
    if "rate_differential" in merged.columns:
        merged["rate_differential_z"] = (
            (merged["rate_differential"] - merged["rate_differential"].rolling(200).mean())
            / (merged["rate_differential"].rolling(200).std() + 1e-9)
        ).clip(-4, 4).astype(np.float32)

    if "vix" in merged.columns:
        merged["vix_z"] = (
            (merged["vix"] - merged["vix"].rolling(200).mean())
            / (merged["vix"].rolling(200).std() + 1e-9)
        ).clip(-4, 4).astype(np.float32)

    print(f"[MACRO] Merged {len(macro_cols)} macro features into price DataFrame")
    return merged


def get_macro_feature_cols(df: pd.DataFrame) -> list:
    """Return macro feature column names suitable for RL observation."""
    macro_obs_cols = [
        "rate_differential", "rate_differential_z",
        "inflation_differential",
        "vix", "vix_z", "vix_elevated", "vix_crisis",
        "dxy", "eurgbp_macro",
    ]
    return [c for c in macro_obs_cols if c in df.columns]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--start",   default="2003-01-01")
    parser.add_argument("--end",     default="2025-12-31")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    df = build_macro_df(args.start, args.end, force_refresh=args.refresh)
    print("\nMacro feature preview:")
    print(df.tail(10).to_string())
    print(f"\nColumns: {df.columns.tolist()}")
