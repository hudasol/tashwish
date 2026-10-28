from pathlib import Path

from tashwish import attribution as attr

ROOT = Path(__file__).resolve().parents[1]


def test_notice_is_odbl_example_wording():
    assert attr.NOTICE == (
        "Contains information from adsb.lol, which is made available here under the Open Database License (ODbL)."
    )


def test_public_documents_use_exact_notice():
    for rel in ("README.md", "docs/DATA_SOURCES.md", "NOTICE", "docs/DATA_CARD.md", "docs/LICENSING.md"):
        assert attr.NOTICE in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_old_short_wording_is_gone():
    for rel in ("README.md", "docs/DATA_SOURCES.md", "NOTICE", "docs/DATA_CARD.md"):
        assert "made available under the ODbL." not in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_licence_copy_shipped():
    text = (ROOT / "licenses" / "ODbL-1.0.txt").read_text(encoding="utf-8")
    assert "ODC Open Database License" in text and "Notice for using output" in text


def test_linked_notice_has_both_hyperlinks():
    assert attr.SOURCE_URL in attr.NOTICE_LINKED_MD and attr.ODBL_URL in attr.NOTICE_LINKED_MD
