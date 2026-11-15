"""G2 operator handoff tests. No credentials, HTTP calls or Zyte jobs."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from agentfuse_crawlers.validation_access import digest
from scripts import p23e1_zyte_queue_preflight as queue
from scripts import g2_redact_zyte_snapshot as g2

PROJECT = "883514"
NOW = datetime(2026, 11, 15, 13, tzinfo=timezone.utc)


def fake_snapshot(*, schedule_total=None, pending_total=None):
    calls = []

    def fetch(url, key, limit):
        calls.append((url, key, limit))
        if url == queue._periodic_url(PROJECT):
            row = {
                "id": 4, "project": int(PROJECT), "disabled": False,
                "type": "spider", "cron": "0 9 * * 1",
                "tasks": [{"name": "official_documentation", "spider_args": {
                    "secret": "PRIVATE_SCHEDULE_ARG_MUST_NOT_EXPORT",
                }}],
                "unknown": "PRIVATE_SCHEDULE_EXTRA_MUST_NOT_EXPORT",
            }
            return json.dumps({
                "count": 1 if schedule_total is None else schedule_total,
                "next": (None if schedule_total is None else "https://not-followed.example"),
                "previous": None, "results": [row],
                "raw_secret": "PRIVATE_NOT_EXPORTED",
            }).encode()
        q = parse_qs(urlsplit(url).query)
        assert q["project"] == [PROJECT]
        assert q["count"] == [str(queue.MAX_JOBS)]
        state = q["state"][0]
        rows = [{
            "id": f"{PROJECT}/1/99",
            "state": "pending",
            "spider": "official_pricing",
            "version": "historic-version-NOT-REMOTE-EGG-PROOF",
            "started_time": "2026-11-15T11:00:00",
            "updated_time": "2026-11-15T11:01:00",
            "spider_args": {"api_key": "SENSITIVE_NOT_FOR_ARTIFACT"},
        }] if state == "pending" else []
        return json.dumps({
            "status": "ok", "count": len(rows),
            "total": len(rows) if pending_total is None or state != "pending"
            else pending_total,
            "jobs": rows, "secret": "SENSITIVE_TOP_LEVEL",
        }).encode()

    raw = queue.build_preflight(
        PROJECT, api_key="SYNTHETIC_NO_NETWORK", fetch=fetch, now=NOW,
    )
    return raw, calls


def test_redacts_true_readonly_account_snapshot_without_claiming_remote_verification():
    raw, calls = fake_snapshot()
    assert len(calls) == 3
    assert all(key == "SYNTHETIC_NO_NETWORK" for _, key, _ in calls)
    summary = g2.redact(raw)
    assert summary["project_id"] == PROJECT
    assert summary["status"] == "NO_GO_REAL_ACCOUNT_EVIDENCE_INCOMPLETE"
    assert summary["requests_to_zyte_read_only_api"] == 3
    assert summary["new_zyte_jobs"] == summary["publisher_requests"] == 0
    assert summary["pending_jobs_visible"] == 1
    assert summary["running_jobs_visible"] == 0
    assert summary["enabled_periodic_schedules_visible"] == 1
    assert summary["queue_pages_complete"] is True
    assert summary["periodic_schedule_page_complete"] is True
    for attr in (
        "remote_deployed_egg_independently_verified",
        "billing_and_spend_ceiling_independently_verified",
        "source_permissions_verified", "approved_to_run",
        "no_future_jobs_guaranteed",
    ):
        assert summary[attr] is False
    serialized = json.dumps(summary)
    for secret in (
        "PRIVATE_SCHEDULE_ARG_MUST_NOT_EXPORT",
        "PRIVATE_SCHEDULE_EXTRA_MUST_NOT_EXPORT",
        "SENSITIVE_NOT_FOR_ARTIFACT", "SENSITIVE_TOP_LEVEL",
        "historic-version-NOT-REMOTE-EGG-PROOF",
        f"{PROJECT}/1/99", "official_pricing",
    ):
        assert secret not in serialized


def test_incomplete_pages_are_visible_not_a_false_empty_or_authorization():
    raw, _ = fake_snapshot(schedule_total=3, pending_total=4)
    summary = g2.redact(raw)
    assert summary["queue_pages_complete"] is False
    assert summary["periodic_schedule_page_complete"] is False
    assert summary["pending_jobs_visible"] == 1
    assert summary["pending_jobs_reported_total"] == 4
    assert summary["periodic_schedules_reported_total"] == 3
    assert summary["enabled_periodic_schedules_visible"] == 1
    assert summary["approved_to_run"] is False


@pytest.mark.parametrize("field,value", [
    ("readiness_to_run", True),
    ("remote_current_deployed_egg_independently_verified", True),
    ("current_zyte_billing_terms_independently_verified", True),
    ("incremental_spend_ceiling_approved_by_operator", True),
    ("periodic_schedules_independently_checked", True),
    ("live_two_round_cross_category_gold_independently_verified", True),
    ("new_jobs_created_or_modified", 1),
    ("publisher_requests_performed", 1),
    ("publisher_permissions_granted", 1),
    ("p23e_bounded_plans_authorized_by_this_report", 1),
    ("only_three_zyte_api_gets", False),
    ("active_queue_snapshot_non_atomic", False),
    ("queue_list_single_pages_complete", "yes"),
    ("pending_jobs_visible", True),
    ("periodic_schedules_reported_total", -1),
    ("snapshot_at_utc", "not-a-time"),
    ("status", "GO"),
    ("kind", "unexpected"),
])
def test_redaction_refuses_authorizing_or_inconsistent_p23e1_report(field, value):
    original, _ = fake_snapshot()
    modified = deepcopy(original)
    modified[field] = value
    modified["report_sha256"] = digest({
        key: val for key, val in modified.items() if key != "report_sha256"
    })
    with pytest.raises(ValueError):
        g2.redact(modified)


def test_digest_tamper_and_complete_page_lie_fail_closed():
    original, _ = fake_snapshot()
    modified = deepcopy(original)
    modified["pending_jobs_visible"] = 12
    with pytest.raises(ValueError, match="digest"):
        g2.redact(modified)
    modified["report_sha256"] = digest({
        k: v for k, v in modified.items() if k != "report_sha256"
    })
    with pytest.raises(ValueError):
        g2.redact(modified)


def test_no_overwrite_private_summary_and_content_allowlist(tmp_path):
    raw, _ = fake_snapshot()
    data = g2.redact(raw)
    dest = tmp_path / "g2-summary"
    path = g2.write_summary(data, dest)
    assert path == dest / g2.OUTPUT_FILE
    saved = json.loads(path.read_text())
    assert saved == data
    assert set(saved) == {
        "schema_version", "kind", "status", "project_id", "snapshot_at_utc",
        "source_p23e1_report_sha256_NOT_APPROVAL",
        "requests_to_zyte_read_only_api", "new_zyte_jobs", "publisher_requests",
        "approved_to_run", "source_permissions_verified",
        "remote_deployed_egg_independently_verified",
        "billing_and_spend_ceiling_independently_verified",
        "read_only_queue_observation_non_atomic", "queue_pages_complete",
        "pending_jobs_visible", "running_jobs_visible",
        "pending_jobs_reported_total", "running_jobs_reported_total",
        "periodic_schedule_page_complete", "periodic_schedules_reported_total",
        "enabled_periodic_schedules_visible",
        "disabled_periodic_schedules_visible", "no_future_jobs_guaranteed",
        "raw_job_ids_or_schedule_arguments_exported", "next_operator_action",
        "report_sha256",
    }
    with pytest.raises(ValueError, match="NEW non-symlink"):
        g2.write_summary(data, dest)
    bad = deepcopy(data)
    bad["approved_to_run"] = True
    bad["report_sha256"] = digest({
        k: v for k, v in bad.items() if k != "report_sha256"
    })
    with pytest.raises(ValueError):
        g2.write_summary(bad, tmp_path / "bad")


def test_g2_workflow_is_manual_only_and_never_uploads_raw_p23e1_report():
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/manual-g2-zyte-readonly-account.yml").read_text()
    assert "\n  workflow_dispatch:\n" in workflow
    assert "\n  push:" not in workflow
    assert "\n  pull_request:" not in workflow
    assert "contents: read" in workflow
    assert "secrets.ZYTE_SCRAPY_CLOUD_API_KEY" in workflow
    assert "python -m scripts.p23e1_zyte_queue_preflight" in workflow
    assert "python -m scripts.g2_redact_zyte_snapshot" in workflow
    assert "output/private/g2-summary-only/g2_zyte_redacted_snapshot_NO_GO.json" in workflow
    assert "path: output/private/g2-summary-only/" in workflow
    assert "path: output/private/g2-raw-LOCAL_ONLY" not in workflow
    for danger in ("api/run.json", "shub deploy", "api/stop.json", "confirm_full_inventory=yes"):
        assert danger not in workflow
