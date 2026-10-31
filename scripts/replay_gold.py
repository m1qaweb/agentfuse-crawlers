"""Synthetic, copyright-respectful offline extractor regression corpus.

This code NEVER fetches websites. Synthetic examples establish regression
behavior, NOT the independent accuracy required for production release gates.
"""

import argparse
import json
from datetime import date
from decimal import Decimal
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.rate_units import analyze_cell
from agentfuse_crawlers.sources import load_sources

DEFAULT_SUITE = Path(__file__).resolve().parents[1] / "tests/fixtures/p08_release_cases.json"
RATE_SAMPLES = 240


def load_suite(path=DEFAULT_SUITE):
    suite = json.loads(Path(path).read_text(encoding="utf-8"))
    if (suite.get("schema_version") != "1.0"
            or suite.get("origin") != "synthetic_examples_no_vendor_html"
            or suite.get("independently_human_reviewed") is not False):
        raise ValueError("Synthetic fixture manifest identity mismatch")
    cases = suite.get("cases")
    known = {row["id"]: row for row in load_sources()}
    if not isinstance(cases, list) or len(cases) < 24:
        raise ValueError("Expected at least 24 independent synthetic release examples")
    seen = set()
    github = 0
    for case in cases:
        sid = case.get("source_id")
        if not isinstance(sid, str) or sid not in known:
            raise ValueError("Unknown fixture source ID")
        if known[sid]["category"] != "changelog" or sid in seen:
            raise ValueError("Invalid or duplicate fixture changelog source")
        if case.get("layout") not in {
            "article_time", "relative_time", "month_group",
            "yearless_dateline", "dateline", "version_only",
            "inline_prefix",
        }:
            raise ValueError("Invalid synthetic fixture rendering layout")
        if not isinstance(case.get("title"), str) or not case["title"]:
            raise ValueError("Missing synthetic event title")
        exp = case.get("expected")
        if exp is not None:
            if not isinstance(exp, str) or len(exp) != 10:
                raise ValueError("Expected ISO publication day or null")
            try:
                date.fromisoformat(exp)
            except ValueError as exc:
                raise ValueError("Invalid golden publication day") from exc
        seen.add(sid)
        if urlsplit(known[sid]["url"]).hostname == "github.com":
            github += 1
    if github < 15:
        raise ValueError("At least 15 separate official GitHub release-pattern sources required")
    return suite


def render_case(case):
    """Render a minimal representative layout without copying vendor prose."""
    title = escape(case["title"])
    slug = escape(case["source_id"].replace("_", "-"))
    day = case.get("date")
    layout = case["layout"]
    body = "Synthetic release test text only. No vendor statement or actual product claim."
    if layout in {"article_time", "relative_time"}:
        tag = "relative-time" if layout == "relative_time" else "time"
        markup = (
            f'<article><h2 id="release-{slug}">{title}</h2>'
            f'<{tag} datetime="{escape(day)}T11:30:00Z">Published</{tag}>'
            f"<p>{body}</p></article>"
        )
    elif layout == "month_group":
        year, month, number = day.split("-")
        if (year, month) != ("2026", "10"):
            raise ValueError("Synthetic month group fixture must be October 2026")
        markup = (
            f'<h2>October, 2026</h2><div>Oct {int(number)}</div>'
            f'<h3 id="release-{slug}">{title}</h3><p>{body}</p>'
        )
    elif layout == "yearless_dateline":
        markup = (
            f"<p>{escape(day)}</p><h2 id='release-{slug}'>{title}</h2>"
            f"<p>{body}</p>"
        )
    elif layout == "dateline":
        iso = date.fromisoformat(day)
        markup = (
            f"<p>October {iso.day}, 2026</p>"
            f'<h2 id="release-{slug}">{title}</h2><p>{body}</p>'
        )
    elif layout == "version_only":
        markup = f'<h2 id="release-{slug}">{title}</h2><p>{body}</p>'
    else:
        markup = (
            f'<h2 id="release-{slug}">{escape(day)} — {title}</h2>'
            f"<p>{body}</p>"
        )
    return (
        "<html><head><title>Synthetic change log</title></head>"
        "<body><main><h1>Changelog</h1>"
        + markup + "</main></body></html>"
    )


def _release_report(suite):
    known = {row["id"]: row for row in load_sources()}
    results = []
    correct = 0
    false_latest = 0
    for case in suite["cases"]:
        source = known[case["source_id"]]
        extracted = extract_evidence(
            render_case(case), source["url"], category="changelog",
            source_id=source["id"],
        )
        matches = [event for event in extracted["release_events"]
                   if event.get("title") == case["title"]]
        if len(matches) == 1:
            actual = matches[0].get("published_at")
            precision = matches[0].get("published_date_precision")
            approved = matches[0].get("approved_for_advisor")
        else:
            actual, precision, approved = None, "missing_or_duplicate", None
        expected = case["expected"]
        passed = (
            len(matches) == 1 and actual == expected
            and precision == ("day" if expected is not None else "unknown")
            and approved is False
        )
        if passed:
            correct += 1
        if expected is None and actual is not None:
            false_latest += 1
        results.append({
            "source_id": case["source_id"],
            "layout": case["layout"],
            "expected_published_day": expected,
            "observed_published_day": actual,
            "passed": passed,
            "synthetic_only": True,
        })
    return {
        "cases": len(results),
        "correct": correct,
        "errors": len(results) - correct,
        "false_latest_date_errors": false_latest,
        "accuracy": round(correct / len(results), 5) if results else 0,
        "cases_result": results,
    }


def _rate_report():
    correct = 0
    failures = []
    for i in range(RATE_SAMPLES):
        amount = Decimal(i + 1) / Decimal("100")
        raw = "USD " + format(amount, ".2f")
        dimension = "Input price" if i % 2 == 0 else "Output price"
        row = analyze_cell(
            raw, model_label=f"Model-{i:03}",
            column_header=dimension, row_header=f"Model-{i:03}",
            table_context="Region: Global Tier: Standard",
            table_caption="USD per 1M tokens",
        )
        expected_dimension = "input" if i % 2 == 0 else "output"
        success = bool(
            row["comparable_candidate"]
            and Decimal(row["normalized_amount_decimal"]) == amount
            and row["currency"] == "USD"
            and row["billing_unit"] == "per_1m_tokens"
            and row["price_dimension"] == expected_dimension
            and row["region"] == "Global"
            and row["tier_or_plan"] == "Standard"
            and row["model_or_service"] == f"Model-{i:03}"
        )
        if success:
            correct += 1
        else:
            failures.append(i)
    negative = [
        ("USD 1.50", "", "USD per 1M tokens"),       # missing tier
        ("USD 1.50", "Tier: Standard", "USD per 1M tokens"),  # missing region
        ("$1.50", "Region: Global Tier: Standard", "per 1M tokens"),  # ambiguous $
        ("USD 1.50", "Region: Global Tier: Standard", "USD"),  # missing unit
        ("USD 1.50*", "Region: Global Tier: Standard", "USD per 1M tokens"),
        ("USD 1.50 promotion", "Region: Global Tier: Standard", "USD per 1M tokens"),
        ("Contact sales", "Region: Global Tier: Standard", "USD per 1M tokens"),
        ("Custom pricing", "Region: Global Tier: Standard", "USD per 1M tokens"),
        ("Free", "Region: Global Tier: Standard", "USD per 1M tokens"),
    ]
    false_comparable = []
    for i, (raw, context, caption) in enumerate(negative):
        obs = analyze_cell(
            raw, model_label="Model-Negative",
            column_header="Input price", row_header="Model-Negative",
            table_context=context, table_caption=caption,
        )
        if obs["comparable_candidate"]:
            false_comparable.append(i)
    return {
        "cases": RATE_SAMPLES, "correct": correct,
        "errors": RATE_SAMPLES - correct,
        "accuracy": round(correct / RATE_SAMPLES, 5),
        "negative_cases": len(negative),
        "negative_false_comparable": len(false_comparable),
        "failed_cases": failures, "failed_negative_cases": false_comparable,
    }


def replay_synthetic(suite_path=DEFAULT_SUITE):
    """Return explicit synthetic regression results. NEVER independent gold."""
    suite = load_suite(suite_path)
    dates = _release_report(suite)
    rates = _rate_report()
    return {
        "schema_version": "1.0",
        "origin": suite["origin"],
        "synthetic_only": True,
        "independently_human_reviewed": False,
        "date_cases": dates["cases"],
        "date_correct": dates["correct"],
        "date_accuracy": dates["accuracy"],
        "false_latest_date_errors": dates["false_latest_date_errors"],
        "rate_cases": rates["cases"],
        "rate_correct": rates["correct"],
        "rate_accuracy": rates["accuracy"],
        "unscoped_rate_false_comparable": rates["negative_false_comparable"],
        "approved_for_advisor": False,
        "pass": bool(
            dates["errors"] == 0 and dates["false_latest_date_errors"] == 0
            and rates["errors"] == 0 and rates["negative_false_comparable"] == 0
        ),
        "date_results": dates["cases_result"],
        "rate_failed_cases": rates["failed_cases"],
        "rate_failed_negative_cases": rates["failed_negative_cases"],
        "notice": (
            "These are synthetic regression fixtures, not 200 independently "
            "reviewed real vendor pricing rows or a live Zyte canary result."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--out", type=Path,
                        default=Path("output/golden-replay/synthetic_report.json"))
    args = parser.parse_args()
    report = replay_synthetic(args.fixtures)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "pass": report["pass"], "date_cases": report["date_cases"],
        "date_correct": report["date_correct"],
        "rate_cases": report["rate_cases"], "rate_correct": report["rate_correct"],
        "negative_false_comparable": report["unscoped_rate_false_comparable"],
        "synthetic_only": True,
    }))
    if not report["pass"]:
        print(json.dumps({
            "failed_release_examples": [
                row for row in report["date_results"] if not row["passed"]
            ],
            "failed_price_rows": report["rate_failed_cases"][:20],
            "failed_noncomparable_rows": report["rate_failed_negative_cases"],
        }, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
