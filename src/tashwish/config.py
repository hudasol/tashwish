"""Central, documented defaults. Every numeric default here is a design choice, not a standard.

Each default is covered by a test (tests/test_config.py) and, where it affects results, by a sensitivity
analysis in the validation milestone (docs/VALIDATION.md).
"""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = "1"

DATA_CLASS_OBSERVED = "observed"
DATA_CLASS_SYNTHETIC = "synthetic"


@dataclass(frozen=True)
class Region:
    """Gulf study box (inclusive). UAE, Qatar, Bahrain, Kuwait, north Oman, east Saudi Arabia, Iranian coast, Hormuz."""

    lat_min: float = 22.0
    lat_max: float = 31.0
    lon_min: float = 46.0
    lon_max: float = 62.0

    def contains(self, lat: float, lon: float) -> bool:
        return self.lat_min <= lat <= self.lat_max and self.lon_min <= lon <= self.lon_max


REGION = Region()

# A trace point carries quality fields only when the source wrote an aircraft object for it. We carry the most
# recent object forward for at most this many seconds. Measured on 2026-03-02: median gap between objects 8 s,
# 95th percentile 78 s, 99th percentile 288 s (docs/DATA_QUALITY.md).
QUALITY_MAX_AGE_S = 120.0

# Source/type value for non-transponder emitters (e.g. airport ground vehicles). Excluded from aircraft metrics,
# but kept in the ingested table so the exclusion is auditable.
SRC_NON_TRANSPONDER = "adsb_icao_nt"

H3_RES_MAIN = 5
H3_RES_FINE = 6
