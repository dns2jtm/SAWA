from pathlib import Path
import sys
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env.ftmo_env import FTMOEnv

def make_dummy_df():
    idx = pd.date_range("2024-01-01", periods=50, freq="h", tz="UTC")
    df = pd.DataFrame({
        "datetime": idx,
        "open": 2000.0,
        "high": 2001.0,
        "low": 1999.0,
        "close": 2000.5,
        "volume": 1000.0,
        "hour": [d.hour for d in idx],
        "day_of_week": [d.dayofweek for d in idx],
    })
    return df

def test_env_info_contract_keys_exist():
    env = FTMOEnv(make_dummy_df(), training=True)
    obs, info = env.reset()

    required = {
        "balance",
        "equity",
        "daily_pnl",
        "total_pnl",
        "position",
        "days_traded",
        "trades_today",
        "n_trades",
        "trading_days",
        "final_pnl_pct",
        "challenge_passed",
        "daily_dd_breach",
        "total_dd_breach",
        "profit_target",
        "max_daily_loss",
        "max_total_loss",
        "calendar_blocked",
        "firm",
    }

    missing = required.difference(info.keys())
    assert not missing, f"Missing keys: {missing}"


if __name__ == "__main__":
    test_env_info_contract_keys_exist()
    print("PASS  test_env_info_contract_keys_exist")
