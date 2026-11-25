"""Offline activation/expiry boundary tests; all reviews are fictional."""
from datetime import datetime, timedelta, timezone

import pytest

from agentfuse_crawlers import validation_access as policy

NOW = datetime(2026, 11, 25, 9, tzinfo=timezone.utc)
SOURCES = [
    {"id": "synthetic_alpha", "provider": "Synthetic Alpha",
     "category": "documentation", "url": "https://alpha.invalid/docs"},
    {"id": "synthetic_beta", "provider": "Synthetic Beta",
     "category": "documentation", "url": "https://beta.invalid/docs"},
]
PKG = "a" * 64
MANIFEST = "b" * 64
LIFECYCLE = "c" * 64
PLAN_ID = "synthetic_effective_window"


@pytest.fixture(autouse=True)
def isolated_policy(monkeypatch):
    monkeypatch.setattr(policy, "load_sources", lambda: SOURCES)
    monkeypatch.setattr(policy, "collection_decision", lambda *a, **k: (True, "synthetic"))
    monkeypatch.setattr(policy, "manifest_sha256", lambda: MANIFEST)
    monkeypatch.setattr(policy, "registry_revision_sha256", lambda: LIFECYCLE)
    monkeypatch.setattr(policy, "selection_ids_sha256",
                        lambda rows: policy.digest([r["id"] for r in rows]))


def timestamp(seconds):
    return (NOW + timedelta(seconds=seconds)).isoformat()


def access(*, start=-60, end=3600):
    src = SOURCES[0]
    return {
        "schema_version": policy.SCHEMA, "kind": policy.ACCESS_KIND,
        "default_decision": "not_reviewed", "reviews": {src["id"]: {
            "source_url": src["url"], "category": src["category"],
            "decision": "allowed_reviewed", "scopes": ["single_validation", "bulk_validation"],
            "reviewed_by": "Synthetic Test Reviewer",
            "reviewed_at_utc": timestamp(start), "expires_at_utc": timestamp(end),
            "ownership_evidence_url": src["url"],
            "publisher_access_policy_url": "https://alpha.invalid/terms",
            "robots_url": "https://alpha.invalid/robots.txt",
            "publisher_terms_reviewed": True, "robots_reviewed": True,
            "private_retention_reviewed": True,
            "evidence_note": "Synthetic test fixture only. This fictional record does not establish actual publisher permission or any real retention rights.",
        }},
    }


def plans(registry, *, start=-60, end=3600):
    return {"schema_version": policy.SCHEMA, "kind": policy.PLAN_KIND,
            "default_policy": "no_bulk_runs_authorized", "plans": {PLAN_ID: {
                "category": "documentation", "collection_mode": "validation", "cohort": "all",
                "source_ids": [s["id"] for s in SOURCES],
                "authorized_source_ids": [SOURCES[0]["id"]],
                "manifest_sha256": MANIFEST, "source_registry_sha256": LIFECYCLE,
                "access_registry_sha256": policy.digest(registry),
                "selection_ids_sha256": policy.selection_ids_sha256(SOURCES),
                "source_urls_sha256": policy._urls_digest(SOURCES),
                "approved_by": "Synthetic Test Reviewer", "reviewed_at_utc": timestamp(start),
                "expires_at_utc": timestamp(end), "max_primary_requests": 1,
                "max_redirects_per_source": 0, "purpose": "bounded_human_supervised_diagnostic",
                "publisher_policy_review_attested": True,
            }}}


def authorize(registry, run_plans, *, now=NOW):
    return policy.authorize_bulk_run(
        selected=SOURCES, category="documentation", cohort="all", collection_mode="validation",
        plan_id=PLAN_ID, expected_plan_sha256=policy.digest(run_plans["plans"][PLAN_ID]),
        expected_package_sha256=PKG, current_package_sha256=PKG,
        access_registry=registry, run_plans=run_plans, now=now,
    )


@pytest.mark.parametrize("scope", ["single_validation", "bulk_validation"])
@pytest.mark.parametrize("offset", [1, 60, 300])
def test_source_clock_skew_is_not_early_authorization(scope, offset):
    registry = access(start=offset)
    assert policy.validate_access_registry(registry, now=NOW) is registry
    allowed, reason = policy.validation_access_decision(SOURCES[0], scope=scope, registry=registry, now=NOW)
    assert not allowed
    assert reason.endswith("_policy_review_not_yet_effective")
    assert policy.validation_access_decision(SOURCES[0], scope=scope, registry=registry,
                                            now=NOW + timedelta(seconds=offset))[0]


@pytest.mark.parametrize("scope", ["single_validation", "bulk_validation"])
def test_source_review_is_inclusive_at_start_exclusive_at_expiry(scope):
    registry = access(start=0, end=60)
    assert policy.validation_access_decision(SOURCES[0], scope=scope, registry=registry, now=NOW)[0]
    assert policy.validation_access_decision(SOURCES[0], scope=scope, registry=registry,
                                            now=NOW + timedelta(seconds=59))[0]
    allowed, reason = policy.validation_access_decision(SOURCES[0], scope=scope, registry=registry,
                                                         now=NOW + timedelta(seconds=60))
    assert not allowed and reason.endswith("_policy_review_expired")


@pytest.mark.parametrize("offset", [1, 60, 300])
def test_future_plan_cannot_authorize_during_schema_clock_tolerance(offset):
    registry = access()
    run_plans = plans(registry, start=offset)
    assert policy.validate_plan_registry(run_plans, now=NOW) is run_plans
    with pytest.raises(ValueError, match="Bulk authorization not yet effective"):
        authorize(registry, run_plans)
    result = authorize(registry, run_plans, now=NOW + timedelta(seconds=offset))
    assert result["authorized_source_ids"] == {SOURCES[0]["id"]}


def test_current_plan_cannot_authorize_a_future_source_review():
    registry = access(start=60)
    run_plans = plans(registry)
    with pytest.raises(ValueError, match="bulk_source_policy_review_not_yet_effective"):
        authorize(registry, run_plans)


def test_plan_start_and_expiry_boundaries():
    registry = access()
    run_plans = plans(registry, start=0, end=60)
    assert authorize(registry, run_plans)["max_primary_requests"] == 1
    with pytest.raises(ValueError, match="Bulk authorization expired"):
        authorize(registry, run_plans, now=NOW + timedelta(seconds=60))


def test_future_outside_schema_tolerance_remains_invalid():
    registry = access(start=301)
    with pytest.raises(ValueError, match="future evaluation"):
        policy.validate_access_registry(registry, now=NOW)
    registry = access()
    with pytest.raises(ValueError, match="Invalid bulk plan review time"):
        policy.validate_plan_registry(plans(registry, start=301), now=NOW)
