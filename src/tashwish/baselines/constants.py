"""Baseline constants. Fixed by docs/BASELINES.md (Specification) before any baseline was run; never tuned on any day."""

from __future__ import annotations

# B1 fixed fraction (a priori; 0.10 is the red boundary of the public map described in docs/RESEARCH.md section 1.1)
B1_MIN_SHARE = 0.10
B1_MIN_AIRCRAFT = 5  # a priori; the cited text states no minimum

# B1b: percent bad uses (bad minus 1) in the numerator, as the public map described in docs/RESEARCH.md section 1.1
B1B_SPARSITY_OFFSET = 1

# B2 climatology z score per cell and 3 hour slot, development days only
B2_Z = 3.0
B2_MIN_AIRCRAFT = 5
B2_MIN_DAYS = 3

# B3c: per test threshold replacing false discovery control
B3C_ALPHA = 0.01

# B4 naive speed threshold on single position jumps
B4_MIN_KT = 800.0
B4_DT_MAX_S = 120.0
B4_DT_FLOOR_S = 1.0
