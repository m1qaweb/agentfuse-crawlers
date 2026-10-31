"""P07 offline replay: no first-baseline news, no CDN failures as releases."""

import json

import pytest

from agentfuse_crawlers.sources import load_sources
from scripts.archive_jobs import archive_job
from scripts.evaluate_run import evaluate, write_evaluation

SOURCES = {s["id"]: s for s in load_sources()}


def fixture_row(sid, job, *, status="captured", category=None, sha="page1",
                fetched="2026-10-30T12:00:00Z"):
    s = SOURCES[sid]
    return {
        "_key": f"{job}/0", "source_id": sid, "source_url": s["url"],
        "provider": s["provider"], "category": category or s["category"],
        "status": status, "error": "HTTP 503" if status != "captured" else "",
        "content_sha256": sha,
        "schema_version": "2.1", "fetched_at_utc": fetched,
        "zyte_job_id": job,
        "manifest_sha256": "same-manifest", "source_registry_sha256": "same-registry",
        "selection_source_count": 1, "selection_ids_sha256": "same-selection",
        "requested_cohort": "all", "run_started_at_utc": fetched,
        "approved_for_advisor": False,
    }


def event(key, *, body="body", date="2026-10-31", version="1.2.0"):
    return {
        "event_id": key, "body_sha256": body,
        "title": "Version " + key,
        "version": version, "published_at": date,
        "published_date_provenance": "html_time_datetime" if date else "none",
        "permalink": "https://developers.openai.com/api/docs/changelog#v" + key,
        "excerpt": "Unverified new example API capabilities.",
    }


def release_row(job, entries, *, sha="a", fetched="2026-10-30T12:00:00Z",
                status="captured", sid="openai_api_changelog"):
    r = fixture_row(sid, job, status=status, sha=sha, fetched=fetched)
    r.update(release_events_schema="1.1", release_events=entries,
             release_window_complete=True, release_event_evidence_lost=False,
             release_event_identity_collision=False,
             release_recent_body_loss_count=0)
    return r


def priced(amount, *, region="Global", plan="Standard", unit="per_1m_tokens",
           model="Model Alpha", dimension="input", observation_id="obs1"):
    return {
        "observation_id": observation_id,
        "comparable_candidate": True,
        "model_or_service": model, "region": region,
        "tier_or_plan": plan, "price_dimension": dimension,
        "billing_unit": unit, "currency": "USD",
        "normalized_amount_decimal": amount,
        "raw_displayed_price": "USD " + amount,
        "price_state": "numeric_candidate",
        "table_id": "table-1", "row_index": 1, "column_index": 1,
        "source_url": SOURCES["openai_api_pricing"]["url"],
    }


def pricing_row(job, prices, *, sha="p", status="captured"):
    r = fixture_row("openai_api_pricing", job, status=status, sha=sha)
    r.update(pricing_evidence_schema="1.0", pricing_inventory_complete=True,
             pricing_comparable_candidate_count=len(prices),
             pricing_observations=prices,
             pricing_evidence_lost_to_item_budget=False)
    return r


def docs_row(job, sections, *, sha="d", status="captured"):
    r = fixture_row("openai_api_docs", job, sha=sha, status=status)
    r.update(
        documentation_evidence_schema="1.0",
        documentation_scope_status="scoped_page",
        documentation_profile_status="curated_pending_live_validation",
        documentation_product_scope="OpenAI API",
        documentation_topic_candidate_omitted=0,
        documentation_source_sections_truncated=False,
        documentation_item_budget_truncated=False,
        sections=sections,
    )
    return r


def doc_section(identity, sha):
    return {
        "section_id": identity, "sha256": sha, "heading": "Request API",
        "section_url": SOURCES["openai_api_docs"]["url"] + "#request-api",
        "excerpt": "A concise official documentation section about API usage.",
    }


def save_job(tmp_path, row, ordinal):
    job = row["zyte_job_id"]
    meta = {
        "state": "finished", "spider": {
            "changelog": "official_changelogs",
            "pricing": "official_pricing",
            "documentation": "official_documentation",
        }[row["category"]],
        "deploy_id": 10, "finished_time": 1793000000000 + ordinal * 100000,
        "close_reason": "finished", "spider_args": {},
        "scrapystats": {"item_scraped_count": 1},
    }
    target, _, _ = archive_job(
        job, tmp_path, api_key="offline-test",
        fetch_metadata=lambda *_: meta,
        fetch_page=lambda *args: [row],
    )
    return target


def test_first_crawl_is_historical_baseline_never_new_release(tmp_path):
    job = "883514/1/101"
    path = save_job(tmp_path, release_row(job, [event("old")]), 1)
    output = evaluate(path)
    assert [c["change_type"] for c in output["changes"]] == ["historical_baseline"]
    assert output["summary"]["advisor_approved_fact_count"] == 0
    assert output["states"][0]["latest_healthy_job_id"] == job


def test_second_crawl_first_seen_recent_release_is_only_candidate(tmp_path):
    before = save_job(tmp_path, release_row(
        "883514/1/101", [event("a", date="2026-10-20")]), 1)
    after = save_job(tmp_path, release_row(
        "883514/1/102", [
            event("b", date="2026-10-31"),
            event("a", date="2026-10-20")],
        sha="b", fetched="2026-10-31T12:00:00Z",
    ), 2)
    result = evaluate(after, [before])
    assert [x["change_type"] for x in result["changes"]] == ["new_event_candidate"]
    assert result["changes"][0]["event_id"] == "b"
    assert result["changes"][0]["approved_for_advisor"] is False


def test_reordering_same_events_produces_no_candidate(tmp_path):
    a = event("a", body="same")
    b = event("b", body="same2")
    before = save_job(tmp_path, release_row("883514/1/101", [a, b]), 1)
    after = save_job(tmp_path, release_row("883514/1/102", [b, a], sha="reordered"), 2)
    assert evaluate(after, [before])["changes"] == []


def test_stale_cdn_failure_retains_last_healthy_without_releases(tmp_path):
    old = save_job(tmp_path, release_row("883514/1/101", [event("old")]), 1)
    bad = save_job(tmp_path, release_row(
        "883514/1/102", [event("fake", body="nonsense")],
        sha="", status="http_error",
    ), 2)
    report = evaluate(bad, [old])
    assert [x["change_type"] for x in report["changes"]] == ["source_unavailable"]
    assert report["states"][0]["latest_observed_job_id"] == "883514/1/102"
    assert report["states"][0]["latest_healthy_job_id"] == "883514/1/101"
    assert report["states"][0]["latest_observed_status"] == "http_error"


def test_restoration_compares_previous_healthy_not_intermediate_failure(tmp_path):
    healthy = save_job(tmp_path, release_row("883514/1/101", [event("old")]), 1)
    fail = save_job(tmp_path, release_row(
        "883514/1/102", [event("fake")], sha="", status="http_error"
    ), 2)
    restored = save_job(tmp_path, release_row(
        "883514/1/103", [event("recent", date="2026-10-31"), event("old")],
        sha="real", fetched="2026-10-31T12:00:00Z",
    ), 3)
    report = evaluate(restored, [healthy, fail])
    assert {x["change_type"] for x in report["changes"]} == {
        "source_restored", "new_event_candidate",
    }
    assert report["states"][0]["latest_healthy_job_id"] == "883514/1/103"


def test_backfilled_old_date_is_not_announced_as_new_publication(tmp_path):
    before = save_job(tmp_path, release_row("883514/1/101", [event("old")]), 1)
    after = save_job(tmp_path, release_row(
        "883514/1/102", [event("archival", date="2024-01-10"),
                         event("old")], sha="changed",
    ), 2)
    result = evaluate(after, [before])
    assert [x["change_type"] for x in result["changes"]] == ["backfilled_event"]


def test_same_event_changed_body_is_edit_not_new_release(tmp_path):
    old = save_job(tmp_path, release_row("883514/1/101", [event("a")]), 1)
    new = save_job(tmp_path, release_row(
        "883514/1/102", [event("a", body="changed-body")], sha="changed",
    ), 2)
    result = evaluate(new, [old])
    assert [x["change_type"] for x in result["changes"]] == ["edited_event"]


def test_missing_date_is_unverified_review_only(tmp_path):
    old = save_job(tmp_path, release_row("883514/1/101", [event("a")]), 1)
    new = save_job(tmp_path, release_row(
        "883514/1/102", [event("unknown", date=None), event("a")],
        sha="changed",
    ), 2)
    result = evaluate(new, [old])
    assert [x["change_type"] for x in result["changes"]] == ["needs_review"]
    assert result["changes"][0]["reason"] == "date_missing_or_unknown"


def test_schema_migration_reset_baseline_without_price_release_alert(tmp_path):
    before_row = release_row("883514/1/101", [event("a")])
    before_row["release_events_schema"] = "1.0"
    before = save_job(tmp_path, before_row, 1)
    after = save_job(tmp_path, release_row(
        "883514/1/102", [event("new")], sha="new"
    ), 2)
    assert [x["change_type"] for x in evaluate(after, [before])["changes"]] == [
        "source_migrated"
    ]


def test_url_product_scope_mismatch_resets_baseline(tmp_path):
    before = save_job(tmp_path, docs_row(
        "883514/1/101", [doc_section("a", "one")]
    ), 1)
    after_row = docs_row("883514/1/102", [doc_section("a", "two")], sha="new")
    after_row["documentation_product_scope"] = "Different API Product"
    after = save_job(tmp_path, after_row, 2)
    assert [x["change_type"] for x in evaluate(after, [before])["changes"]] == [
        "source_migrated"
    ]


def test_price_change_only_exact_same_model_region_tier_unit(tmp_path):
    old = save_job(tmp_path, pricing_row("883514/1/101", [
        priced("1.50"), priced("2.00", region="US East", observation_id="other")
    ]), 1)
    new = save_job(tmp_path, pricing_row("883514/1/102", [
        priced("2.50"), priced("0.50", region="Europe", observation_id="third")
    ], sha="price-changed"), 2)
    changes = evaluate(new, [old])["changes"]
    assert {x["change_type"] for x in changes} == {
        "rate_change_candidate", "rate_first_seen_candidate",
    }
    change = next(x for x in changes if x["change_type"] == "rate_change_candidate")
    assert change["prior_value"] == "1.50"
    assert change["current_value"] == "2.50"
    assert change["rate_dimensions"]["region"] == "Global"
    assert change["approved_for_advisor"] is False


def test_amount_format_change_same_decimal_is_not_price_increase(tmp_path):
    old = save_job(tmp_path, pricing_row("883514/1/101", [priced("1.50")]), 1)
    new = save_job(tmp_path, pricing_row(
        "883514/1/102", [priced("1.5000")], sha="formatted"
    ), 2)
    assert evaluate(new, [old])["changes"] == []


def test_ambiguous_currency_or_table_loss_blocks_price_comparison(tmp_path):
    old = save_job(tmp_path, pricing_row("883514/1/101", [priced("1.50")]), 1)
    new_row = pricing_row("883514/1/102", [priced("3.50")], sha="")
    new_row["pricing_inventory_complete"] = False
    new = save_job(tmp_path, new_row, 2)
    assert [x["change_type"] for x in evaluate(new, [old])["changes"]] == [
        "source_unavailable"
    ]


def test_docs_semantic_section_change_ignores_template_order(tmp_path):
    first = save_job(tmp_path, docs_row(
        "883514/1/101", [
            doc_section("old", "same"), doc_section("change", "before"),
        ]
    ), 1)
    second = save_job(tmp_path, docs_row(
        "883514/1/102", [
            doc_section("change", "after"), doc_section("old", "same"),
        ], sha="template-update"
    ), 2)
    changes = evaluate(second, [first])["changes"]
    assert [x["change_type"] for x in changes] == ["docs_section_changed"]
    assert changes[0]["section_change_kind"] == "modified"


def test_missing_old_section_never_claims_deleted_feature(tmp_path):
    first = save_job(tmp_path, docs_row(
        "883514/1/101", [
            doc_section("one", "one"), doc_section("two", "two"),
        ]
    ), 1)
    second = save_job(tmp_path, docs_row(
        "883514/1/102", [doc_section("one", "one")], sha="changed"
    ), 2)
    assert evaluate(second, [first])["changes"] == []


def test_write_all_six_unverified_outputs_and_stable_replay(tmp_path):
    path = save_job(tmp_path, release_row(
        "883514/1/101", [event("a")]
    ), 1)
    res = evaluate(path)
    out = tmp_path / "reports"
    report = write_evaluation(res, out)
    assert report["all_results_unverified"] is True
    for name in (
        "status.csv", "changes.csv", "release_events.jsonl",
        "pricing_observations.jsonl", "review_queue.jsonl", "run_quality.json",
        "latest_state.jsonl",
    ):
        assert (out / name).exists(), name
    first = (out / "run_quality.json").read_bytes()
    write_evaluation(evaluate(path), out)
    assert (out / "run_quality.json").read_bytes() == first


def test_identical_current_archive_in_history_does_not_diff_against_itself(tmp_path):
    current = save_job(tmp_path, release_row("883514/1/101", [event("a")]), 1)
    result = evaluate(current, [current])
    assert [x["change_type"] for x in result["changes"]] == ["historical_baseline"]


def test_future_history_rejected_to_prevent_inverted_time_comparison(tmp_path):
    earlier = save_job(tmp_path, release_row("883514/1/101", [event("a")]), 1)
    future = save_job(tmp_path, release_row(
        "883514/1/102", [event("a")], sha="other"
    ), 2)
    with pytest.raises(ValueError, match="must precede"):
        evaluate(earlier, [future])
