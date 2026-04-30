"""
Stitch Datasets — XAUUSD
=========================
Combines Dukascopy deep historical data with LSEG recent data.
Because LSEG intraday history is limited to ~1 year, we use Dukascopy for 
2004-2025 and LSEG for 2025-present.
"""

import os
import sys
from pathlib import Path

import pandas as pd

RAW_DIR = Path(__file__).parent / "raw"

def stitch(symbol="XAUUSD", tf="H1"):
    # Find newest files
    duka_files = sorted(RAW_DIR.glob(f"{symbol}_{tf}_*.parquet"))
    lseg_files = sorted(RAW_DIR.glob(f"lseg_{symbol}_{tf}_*.parquet"))

    if not duka_files:
        print(f"[{tf}] No Dukascopy data found. Waiting for download.py to finish.")
        return
    if not lseg_files:
        print(f"[{tf}] No LSEG data found. Run python data/download.py --lseg")
        return

    df_duka = pd.read_parquet(duka_files[-1])
    df_lseg = pd.read_parquet(lseg_files[-1])

    # Ensure UTC timezone
    if df_duka.index.tzinfo is None:
        df_duka.index = pd.to_datetime(df_duka.index, utc=True)
    if df_lseg.index.tzinfo is None:
        df_lseg.index = pd.to_datetime(df_lseg.index, utc=True)

    # Stitch: take Dukascopy up to the start of LSEG data, then append LSEG data
    lseg_start = df_lseg.index.min()
    
    df_duka_tail = df_duka[df_duka.index < lseg_start]
    
    stitched = pd.concat([df_duka_tail, df_lseg]).sort_index()
    stitched = stitched[~stitched.index.duplicated(keep="last")]
    
    out_path = RAW_DIR / f"stitched_{symbol}_{tf}_hybrid.parquet"
    stitched.to_parquet(out_path)
    
    print(f"✅ Stitched {tf}: {len(df_duka_tail):,} (Dukascopy) + {len(df_lseg):,} (LSEG) = {len(stitched):,} total bars")
    print(f"   Saved → {out_path}")

if __name__ == "__main__":
    print("Stitching Dukascopy deep history + LSEG recent data...")
    for tf in ["H1", "H4", "D"]:
        stitch(tf=tf)
