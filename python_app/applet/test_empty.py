import pandas as pd
import sys
sys.path.insert(0, ".")
from data.lseg_client import _ld, open_session

open_session()
lib = _ld()
raw = lib.get_history(universe="XAU=", interval="PT1H", start="2004-01-01", end="2025-01-01")
print(raw.head())
print(len(raw))
