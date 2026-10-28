"""Central, documented defaults. Every numeric default here is a design choice, not a standard.

Each default is covered by a test (tests/test_config.py) and, where it affects results, by a sensitivity
analysis in the validation milestone (docs/research/VALIDATION.md).
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
# recent object forward for at most this many seconds. For airborne aircraft the 95th percentile gap between
# consecutive own-quality rows is about 79 s (regenerated in docs/DATA_QUALITY.md), so 120 s covers well over 95%.
QUALITY_MAX_AGE_S = 120.0

# Source/type value for non-transponder emitters (e.g. airport ground vehicles). Excluded from aircraft metrics,
# but kept in the ingested table so the exclusion is auditable.
SRC_NON_TRANSPONDER = "adsb_icao_nt"
SRC_ADSB = "adsb_icao"  # position broadcast by the aircraft itself (readsb source tag)

H3_RES_MAIN = 5
H3_RES_FINE = 6


@dataclass(frozen=True)
class Grid:
    """Spatial and temporal aggregation unit: H3 resolution and UTC bucket length in hours (divides 24)."""

    h3_res: int
    bucket_hours: int

    def __post_init__(self):
        if 24 % self.bucket_hours:
            raise ValueError("bucket_hours must divide 24")


# Decided from data (docs/DATA_QUALITY.md, grid feasibility on 2026-03-02): at H3 res 5 / 1 h only 9% of cell-buckets
# reach the minimum sample; at res 4 / 3 h, 52% do. Volunteer receiver coverage, not statistics, sets the resolution.
GRID_MAIN = Grid(h3_res=4, bucket_hours=3)
GRID_FAST = Grid(h3_res=3, bucket_hours=1)  # coarser in space, finer in time

# Altitude strata (barometric feet). "enroute" is the union of mid and high samples and is the main detection layer.
ENROUTE_MIN_FT = 10_000
HIGH_MIN_FT = 25_000
STRATA = ("enroute", "high", "mid", "low")

# Degradation tiers. strong = NIC < 4 or NACp < 5 (NIC < 4 follows OpenSky/SkAI in RESEARCH.md; NACp < 5 is a design
# choice). gpsjam = NACp < 8, kept only for comparison with GPSJam-style maps.
NIC_STRONG_BELOW = 4
NACP_STRONG_BELOW = 5
NACP_GPSJAM_BELOW = 8

# An aircraft counts as degraded in a cell-bucket if at least this fraction of its quality-bearing samples are
# degraded and it has at least MIN_SAMPLES_PER_AIRCRAFT such samples. Measured on 2026-03-02: when an aircraft is
# degraded in a cell-hour it is usually degraded throughout (only 44 of 834 had a single degraded sample).
DEGRADED_FRACTION = 0.5
MIN_SAMPLES_PER_AIRCRAFT = 2

# A cell-bucket is testable only with at least this many distinct eligible aircraft.
MIN_AIRCRAFT_PER_CELL = 5

# Persistent low-quality emitters (avionics heterogeneity): excluded when, over the baseline window, an aircraft has
# at least PERSISTENT_MIN_SAMPLES en-route samples on at least PERSISTENT_MIN_DAYS days and a degraded share of at
# least PERSISTENT_LOW_SHARE.
PERSISTENT_MIN_SAMPLES = 200
PERSISTENT_MIN_DAYS = 3
PERSISTENT_LOW_SHARE = 0.9

# --- jamming-like detection (design choices, tested for sensitivity in docs/research/VALIDATION.md) ---
DETECT_FDR_Q = 0.05
DETECT_MIN_BAD = 3  # at least this many degraded aircraft in the cell-bucket
DETECT_MIN_LOWER_BOUND = 0.20  # Wilson lower bound of the degraded share must exceed this (effect-size gate)
DETECT_P0_FLOOR = 0.02  # baseline degraded share never assumed below this
DETECT_HIGH_LOWER_BOUND = 0.40
DETECT_MERGE_GAP_BUCKETS = 1  # events merge across at most this many empty buckets

# --- spoofing-like detection (design choices; frozen before the held-out run) ---
SPOOF_JUMP_MIN_KT = 650.0  # implied ground speed between consecutive fixes
SPOOF_JUMP_MIN_KM = 5.0
SPOOF_JUMP_SPEED_RATIO = 2.5  # implied speed must also exceed this multiple of the reported speed (floor 100 kt)
SPOOF_DT_FLOOR_S = (
    1.0  # implied speed is computed over at least this many seconds (median fix gap is about 4 s; 54% are < 5 s)
)
SPOOF_DT_MAX_S = 120.0
SPOOF_CLUSTER_KM = 20.0  # jump destinations within this distance...
SPOOF_CLUSTER_MIN = 30 * 60  # ...and this many seconds are the same cluster
SPOOF_MIN_AIRCRAFT = 3  # distinct aircraft needed for a spoofing-like event
SPOOF_HIGH_AIRCRAFT = 5
SPOOF_HIGH_SPREAD_KM = 10.0
