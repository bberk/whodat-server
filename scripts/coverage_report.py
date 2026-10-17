#!/usr/bin/env python3
"""Build one markdown coverage report for a PR from backend and frontend coverage output.

Backend:  Cobertura XML from `pytest --cov --cov-report=xml` (coverage.xml)
Frontend: Vitest `json-summary` reporter output (coverage-summary.json)

Usage: coverage_report.py --backend coverage.xml --frontend coverage-summary.json > report.md
Either input may be omitted or missing; the report says so instead of failing.
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


def pct(value: float) -> str:
    return f"{value:.1f}%"


def backend_section(path: Path) -> str:
    if not path.is_file():
        return "### Backend\n\n_No backend coverage report found._\n"
    root = ET.parse(path).getroot()
    lines = float(root.get("line-rate", 0)) * 100
    branches = float(root.get("branch-rate", 0)) * 100
    per_file: list[tuple[float, str]] = []
    for cls in root.iter("class"):
        name = cls.get("filename", "?")
        rate = float(cls.get("line-rate", 0)) * 100
        per_file.append((rate, name))
    per_file.sort()
    out = [
        "### Backend (pytest-cov)",
        "",
        "| Metric | Coverage |",
        "|---|---|",
        f"| Lines | {pct(lines)} |",
        f"| Branches | {pct(branches)} |",
        "",
    ]
    low = [(r, n) for r, n in per_file if r < 100][:WORST_FILES]
    if low:
        out += ["Least-covered files:", "", "| File | Lines |", "|---|---|"]
        out += [f"| `{n}` | {pct(r)} |" for r, n in low]
        out.append("")
    return "\n".join(out) + "\n"


def frontend_section(path: Path) -> str:
    if not path.is_file():
        return "### Frontend\n\n_No frontend coverage report found._\n"
    data = json.loads(path.read_text())
    total = data["total"]
    out = [
        "### Frontend (vitest)",
        "",
        "| Metric | Coverage |",
        "|---|---|",
    ]
    for key in ("lines", "statements", "functions", "branches"):
        out.append(f"| {key.capitalize()} | {pct(float(total[key]['pct']))} |")
    out.append("")
    files = [
        (float(v["lines"]["pct"]), k) for k, v in data.items() if k != "total"
    ]
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
    args = parser.parse_args()

    report = "\n".join(
        [
            MARKER,
            "## Coverage report",
            "",
            backend_section(args.backend),
            frontend_section(args.frontend),
        ]
    )
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
