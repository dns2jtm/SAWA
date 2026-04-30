import pandas as pd
from lseg_client import _ld, open_session

open_session()
try:
    lib = _ld()
    raw = lib.get_history(universe="XAU=", interval="1h", start="2004-01-01", end="2025-01-01")
    print(raw.columns)
    print(raw[['BID', 'MID_PRICE', 'OPEN_BID' ,'MID_OPEN']].head())
    print("\nNull counts:")
    print(raw.isnull().sum())
except Exception as e:
    print(e)
