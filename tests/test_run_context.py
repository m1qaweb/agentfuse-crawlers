"""PR01: deterministic fingerprints, run identity and intentional scope."""

from datetime import datetime, timezone

import pytest

from agentfuse_crawlers.run_context import (
    build_run_context, manifest_sha256, selection_ids_sha256,
)
from agentfuse_crawlers.sources import load_sources, select_sources
from agentfuse_crawlers.spiders.official import ChangelogSpider


def test_source_registry_hash_changes_when_url_or_order_changes():
    sources = load_sources()
    baseline = manifest_sha256(sources)
    assert len(baseline) == 64
    assert manifest_sha256(sources) == baseline
    changed_url = [dict(x) for x in sources]
    changed_url[0]["url"] += "/new-documentation"
    assert manifest_sha256(changed_url) != baseline
    reordered = list(reversed(sources))
    assert manifest_sha256(reordered) != baseline


def test_selected_id_hash_is_order_sensitive_and_stable():
    batch = select_sources("changelog", cohort="proven")
    assert len(selection_ids_sha256(batch)) == 64
    assert selection_ids_sha256(batch) == selection_ids_sha256(batch)
    assert selection_ids_sha256(batch[::-1]) != selection_ids_sha256(batch)


def test_recorded_job_metadata_requires_real_identifiers():
    batch = select_sources("changelog", cohort="proven")
    fixed_time = datetime(2026, 10, 31, 11, 0, tzinfo=timezone.utc)
    result = build_run_context(
        "official_changelogs", "proven", batch, started_at=fixed_time,
        job_id="883514/1/100", revision="123456abcdef",
    )
    assert result["run_started_at_utc"] == "2026-10-31T11:00:00+00:00"
    assert result["zyte_job_id"] == "883514/1/100"
    assert result["deployment_revision"] == "123456abcdef"
    assert result["requested_cohort"] == "proven"
    assert result["run_scope_explicit"] is False


def test_invalid_job_or_revision_are_not_claimed_as_real_provenance():
    batch = select_sources("documentation", cohort="proven")
    result = build_run_context(
        "official_documentation", "proven", batch,
        job_id="apikey=secret", revision="wrong revision",
    )
    assert result["zyte_job_id"] == ""
    assert result["deployment_revision"] == ""


def test_naive_started_at_rejected():
    batch = select_sources("pricing", cohort="proven")
    with pytest.raises(ValueError, match="timezone-aware"):
        build_run_context(
            "official_pricing", "proven", batch,
            started_at=datetime(2026, 10, 31, 11, 0),
        )


def test_plan_pinned_explicit_source_ids_even_if_cohort_membership_changes():
    from scripts.plan_validation import plan_validation
    plan = plan_validation(batch_size=15)
    first = plan["batches"][0]
    spider = ChangelogSpider(
        cohort=first["pinned_cohort"],
        source_ids=first["source_ids_csv"],
        expected_manifest_sha256=first["expected_manifest_sha256"],
        expected_selection_ids_sha256=first["expected_selection_ids_sha256"],
    )
    assert spider.run_context["selection_source_count"] == first["requested_count"]
    assert spider.run_context["requested_cohort"] == "all"


def test_wrong_pinned_manifest_or_selection_fails_before_first_request():
    from scripts.plan_validation import plan_validation
    first = plan_validation(batch_size=15)["batches"][0]
    args = {
        "cohort": first["pinned_cohort"],
        "source_ids": first["source_ids_csv"],
        "expected_manifest_sha256": first["expected_manifest_sha256"],
        "expected_selection_ids_sha256": first["expected_selection_ids_sha256"],
    }
    with pytest.raises(ValueError, match="manifest_sha256"):
        ChangelogSpider(**{**args, "expected_manifest_sha256": "0" * 64})
    with pytest.raises(ValueError, match="selection_ids_sha256"):
        ChangelogSpider(**{**args, "expected_selection_ids_sha256": "0" * 64})
