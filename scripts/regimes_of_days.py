"""Write results/regimes.csv: traffic and degraded regime label of every study day (labels from tashwish.regime)."""

from pathlib import Path

import pandas as pd

from tashwish.split import split
from tashwish.validate.harness import ContextFactory

dev, held = split()
fac = ContextFactory(Path("data/interim"), [d.isoformat() for d in dev])
rows = []
for name, days in (("dev", dev), ("held_out", held)):
    for d in days:
        d = d.isoformat()
        tr, dr = fac.regimes_of(d)
        st = fac.stats.get(d) or fac._extra[d]
        rows.append(
            {"day": d, "split": name, "traffic": tr, "degraded": dr, "units": st["units"], "share": st["share"]}
        )
pd.DataFrame(rows).sort_values("day").to_csv("results/regimes.csv", index=False, lineterminator="\n")
