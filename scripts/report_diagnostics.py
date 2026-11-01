"""Summarize all independent diagnostic axes for exported Zyte Items offline.

Also supports legacy Items by clearly labeling recomputed diagnostics. This
command never changes source lifecycle status or approves advisor/alerts.
"""

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from agentfuse_crawlers.diagnostics import AXES, derive_diagnostics
from agentfuse_crawlers.sources import load_sources

FIELDS = (
    "job_id", "source_id", "category", "status", "legacy_primary_error",
    "diagnostic_origin", "deployment_revision", "diagnostic_reasons",
    *AXES,
)


def summarize(paths):
    manifest = {s["id"]: s for s in load_sources()}
    seen = set()
    coverage_by_job = defaultdict(set)
    categories, primary, reasons, axes = Counter(), Counter(), Counter(), {
        key: Counter() for key in AXES
    }
    source_rows = []
    mismatches = []
    for path in paths:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Items export must be a JSON array: " + str(path))
        for item in data:
            if not isinstance(item, dict):
                raise ValueError("Each Item must be a JSON object")
            sid = item.get("source_id")
            src = manifest.get(sid) if isinstance(sid, str) else None
            if not src or item.get("category") != src["category"] or item.get("source_url") != src["url"]:
                mismatches.append(str(sid)[:85])
                continue
            job = str(item.get("zyte_job_id") or "unknown_job")
            key = (job, sid)
            if key in seen:
                mismatches.append("duplicate:" + sid)
                continue
            seen.add(key)
            coverage_by_job[job].add(sid)
            existing = item.get("quality_axes")
            existing_codes = item.get("diagnostic_reason_codes")
            embedded = (
                item.get("diagnostic_schema") == "1.0"
                and isinstance(existing, dict)
                and isinstance(existing_codes, list)
                and all(isinstance(existing.get(k), str) for k in AXES)
            )
            d = {
                "quality_axes": existing, "diagnostic_reason_codes": existing_codes
            } if embedded else derive_diagnostics(item)
            origin = "embedded" if embedded else "recomputed_from_legacy_export"
            categories[src["category"]] += 1
            primary[str(item.get("error") or "(none)")] += 1
            for reason in set(d["diagnostic_reason_codes"]):
                reasons[reason] += 1
            for axis in AXES:
                axes[axis][d["quality_axes"][axis]] += 1
            source_rows.append({
                "job_id": job, "source_id": sid, "category": src["category"],
                "status": item.get("status", "unknown"),
                "legacy_primary_error": item.get("error", ""),
                "diagnostic_origin": origin,
                "deployment_revision": item.get("deployment_revision", ""),
                "diagnostic_reasons": ",".join(d["diagnostic_reason_codes"]),
                **d["quality_axes"],
            })
    return {
        "summary": {
            "report_kind": "offline_unverified_diagnostic_review",
            "source_item_count": len(source_rows),
            "category_counts": dict(sorted(categories.items())),
            "job_source_counts": {
                k: len(v) for k, v in sorted(coverage_by_job.items())
            },
            "primary_errors": dict(primary.most_common()),
            "concurrent_reasons": dict(reasons.most_common()),
            "axis_counts": {k: dict(v.most_common()) for k, v in axes.items()},
            "input_anomalies": mismatches[:200],
            "input_anomaly_count": len(mismatches),
            "advisor_approved_facts": 0,
            "deployment_authorized": False,
        },
        "rows": source_rows,
    }


def write_report(report, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(
        json.dumps(report["summary"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with (out_dir / "source_diagnostics.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(report["rows"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", nargs="+", required=True, type=Path)
    parser.add_argument("--out-dir", type=Path,
                        default=Path("output/diagnostic-review"))
    args = parser.parse_args()
    result = summarize(args.items)
    write_report(result, args.out_dir)
    print(json.dumps({
        "item_count": result["summary"]["source_item_count"],
        "anomalies": result["summary"]["input_anomaly_count"],
        "output_dir": str(args.out_dir),
        "approved_facts": 0,
    }, indent=2))


if __name__ == "__main__":
    main()
