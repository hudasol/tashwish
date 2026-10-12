from datetime import date

from tashwish.split import PREVIOUSLY_EXAMINED, is_held_out, split, study_days


def test_partition_is_complete_and_disjoint():
    dev, held = split()
    assert set(dev) | set(held) == set(study_days())
    assert not set(dev) & set(held)


def test_expected_pinned_split():
    # Pinned: changing the rule after seeing results must fail this test and be explained in docs/PREDICTIONS.md
    _, held = split()
    assert [d.isoformat() for d in held] == [
        "2026-02-07", "2026-02-10", "2026-02-11", "2026-02-12", "2026-02-15", "2026-02-18", "2026-02-24",
        "2026-02-26", "2026-02-28", "2026-03-01", "2026-03-03", "2026-03-08", "2026-03-10", "2026-03-13",
    ]  # fmt: skip


def test_examined_days_never_held_out():
    for d in PREVIOUSLY_EXAMINED:
        assert not is_held_out(d)


def test_deterministic():
    assert is_held_out(date(2026, 2, 28)) == is_held_out(date(2026, 2, 28))
