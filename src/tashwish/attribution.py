"""Single source of truth for attribution wording (see docs/LICENSING.md section 4).

Every public surface (README, data card, dataset sidecar, dashboard footer, exported charts) takes its text from here;
tests/test_attribution.py fails if a document drifts from these strings.
"""

SOURCE_NAME = "adsb.lol"
SOURCE_URL = "https://github.com/adsblol/globe_history"
ODBL_URL = "https://opendatacommons.org/licenses/odbl/1-0/"

# ODbL 4.3.a example notice, with the database name substituted.
NOTICE = "Contains information from adsb.lol, which is made available here under the Open Database License (ODbL)."
NOTICE_LINKED_MD = (
    f"Contains information from [adsb.lol]({SOURCE_URL}), which is made available here under the "
    f"[Open Database License (ODbL)]({ODBL_URL})."
)
DERIVED_NOTICE = "This derived database (Tashwish aggregates) is also made available under the ODbL 1.0."
DATASET_ATTRIBUTION = f"{NOTICE} {DERIVED_NOTICE}"
# Synthetic samples must never claim adsb.lol content. Valid only when data_class is "synthetic".
SYNTHETIC_ATTRIBUTION = "SYNTHETIC SAMPLE: contains no information from adsb.lol."


def attribution_for(data_class: str) -> str:
    """Canonical attribution text for a data class ("synthetic" gets the synthetic notice, anything else the ODbL one)."""
    return SYNTHETIC_ATTRIBUTION if data_class == "synthetic" else DATASET_ATTRIBUTION


CODE_LICENCE_LINE = "Code: Apache-2.0. Data: ODbL 1.0. Contains information from adsb.lol."
