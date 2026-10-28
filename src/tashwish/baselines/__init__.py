"""Comparison detectors for the Tashwish evaluation (docs/BASELINES.md).

Each jamming-like baseline returns `(flags, events)` exactly like `tashwish.detect.jamming.detect_jamming`, and the
spoofing-like baseline returns `(jumps, events)` like `tashwish.detect.spoofing.detect_spoofing`, so the unchanged
injection harness can score them. The constants live in `constants.py` and are fixed by the specification section of
docs/BASELINES.md before any run. These are research comparators, not navigation or safety of life tools.
"""
