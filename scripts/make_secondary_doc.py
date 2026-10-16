"""Write docs/SECONDARY_ANALYSES.md from result files (results/secondary/*.json, results/regimes.csv).

Numbers come from the files; only the list of public sources (fetched 2026-10-16) is text in this script. Nothing here changes
the detector, a threshold or a published result.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from tashwish import config as cfg
from tashwish.split import split

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "SECONDARY_ANALYSES.md"

# Public sources fetched on 2026-10-16. Each row: what the source states, as paraphrased here, and the URL.
SOURCES = [
    (
        "EASA, Conflict Zone Information Bulletin 2026-03 (revision R14 page)",
        "Original bulletin issued 28/02/2026 for the airspace of Bahrain, Iran, Iraq, Israel, Jordan, Kuwait, Lebanon, Oman, "
        "Qatar, the United Arab Emirates and Saudi Arabia; recommends not operating in part of it and caution in the rest. "
        "The page text retrieved does not mention GNSS, jamming or spoofing.",
        "https://www.easa.europa.eu/en/domains/air-operations/czibs/2026-03-r14",
    ),
    (
        "Aviation trade news item, dated 2 March 2026",
        "States that the airspace of several countries in the region, including Bahrain, Kuwait, Qatar and the United Arab "
        "Emirates, was closed to all commercial traffic on 28 February 2026.",
        "https://www.ch-aviation.com/news/164379-gulf-iran-iraq-syria-israel-close-to-all-traffic",
    ),
    (
        "Windward, maritime analytics report, dated 18 June 2026",
        "Reports GPS jamming affecting vessels concentrated in the Middle East Gulf in the first quarter of 2026, accelerating "
        "sharply over two weeks in early 2026 (Strait of Hormuz, Persian Gulf, Gulf of Oman). Its Gulf sections do not mention "
        "aircraft.",
        "https://windward.ai/blog/what-is-gps-jamming-and-why-are-we-seeing-so-much-of-it/",
    ),
    (
        "Radionavigation Laboratory, University of Texas at Austin, post dated March 2026",
        "Reports navigation disruption for ships in the Persian Gulf and the Gulf of Oman and notes that aircraft GNSS receivers "
        "use the same civil signal. It names no dataset or measurement method.",
        "https://radionavlab.ae.utexas.edu/?p=5268",
    ),
]


def f3(x: float) -> str:
    return f"{x:.3f}"


def beta_binomial_section() -> list[str]:
    r = json.loads((ROOT / "results" / "secondary" / "beta_binomial.json").read_text(encoding="utf-8"))
    rep = r["reproduction"]
    lines = [
        "## 1. Beta binomial sensitivity of the jamming-like flags (OBSERVED, development days only)",
        "",
        "Source: `results/secondary/beta_binomial.json`, written by `scripts/beta_binomial_sensitivity.py`.",
        "",
        "Question: the detector tests each cell bucket against a binomial distribution, which treats the baseline share as known",
        "and every aircraft as independent. How many flags survive if degraded reports are allowed to cluster within a cell",
        "bucket (a beta binomial tail with the same mean and an intra cell bucket correlation rho)? Every other rule is unchanged.",
        "This section reads development days only.",
        "",
        f"Reproduction check: rebuilding the binomial flags from the processed cell buckets gives {rep['rebuilt_jamming_events']} "
        f"jamming-like events on the {r['n_days']} development days; the committed events contain "
        f"{rep['committed_distinct_jamming_components']} distinct jamming components; days that differ: "
        f"{', '.join(rep['days_differing']) or 'none'}.",
        "",
        "| Degraded regime | Days | Tested units | Mean dispersion ratio | rho (day bootstrap 95%) | Flags, binomial | Flags at rho low, point, high |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, g in r["by_degraded_regime"].items():
        c = g["counts"]
        rho = (
            "not estimable (underdispersed, set to 0)"
            if g["mean_dispersion_ratio"] < 1
            else f"{f3(g['rho'])} ({f3(g['rho_ci'][0])} to {f3(g['rho_ci'][1])})"
        )
        lines.append(
            f"| {name} | {g['n_days']} | {g['n_tested_units']} | {f3(g['mean_dispersion_ratio'])} | {rho} | "
            f"{c['binomial']['flags']} | {c['rho_low']['flags']}, {c['rho_point']['flags']}, {c['rho_high']['flags']} |"
        )
    lines += ["", "Flags remaining at fixed values of rho:", "", "| Degraded regime | " +
              " | ".join(f"rho {k}" for k in next(iter(r["by_degraded_regime"].values()))["flags_by_rho_grid"]) + " |"]  # fmt: skip
    lines.append("|---|" + "---|" * len(next(iter(r["by_degraded_regime"].values()))["flags_by_rho_grid"]))
    for name, g in r["by_degraded_regime"].items():
        lines.append(f"| {name} | " + " | ".join(str(v) for v in g["flags_by_rho_grid"].values()) + " |")
    lines += ["", "Reading (derived from the result file):", ""]
    for name, g in r["by_degraded_regime"].items():
        c, n = g["counts"], g["counts"]["binomial"]["flags"]
        kept = sorted({c[k]["flags"] for k in ("rho_low", "rho_point", "rho_high")})
        drop = [k for k, v in g["flags_by_rho_grid"].items() if v < n]
        first_drop = f"; on the fixed grid, fewer flags remain from rho {drop[0]}" if drop else ""
        if g["mean_dispersion_ratio"] < 1:
            lines.append(
                f"- {name.capitalize()} days: the dispersion ratio is {f3(g['mean_dispersion_ratio'])}, below 1, so rho cannot "
                f"be estimated by moments and is set to 0; {kept[-1]} of {n} binomial flags remain{first_drop}. A ratio below 1 "
                f"is consistent with the floor of {cfg.DETECT_P0_FLOOR} on the baseline share when typical shares are lower, "
                "which makes the binomial test conservative."
            )
        else:
            survive = f"{kept[0]}" if len(kept) == 1 else f"{kept[0]} to {kept[-1]}"
            lines.append(
                f"- {name.capitalize()} days: the dispersion ratio is {f3(g['mean_dispersion_ratio'])} (1 means binomial); "
                f"with rho anywhere in its interval, {survive} of the {n} binomial flags remain{first_drop}."
            )
    lines += [
        "- The extra variation on elevated days may be clustering within cell buckets, a shift of the degraded share from day"
        " to day, or a baseline share that does not fit individual cells; the moment estimate cannot tell these apart. The"
        " binomial p values on those days are miscalibrated, in either direction for a given unit.",
        f"- Limits: {r['n_days']} development days and few flags; one moment estimator; the units used to estimate rho exclude"
        " the binomial flags. This is a sensitivity analysis, not a change to the detector.",
        "",
    ]
    return lines


def injection_section() -> list[str]:
    return [
        "## 2. More realistic injection variants (not done)",
        "",
        "Partial degradation of an aircraft's samples, drifting spoof tracks and one scenario per run need the per sample",
        "points of the development days. The repository stores only cell bucket aggregates. The validation harness fits the",
        "persistent emitter list from the points of all development days together, so even one variant needs every development",
        "day downloaded and parsed again (about 2 to 4 GiB of archive per day, `docs/OPERATIONS.md` section 4). That exceeded",
        "the time budget of the session and would be a heavy load on a volunteer archive whose fair use terms are unverified,",
        "so it was not started. No number exists for it.",
        "",
    ]


def regime_section() -> list[str]:
    reg = pd.read_csv(ROOT / "results" / "regimes.csv").sort_values("day")
    first_red = reg.loc[reg["traffic"] == "reduced", "day"].min()
    first_el = reg.loc[reg["degraded"] == "elevated", "day"].min()
    gap = (pd.Timestamp(first_el) - pd.Timestamp(first_red)).days
    held = {d.isoformat() for d in split()[1]}
    kind = {d: "a held out day" if d in held else "a development day" for d in (first_red, first_el)}
    lines = [
        "## 3. The regime change and public sources",
        "",
        "No cause is identified and none is asserted. Nothing here attributes interference to any state or actor. Several of",
        "the sources below discuss who may be responsible; this repository does not repeat or adopt any such attribution.",
        "",
        "What the data show, quoted from results already published (`results/regimes.csv`, the README status block and",
        f"`docs/VALIDATION.md`): the first day labelled traffic reduced is {first_red} ({kind[first_red]}) and the first day",
        f"labelled degraded elevated is {first_el} ({kind[first_el]}). These published labels are quoted, not recomputed, and",
        "no held out day is analysed further here.",
        "",
        "What public sources state (fetched 2026-10-16; paraphrased; no copy is stored; the sources' claims are theirs):",
        "",
        "| Source | What it states | Link |",
        "|---|---|---|",
    ]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in SOURCES]
    lines += [
        "",
        "What is reported, and what is not established:",
        "",
        "- Reported by the sources (reports, not ground truth): from 28 February 2026 several airspaces in the study box were",
        "  closed to commercial traffic, and a European regulator advised against or cautioned on operating there.",
        "- Reported by the sources: widespread GPS jamming affecting ships in Gulf waters in early 2026. None of the fetched",
        "  sources gives an aviation measurement.",
        f"- Consistent timing, not an established cause: the traffic drop in the data starts on {first_red}, the date of the",
        f"  reported closures, and the rise in degraded reports starts on {first_el}, {gap} day(s) later.",
        "- Not established: that the rise in degraded ADS-B reports is caused by interference rather than by other changes",
        "  (which aircraft still fly, routing, avionics, receiver coverage). The rise also holds for the same aircraft seen before",
        "  and after (`results/dev/regime_check.json`), which argues against a pure change of aircraft mix but does not prove",
        "  interference.",
        "- UNVERIFIED: changes in the adsb.lol receiver network in the same days (feeder counts were not retrieved; they could",
        "  be checked from the archive's receiver files or by asking the maintainers), and aviation specific interference",
        "  reports (for example GPSJam or regulator notices), which were not fetched or checked here.",
        "",
    ]
    return lines


def main() -> None:
    lines = [
        "# Secondary analyses",
        "",
        "Generated by `scripts/make_secondary_doc.py` from result files. Secondary means: not preregistered, not part of the",
        "held out evaluation, and not a change to the detector. Research and monitoring tool, not for navigation or safety of",
        "life.",
        "",
        *beta_binomial_section(),
        *injection_section(),
        *regime_section(),
    ]
    DOC.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {DOC}")


if __name__ == "__main__":
    main()
