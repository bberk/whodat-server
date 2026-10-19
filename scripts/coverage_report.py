#!/usr/bin/env python3
"""Build one markdown coverage report for a PR from backend and frontend coverage output.

Backend:  Cobertura XML from `pytest --cov --cov-report=xml` (coverage.xml)
Frontend: Vitest `json-summary` reporter output (coverage-summary.json)

Usage: coverage_report.py --backend coverage.xml --frontend coverage-summary.json > report.md
Either input may be omitted or missing; the report says so instead of failing.

Pass `--base-backend`/`--base-frontend` (the same artifacts from the base branch) to add the
change against the base branch. A missing or unreadable base report is reported as `n/a`, never as
a failure. The report also lists the two modules that AC-DX-03 requires at 100%.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MARKER = "<!-- coverage-report -->"
WORST_FILES = 8
TARGET_MODULES = ("app/domain/vp_engine.py", "app/domain/standings.py")
FRONTEND_METRICS = ("lines", "statements", "functions", "branches")
NA = "n/a"


def pct(value: float) -> str:
    return f"{value:.1f}%"


def delta(current: float, base: float | None) -> str:
    """Format the change from the base branch in percentage points, or `n/a` without a base."""
    if base is None:
        return NA
    return f"{current - base:+.1f} pp"


def _cobertura_rates(root: ET.Element) -> dict[str, tuple[float, float]]:
    """Map every class filename in a Cobertura report to its (lines, branches) percentages."""
    rates: dict[str, tuple[float, float]] = {}
    for cls in root.iter("class"):
        name = cls.get("filename", "?")
        rates[name] = (
            float(cls.get("line-rate", 0)) * 100,
            float(cls.get("branch-rate", 0)) * 100,
        )
    return rates


def _backend_totals(path: Path | None) -> tuple[float, float] | None:
    """Return the (lines, branches) totals of a Cobertura report, or None when unusable."""
    if path is None or not path.is_file():
        return None
    try:
        root = ET.parse(path).getroot()
        return float(root.get("line-rate", 0)) * 100, float(root.get("branch-rate", 0)) * 100
    except (ET.ParseError, OSError, ValueError):
        return None


def _frontend_totals(path: Path | None) -> dict[str, float] | None:
    """Return the frontend totals per metric, or None when the summary is missing or unusable."""
    if path is None or not path.is_file():
        return None
    try:
        total = json.loads(path.read_text())["total"]
        return {key: float(total[key]["pct"]) for key in FRONTEND_METRICS}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def backend_section(path: Path, base_path: Path | None) -> str:
    if not path.is_file():
        return "### Backend\n\n_No backend coverage report found._\n"
    root = ET.parse(path).getroot()
    lines = float(root.get("line-rate", 0)) * 100
    branches = float(root.get("branch-rate", 0)) * 100
    base = _backend_totals(base_path) or (None, None)
    per_file: list[tuple[float, str]] = []
    for cls in root.iter("class"):
        name = cls.get("filename", "?")
        rate = float(cls.get("line-rate", 0)) * 100
        per_file.append((rate, name))
    per_file.sort()
    rates = _cobertura_rates(root)
    out = [
        "### Backend (pytest-cov)",
        "",
        f"Change from base branch: {delta(lines, base[0])} lines, "
        f"{delta(branches, base[1])} branches.",
        "",
        "| Metric | Coverage | Δ base |",
        "|---|---|---|",
        f"| Lines | {pct(lines)} | {delta(lines, base[0])} |",
        f"| Branches | {pct(branches)} | {delta(branches, base[1])} |",
        "",
        "Modules required at 100% (AC-DX-03):",
        "",
        "| Module | Lines | Branches |",
        "|---|---|---|",
    ]
    for module in TARGET_MODULES:
        found = next((v for k, v in rates.items() if k.endswith(module)), None)
        if found is None:
            out.append(f"| `{module}` | {NA} | {NA} |")
        else:
            out.append(f"| `{module}` | {pct(found[0])} | {pct(found[1])} |")
    out.append("")
    low = [(r, n) for r, n in per_file if r < 100][:WORST_FILES]
    if low:
        out += ["Least-covered files:", "", "| File | Lines |", "|---|---|"]
        out += [f"| `{n}` | {pct(r)} |" for r, n in low]
        out.append("")
    return "\n".join(out) + "\n"


def frontend_section(path: Path, base_path: Path | None) -> str:
    if not path.is_file():
        return "### Frontend\n\n_No frontend coverage report found._\n"
    data = json.loads(path.read_text())
    total = data["total"]
    base = _frontend_totals(base_path) or {}
    out = [
        "### Frontend (vitest)",
        "",
        f"Change from base branch: {delta(float(total['lines']['pct']), base.get('lines'))} lines, "
        f"{delta(float(total['branches']['pct']), base.get('branches'))} branches.",
        "",
        "| Metric | Coverage | Δ base |",
        "|---|---|---|",
    ]
    for key in FRONTEND_METRICS:
        current = float(total[key]["pct"])
        out.append(f"| {key.capitalize()} | {pct(current)} | {delta(current, base.get(key))} |")
    out.append("")
    files = [(float(v["lines"]["pct"]), k) for k, v in data.items() if k != "total"]
    files.sort()
    low = [(r, n) for r, n in files if r < 100][:WORST_FILES]
    if low:
        out += ["Least-covered files:", "", "| File | Lines |", "|---|---|"]
        out += [f"| `{n}` | {pct(r)} |" for r, n in low]
        out.append("")
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", type=Path, default=Path("coverage.xml"))
    parser.add_argument("--frontend", type=Path, default=Path("coverage-summary.json"))
    parser.add_argument(
        "--base-backend",
        type=Path,
        default=None,
        help="backend coverage.xml from the base branch, for the delta column",
    )
    parser.add_argument(
        "--base-frontend",
        type=Path,
        default=None,
        help="frontend coverage-summary.json from the base branch, for the delta column",
    )
    args = parser.parse_args()

    report = "\n".join(
        [
            MARKER,
            "## Coverage report",
            "",
            backend_section(args.backend, args.base_backend),
            frontend_section(args.frontend, args.base_frontend),
        ]
    )
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
