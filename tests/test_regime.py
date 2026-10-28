import json

import pandas as pd
import pytest

from tashwish import regime as rg
from tashwish.validate import run as vrun


def _cb(units_each, k_each, n_cells=10):
    return pd.DataFrame(
        {"stratum": ["enroute"] * n_cells, "n_aircraft": [units_each] * n_cells, "k_strong": [k_each] * n_cells}
    )


def test_labels_are_mechanical_and_use_aggregates_only():
    normal, reduced = rg.day_stats(_cb(20, 0)), rg.day_stats(_cb(4, 2))
    assert rg.traffic_regime(normal["units"], 200.0) == "normal"
    assert rg.traffic_regime(reduced["units"], 200.0) == "reduced"
    assert rg.degraded_regime(0.01) == "baseline"
    assert rg.degraded_regime(0.05) == "elevated"
    assert rg.degraded_regime(float("nan")) == "baseline"


def test_untestable_cells_do_not_enter_the_share():
    cb = pd.concat([_cb(20, 1), _cb(2, 2)], ignore_index=True)  # the second group has fewer than 5 aircraft per cell
    assert rg.day_stats(cb)["share"] == pytest.approx(0.05)


def test_freeze_cannot_be_replaced_silently(tmp_path):
    (tmp_path).mkdir(exist_ok=True)
    (tmp_path / "FREEZE.json").write_text(json.dumps({"commit": "x"}), encoding="utf-8", newline="\n")
    with pytest.raises(SystemExit):
        vrun.freeze(tmp_path, tmp_path)  # a freeze exists and no reason is given
    (tmp_path / "held_out").mkdir()
    (tmp_path / "held_out" / "RUNNING").write_text("{}", encoding="utf-8", newline="\n")
    with pytest.raises(SystemExit):
        vrun.freeze(tmp_path, tmp_path, reason="again")  # the held-out run has started
