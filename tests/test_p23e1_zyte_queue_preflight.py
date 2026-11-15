"""P23E1 queue snapshot tests: all Zyte responses are invented in memory.

No requests, changes, jobs, publisher pages or credential usage.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import urllib.parse

import pytest

from scripts import p23e1_zyte_queue_preflight as p

NOW = datetime(2026, 11, 13, 18, tzinfo=timezone.utc)
PROJECT = "883514"


def payload(state, jobs=(), *, total=None, **changes):
    rows = [
        {"id": f"{PROJECT}/1/{i+1}", "state": state,
         "spider": "official_documentation",
         "version": "synthetic-unverified-version",
         "started_time": "2026-11-13T12:00:00",
         "updated_time": "2026-11-13T12:01:00"}
        for i, _ in enumerate(jobs)
    ]
    blob = {"status": "ok", "count": len(rows),
            "total": len(rows) if total is None else total, "jobs": rows}
    blob.update(changes)
    return json.dumps(blob).encode("utf-8")


def periodic_payload(disabled=(), *, total=None, next_url=None):
    rows = [{
        "id": 10 + index, "disabled": is_disabled, "project": int(PROJECT),
        "type": "spider", "cron": "0 9 * * 1",
        "description": "PRIVATE_DO_NOT_RETAIN",
        "tasks": [{
            "name": "official_documentation",
            "spider_args": {"api_key": "PRIVATE_SPIDER_ARG_NEVER_RETAIN"},
            "script_args": "PRIVATE_SCRIPT_ARG_NEVER_RETAIN",
        }],
        "extra_secret": "PRIVATE_UNKNOWN_FIELD_NEVER_RETAIN",
    } for index, is_disabled in enumerate(disabled)]
    return json.dumps({
        "count": len(rows) if total is None else total,
        "next": next_url, "previous": None,
        "results": rows, "meta": {"hint": "PRIVATE_META_NEVER_RETAIN"},
    }).encode("utf-8")


def fake_api(pending=(), running=(), *, pending_total=None,
             running_total=None, schedules=(), schedules_total=None,
             schedules_next=None):
    called = []

    def get(url, key, limit):
        called.append((url, key, limit))
        if url == p._periodic_url(PROJECT):
            return periodic_payload(
                schedules, total=schedules_total, next_url=schedules_next
            )
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        assert url.startswith("https://app.zyte.com/api/jobs/list.json?")
        assert qs["project"] == [PROJECT]
        assert qs["count"] == [str(p.MAX_JOBS)]
        state = qs["state"][0]
        if state == "pending":
            return payload(state, pending, total=pending_total)
        assert state == "running"
        return payload(state, running, total=running_total)

    return get, called


def test_clean_queue_never_promotes_to_approval():
    fetch, calls = fake_api()
    report = p.build_preflight(PROJECT, fetch=fetch, api_key="SYNTHETIC", now=NOW)
    assert [urllib.parse.parse_qs(
        urllib.parse.urlsplit(x[0]).query)["state"][0] for x in calls[:2]
    ] == ["pending", "running"]
    assert len(calls) == 3
    assert calls[2][0] == p._periodic_url(PROJECT)
    assert all(x[1] == "SYNTHETIC" and x[2] == p.MAX_BYTES for x in calls)
    assert report["no_pending_or_running_jobs_observed"] is True
    assert report["queue_list_single_pages_complete"] is True
    assert report["pending_jobs_visible"] == 0
    assert report["running_jobs_visible"] == 0
    assert report["periodic_schedule_list_complete"] is True
    assert report["no_enabled_periodic_schedules_observed"] is True
    assert report["enabled_periodic_schedules_visible"] == 0
    assert report["only_three_zyte_api_gets"] is True
    assert report["remote_current_deployed_egg_independently_verified"] is False
    assert report["current_zyte_billing_terms_independently_verified"] is False
    assert report["incremental_spend_ceiling_approved_by_operator"] is False
    assert report["periodic_schedules_independently_checked"] is False
    assert report["readiness_to_run"] is False
    assert report["p23e_bounded_plans_authorized_by_this_report"] == 0
    assert report["new_jobs_created_or_modified"] == 0
    assert report["publisher_requests_performed"] == 0
    assert report["report_sha256"] == p.digest({
        k: v for k, v in report.items() if k != "report_sha256"
    })


def test_active_jobs_remain_visible_without_assuming_authorization():
    fetch, called = fake_api(pending=(1,), running=(1,))
    # Use different job IDs across states as actual Zyte API would.
    def get(url, key, limit):
        raw = json.loads(fetch(url, key, limit))
        if "state=running" in url:
            raw["jobs"][0]["id"] = f"{PROJECT}/3/28"
        return json.dumps(raw).encode("utf-8")

    report = p.build_preflight(PROJECT, fetch=get, api_key="SYNTHETIC", now=NOW)
    assert len(called) == 3
    assert report["no_pending_or_running_jobs_observed"] is False
    assert report["pending_jobs_visible"] == 1
    assert report["running_jobs_visible"] == 1
    assert report["job_list_pages"]["running"]["jobs"][0]["id"] == f"{PROJECT}/3/28"
    assert report["readiness_to_run"] is False


def test_truncated_queue_list_is_not_false_empty():
    fetch, _ = fake_api(pending_total=2)
    report = p.build_preflight(PROJECT, fetch=fetch, api_key="SYNTHETIC", now=NOW)
    assert report["pending_jobs_visible"] == 0
    assert report["pending_jobs_reported_total"] == 2
    assert report["queue_list_single_pages_complete"] is False
    assert report["no_pending_or_running_jobs_observed"] is False
    assert report["readiness_to_run"] is False


@pytest.mark.parametrize("field,new_value", [
    ("status", "error"),
    ("count", True),
    ("count", 1),
    ("total", -1),
    ("jobs", "invalid"),
])
def test_invalid_api_envelope_fails_closed(field, new_value):
    data = json.loads(payload("pending"))
    data[field] = new_value
    with pytest.raises(ValueError):
        p._parse_list(json.dumps(data).encode(), PROJECT, "pending")


@pytest.mark.parametrize("mutation", [
    "bad_project", "wrong_state", "duplicate", "empty_spider",
    "invalid_version", "nested_secret",
])
def test_unexpected_job_records_rejected_or_sanitized(mutation):
    row = {"id": f"{PROJECT}/1/5", "state": "running",
           "spider": "official_documentation", "version": "v1",
           "started_time": "2026-11-13T12:00:00"}
    if mutation == "bad_project":
        row["id"] = "999999/1/5"
    elif mutation == "wrong_state":
        row["state"] = "pending"
    elif mutation == "empty_spider":
        row["spider"] = None
    elif mutation == "invalid_version":
        row["version"] = "\nprivate"
    elif mutation == "nested_secret":
        row["untrusted_custom_api_token"] = "not-to-be-exported"
    body = {"status": "ok", "count": 1, "total": 1, "jobs": [row]}
    if mutation == "duplicate":
        body["jobs"] = [row, deepcopy(row)]
        body["count"] = body["total"] = 2
    raw = json.dumps(body).encode("utf-8")
    if mutation == "nested_secret":
        result = p._parse_list(raw, PROJECT, "running")
        assert "not-to-be-exported" not in json.dumps(result)
        assert result["jobs"][0]["spider"] == "official_documentation"
    else:
        with pytest.raises(ValueError):
            p._parse_list(raw, PROJECT, "running")


def test_duplicate_json_keys_are_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        p._parse_list(b'{"status":"ok","status":"error","count":0,"total":0,"jobs":[]}',
                      PROJECT, "pending")


@pytest.mark.parametrize("bad", [
    "0", "-1", "883514?state=running", "not-a-project",
    "https://app.zyte.com/api/run.json", "00001", "",
])
def test_bad_project_cannot_generate_api_url(bad):
    with pytest.raises(ValueError):
        p._url(bad, "pending")


@pytest.mark.parametrize("url", [
    "https://app.zyte.com/api/run.json?project=883514",
    "https://evil.invalid/api/jobs/list.json?project=883514&state=pending&count=200",
    "http://app.zyte.com/api/jobs/list.json?project=883514&state=pending&count=200",
    "https://app.zyte.com/api/jobs/list.json?project=883514&state=finished&count=200",
    "https://app.zyte.com/api/jobs/list.json?project=883514&state=running&count=100",
    "https://app.zyte.com/api/jobs/list.json?project=883514&state=running&count=200&apikey=SECRET",
    "https://app.zyte.com/api/projects/883514/periodicjobs?token=SECRET",
    "https://app.zyte.com/api/projects/883514/periodicjobs/7",
    "https://app.zyte.com/api/projects/883514/periodicjobs?page=2",
    "https://evil.invalid/api/projects/883514/periodicjobs",
    "http://app.zyte.com/api/projects/883514/periodicjobs",
])
def test_http_method_endpoint_allowlist_rejects_unsafe_urls_before_network(url):
    with pytest.raises(ValueError):
        p._read_only_get(url, "SYNTHETIC", p.MAX_BYTES)


def test_missing_real_credential_refused_before_attempt(monkeypatch):
    monkeypatch.delenv(p.API_KEY_VAR, raising=False)
    with pytest.raises(ValueError, match="ZYTE_SCRAPY_CLOUD_API_KEY"):
        p.build_preflight(PROJECT, now=NOW)


def test_api_error_cannot_write_partial_success(tmp_path):
    called = []
    def fail_on_running(url, key, limit):
        called.append(url)
        if "state=running" in url:
            raise TimeoutError("SYNTHETIC network failure")
        return payload("pending")
    out = tmp_path / "must-not-exist"
    with pytest.raises(TimeoutError):
        report = p.build_preflight(
            PROJECT, api_key="SYNTHETIC", fetch=fail_on_running, now=NOW
        )
        p.write_preflight(report, out)
    assert not out.exists()
    assert len(called) == 2


def test_private_new_only_report_is_unprivileged(tmp_path):
    fetch, _ = fake_api()
    report = p.build_preflight(PROJECT, api_key="SYNTHETIC", fetch=fetch, now=NOW)
    folder = tmp_path / "new-private"
    p.write_preflight(report, folder)
    data = json.loads((folder / "p23e1_zyte_readonly_queue_NO_GO.json").read_text())
    assert data == report
    txt = (folder / "OPERATOR_NEXT_STEPS_NOT_AUTHORIZED.txt").read_text()
    assert "NOT AN APPROVAL" in txt
    assert "SYNTHETIC" not in json.dumps(data)
    assert (folder.stat().st_mode & 0o777) == 0o700
    assert ((folder / "p23e1_zyte_readonly_queue_NO_GO.json").stat().st_mode & 0o777) == 0o600
    with pytest.raises((ValueError, FileExistsError)):
        p.write_preflight(report, folder)
    tampered = deepcopy(report)
    tampered["readiness_to_run"] = True
    with pytest.raises(ValueError):
        p.write_preflight(tampered, tmp_path / "tampered")
    assert not (tmp_path / "tampered").exists()


def test_queue_check_never_calls_job_mutation_api():
    for state in p.STATES:
        url = p._url(PROJECT, state)
        assert url.startswith("https://app.zyte.com/api/jobs/list.json?")
        assert "/run.json" not in url
        assert "/stop.json" not in url
        assert "/update.json" not in url
        assert "/delete.json" not in url



def test_active_and_paused_schedules_are_included_but_no_approval():
    fetch, calls = fake_api(schedules=(False, True))
    report = p.build_preflight(PROJECT, fetch=fetch, api_key="SYNTHETIC", now=NOW)
    assert len(calls) == 3
    assert report["periodic_schedule_list_complete"] is True
    assert report["periodic_schedules_reported_total"] == 2
    assert report["enabled_periodic_schedules_visible"] == 1
    assert report["disabled_periodic_schedules_visible"] == 1
    assert report["no_enabled_periodic_schedules_observed"] is False
    assert report["periodic_schedules_independently_checked"] is False
    assert report["readiness_to_run"] is False
    captured = json.dumps(report)
    for forbidden in ("PRIVATE_DO_NOT_RETAIN", "PRIVATE_SPIDER_ARG",
                      "PRIVATE_SCRIPT_ARG", "PRIVATE_UNKNOWN_FIELD",
                      "PRIVATE_META"):
        assert forbidden not in captured
    observed = report["periodic_schedule_api_page"]["schedules"]
    assert [x["id"] for x in observed] == [10, 11]
    assert all(x["task_arguments_REDACTED"] is True for x in observed)


@pytest.mark.parametrize("total,next_url", [
    (3, "https://app.zyte.com/api/projects/883514/periodicjobs?page=2"),
    (3, None),
    (1, "https://evil.invalid/steal?token=SECRET"),
])
def test_paginated_schedule_page_never_claims_all_schedules_visible(
        total, next_url):
    fetch, called = fake_api(schedules=(False,), schedules_total=total,
                             schedules_next=next_url)
    result = p.build_preflight(PROJECT, fetch=fetch, api_key="SYNTHETIC", now=NOW)
    assert len(called) == 3  # DO NOT follow vendor-controlled next links
    assert result["periodic_schedule_list_complete"] is False
    assert result["no_enabled_periodic_schedules_observed"] is False
    assert result["readiness_to_run"] is False
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("mutation", [
    "wrong_project", "wrong_type", "invalid_id", "duplicate_id",
    "wrong_disabled", "missing_tasks", "invalid_task", "missing_name",
    "bad_cron", "count_boolean", "negative_count", "malformed_next",
    "too_many_rows", "bad_root", "duplicate_json_keys",
])
def test_periodic_schedule_parser_fails_closed_on_untrusted_api(mutation):
    original = json.loads(periodic_payload((False,)))
    row = original["results"][0]
    if mutation == "wrong_project":
        row["project"] = 999999
    elif mutation == "wrong_type":
        row["type"] = "unknown"
    elif mutation == "invalid_id":
        row["id"] = True
    elif mutation == "duplicate_id":
        original["results"].append(dict(row))
        original["count"] = 2
    elif mutation == "wrong_disabled":
        row["disabled"] = "false"
    elif mutation == "missing_tasks":
        row["tasks"] = []
    elif mutation == "invalid_task":
        row["tasks"] = [0]
    elif mutation == "missing_name":
        row["tasks"] = [{"spider_args": {}}]
    elif mutation == "bad_cron":
        row["cron"] = "every minute"
    elif mutation == "count_boolean":
        original["count"] = True
    elif mutation == "negative_count":
        original["count"] = -1
    elif mutation == "malformed_next":
        original["next"] = ["https://example.invalid"]
    elif mutation == "too_many_rows":
        original["count"] = p.MAX_SCHEDULES + 1
        original["results"] = [dict(row, id=i + 1) for i in range(p.MAX_SCHEDULES + 1)]
    elif mutation == "bad_root":
        original = []
    else:
        with pytest.raises(ValueError, match="Duplicate JSON object keys"):
            p._parse_periodic(
                b'{"count":0,"count":1,"next":null,"previous":null,"results":[]}',
                PROJECT,
            )
        return
    with pytest.raises(ValueError):
        p._parse_periodic(json.dumps(original).encode(), PROJECT)


def test_periodic_schedule_read_failure_never_writes_partial_report(tmp_path):
    fetch, calls = fake_api()
    def no_schedule_available(url, key, limit):
        if url == p._periodic_url(PROJECT):
            raise ConnectionError("synthetic read-only endpoint unavailable")
        return fetch(url, key, limit)

    path = tmp_path / "must-not-exist"
    with pytest.raises(ConnectionError):
        report = p.build_preflight(
            PROJECT, fetch=no_schedule_available, api_key="SYNTHETIC", now=NOW
        )
        p.write_preflight(report, path)
    assert len(calls) == 2
    assert not path.exists()


def test_periodic_schedule_allowlist_only_get_url_without_queries():
    url = p._periodic_url(PROJECT)
    assert url == "https://app.zyte.com/api/projects/883514/periodicjobs"
    assert "/periodicjobs/" not in url
    assert "run.json" not in url
    assert "stop.json" not in url
    assert "update.json" not in url
    assert "delete.json" not in url
    for malicious in (
        url + "?page=2",
        url + "/3",
        url + "?api_key=leak",
        url.replace("https:", "http:"),
        url.replace("app.zyte.com", "untrusted.invalid"),
        "https://app.zyte.com/api/projects/883514/periodicjobs/",
    ):
        with pytest.raises(ValueError):
            p._read_only_get(malicious, "SYNTHETIC", p.MAX_BYTES)
