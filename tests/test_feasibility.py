import pandas as pd

from tashwish import config as cfg
from tashwish.metrics.feasibility import feasibility

T0 = pd.Timestamp("2026-03-02T00:00:00Z")


def test_feasibility_counts_eligible_aircraft_per_cell_bucket():
    rows = []
    for i in range(7):  # 7 aircraft, 3 samples each, same place: testable at every grid
        for k in range(3):
            rows.append({"icao24": f"a{i}", "ts": T0 + pd.Timedelta(minutes=k), "lat": 25.0, "lon": 55.0,
                         "alt_baro_ft": 35000, "on_ground": False, "src_type": "adsb_icao", "nic": 8, "nac_p": 9})  # fmt: skip
    for k in range(3):  # one lonely aircraft elsewhere
        rows.append({"icao24": "solo", "ts": T0 + pd.Timedelta(minutes=k), "lat": 28.0, "lon": 50.0,
                     "alt_baro_ft": 35000, "on_ground": False, "src_type": "adsb_icao", "nic": 8, "nac_p": 9})  # fmt: skip
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    out = feasibility(df, [cfg.Grid(4, 3), cfg.Grid(5, 24)])
    assert out.cell_buckets.tolist() == [2, 2]
    assert out.share_ge_5.tolist() == [0.5, 0.5]
    assert out.testable_cell_buckets.tolist() == [1, 1]
