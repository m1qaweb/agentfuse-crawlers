"""P23C2 synthetic-only tests; no real publisher, Zyte or job access."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

import agentfuse_crawlers.validation_access as access
from agentfuse_crawlers.run_context import (
    manifest_sha256, package_fingerprint, selection_ids_sha256,
)
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
from scripts.accession_cross_category_html import (
    blank_ledger as blank_html_ledger, frozen_plan,
)
from scripts.archive_jobs import archive_job, archive_path
from scripts.p23c1_zyte_canary_archive_gate import blank_receipts
from scripts.p23c2_zyte_requests_logs_html_gate import (
    audit_evidence, blank_export_index, prepare, write_report,
)

NOW = datetime(2026, 11, 7, 11, 0, tzinfo=timezone.utc)
NOTE = (
    "SYNTHETIC TEST FIXTURE ONLY: no real publisher access approval. "
    "A human would need to check ownership, robots, terms, scope, "
    "exact source URL and private data retention before a request."
)


def at(delta=timedelta()):
    return (NOW + delta).isoformat(timespec="seconds")


def epoch(delta=timedelta()):
    return int((NOW + delta).timestamp() * 1000)


def chosen():
    return next(x for x in load_sources()
                if x["id"] == frozen_plan()["sources"][0]["source_id"])


def policy(source):
    host = source["url"].split("/")[2]
    obj = {
        "schema_version": access.SCHEMA, "kind": access.ACCESS_KIND,
        "default_decision": "not_reviewed",
        "reviews": {
            source["id"]: {
                "source_url": source["url"],
                "category": source["category"],
                "decision": "allowed_reviewed",
                "scopes": ["single_validation"],
                "reviewed_by": "Synthetic Only Reviewer",
                "reviewed_at_utc": at(timedelta(days=-2)),
                "expires_at_utc": at(timedelta(days=2)),
                "ownership_evidence_url": source["url"],
                "publisher_access_policy_url": "https://" + host + "/terms",
                "robots_url": "https://" + host + "/robots.txt",
                "publisher_terms_reviewed": True, "robots_reviewed": True,
                "private_retention_reviewed": True, "evidence_note": NOTE,
            },
        },
    }
    access.validate_access_registry(obj, now=NOW)
    return obj


def make_archive(root, source, pol, job_id="883514/1/1001", *,
                 http_status=200, status="captured", num_requests=2):
    args = {
        "cohort": "all", "source_ids": source["id"],
        "collection_mode": "validation",
        "expected_manifest_sha256": manifest_sha256(),
        "expected_selection_ids_sha256": selection_ids_sha256([source]),
        "expected_source_registry_sha256": registry_revision_sha256(),
    }
    item = {
        "_key": job_id + "/0", "source_id": source["id"],
        "source_url": source["url"], "provider": source["provider"],
        "category": source["category"],
        "spider_name": {
            "documentation": "official_documentation",
            "pricing": "official_pricing",
            "changelog": "official_changelogs",
        }[source["category"]],
        "collection_mode": "validation",
        "validation_scope": "single_exact_source",
        "single_validation_access_required": True,
        "bulk_validation_required": False,
        "run_scope_explicit": True, "selection_source_count": 1,
        "selection_ids_sha256": selection_ids_sha256([source]),
        "manifest_sha256": manifest_sha256(),
        "source_registry_sha256": registry_revision_sha256(),
        "bulk_access_registry_sha256":
            access.validation_access_revision_sha256(pol),
        "deployment_revision": package_fingerprint(),
        "zyte_job_id": job_id,
        "run_started_at_utc": at(timedelta(minutes=-35)),
        "http_status": http_status, "status": status,
        "final_url": source["url"] if http_status is not None else "",
        "approved_for_advisor": False,
    }

    def metadata(*_a):
        return {
            "state": "finished", "spider": item["spider_name"],
            "close_reason": (
                "finished" if http_status is not None
                else "agentfuse_no_usable_sources"
            ),
            "scrapystats": {
                "item_scraped_count": 1,
                "downloader/request_count": num_requests,
            },
            "spider_args": args,
        }

    archive_job(
        job_id, root, api_key="SYNTHETIC_ONLY",
        fetch_metadata=metadata,
        fetch_page=lambda *_a: [item],
    )
    return archive_path(root, job_id)


def make_raw(root, index, *, source, job_id, requests=None, logs=None):
    slot = index["rows"][0]["rounds"][0]
    slot["zyte_job_id"] = job_id
    jobdir = job_id.replace("/", "_")
    for kind, rows in (("requests", requests), ("logs", logs)):
        if rows is None:
            continue
        path = root / jobdir / (kind + ".jl")
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = "".join(json.dumps(row, separators=(",", ":")) + "\n"
                      for row in rows).encode("utf-8")
        path.write_bytes(raw)
        slot[kind] = {
            "file": jobdir + "/" + kind + ".jl",
            "sha256": hashlib.sha256(raw).hexdigest(),
        }


def primary(source, *, status=200, url=None, method="GET",
            time_offset=timedelta(minutes=-35, seconds=2)):
    return {
        "time": epoch(time_offset), "method": method,
        "url": source["url"] if url is None else url,
        "status": status, "duration": 22, "rs": 1450,
    }


def robots(source):
    from urllib.parse import urlsplit
    parsed = urlsplit(source["url"])
    url = parsed._replace(path="/robots.txt", query="", fragment="").geturl()
    return {
        "time": epoch(timedelta(minutes=-35, seconds=1)),
        "method": "GET", "url": url,
        "status": 200, "duration": 5, "rs": 123,
    }


def info_log():
    return {
        "time": epoch(timedelta(minutes=-35, seconds=4)),
        "level": 20, "message": "Synthetic crawl completed (not real)",
    }


def populated(tmp_path, *, requests=None, logs=None, status=200,
              item_status="captured", job="883514/1/1001",
              num_requests=2):
    source = chosen()
    pol = policy(source)
    c1, exports = blank_receipts(), blank_export_index()
    c1["rows"][0]["rounds"][0]["zyte_job_id"] = job
    archive_root = tmp_path / "archive"
    export_root = tmp_path / "exports"
    export_root.mkdir()
    make_archive(archive_root, source, pol, job,
                 http_status=status, status=item_status,
                 num_requests=num_requests)
    if requests is None:
        requests = [robots(source), primary(source, status=status)]
    if logs is None:
        logs = [info_log()]
    make_raw(export_root, exports, source=source, job_id=job,
             requests=requests, logs=logs)
    return c1, exports, archive_root, export_root, pol, source


def audit_tuple(args, **kwargs):
    c1, exports, archive_root, export_root, pol, _ = args
    return audit_evidence(
        c1, exports, archive_root, export_root,
        access_registry=pol, now=NOW, **kwargs,
    )


def test_blank_18_36_retains_all_holds_and_never_claims_permission(tmp_path):
    plan = frozen_plan()
    p23c2 = blank_export_index(plan)
    c1 = blank_receipts(plan)
    root = tmp_path / "archive"
    exp = tmp_path / "raw"
    root.mkdir()
    exp.mkdir()
    report, rows = audit_evidence(
        c1, p23c2, root, exp, now=NOW,
        access_registry={
            "schema_version": access.SCHEMA,
            "kind": access.ACCESS_KIND,
            "default_decision": "not_reviewed",
            "reviews": {},
        },
    )
    assert len(rows) == 36
    assert report["original_selected_sources"] == 18
    assert report["original_source_round_denominator"] == 36
    assert report["status"] == "NO_GO"
    assert report["source_rounds_with_items"] == 0
    assert report["source_rounds_with_requests_export"] == 0
    assert report["source_rounds_with_logs_export"] == 0
    assert report["source_rounds_with_independent_original_html_sha"] == 0
    assert report["full_460_source_diagnostic_approved"] is False
    assert report["new_network_requests"] == report["new_zyte_jobs"] == 0
    assert report["report_sha256"] == access.digest({
        k: v for k, v in report.items() if k != "report_sha256"
    })
    assert all(x["same_zyte_html_response_proven"] is False for x in rows)
    assert [x["source_id"] for x in p23c2["rows"]] == [
        x["source_id"] for x in c1["rows"]
    ]


def test_prepare_creates_only_blank_metadata_and_never_overwrites(tmp_path):
    out = tmp_path / "blank"
    assert prepare(out) == out
    index = json.loads(
        (out / "raw_requests_logs_receipt_index_BLANK.json").read_text()
    )
    assert index == blank_export_index()
    assert all(r["zyte_job_id"] is None
               and r["requests"] is None and r["logs"] is None
               for s in index["rows"] for r in s["rounds"])
    with pytest.raises((FileExistsError, ValueError, OSError)):
        prepare(out)


def test_valid_synthetic_jsonl_and_items_align_but_never_prove_original_html(tmp_path):
    args = populated(tmp_path)
    report, rows = audit_tuple(args)
    selected = rows[0]
    assert report["source_rounds_with_items"] == 1
    assert report["source_rounds_with_requests_export"] == 1
    assert report["source_rounds_with_logs_export"] == 1
    assert report["source_rounds_with_exact_primary_http_get"] == 1
    assert report["source_rounds_with_evidence_issues"] == 0
    assert selected["primary_get_count"] == 1
    assert selected["request_record_count"] == 2
    assert selected["primary_status_matches_item"] is True
    assert selected["request_count_matches_job_stats"] is True
    assert selected["source_round_evidence_state"] == (
        "requests_logs_consistent_HTML_NOT_SUPPLIED"
    )
    assert selected["same_zyte_html_response_proven"] is False
    assert selected["approved_for_advisor"] is False
    assert report["status"] == "NO_GO"
    assert report["requests_export_origin_cryptographically_authenticated"] is False
    assert report["raw_original_html_response_from_same_zyte_job_proven"] is False
    output = write_report(report, rows, tmp_path / "report")
    assert (output / "all_36_round_evidence.csv").is_file()
    assert "status" in (output / "zyte_original_evidence_36_rounds_NO_GO.json"
                        ).read_text()
    with pytest.raises((FileExistsError, ValueError, OSError)):
        write_report(report, rows, output)


@pytest.mark.parametrize("tamper", [
    "job_mismatch", "different_source", "reordered",
    "source_removed", "fake_permission", "path_traversal",
    "reused_raw", "orphan_export", "unknown_field",
])
def test_changed_receipt_denominators_and_path_aliases_are_rejected(
        tmp_path, tamper):
    args = list(populated(tmp_path))
    c1, index = args[:2]
    if tamper == "job_mismatch":
        index["rows"][0]["rounds"][0]["zyte_job_id"] = "883514/1/9999"
    elif tamper == "different_source":
        index["rows"][0]["source_id"] = "random_source"
    elif tamper == "reordered":
        index["rows"][0]["rounds"] = list(reversed(index["rows"][0]["rounds"]))
    elif tamper == "source_removed":
        index["rows"].pop()
    elif tamper == "fake_permission":
        index["approved_for_advisor"] = True
    elif tamper == "path_traversal":
        index["rows"][0]["rounds"][0]["requests"]["file"] = "../outside.jl"
    elif tamper == "reused_raw":
        index["rows"][0]["rounds"][0]["logs"]["file"] = (
            index["rows"][0]["rounds"][0]["requests"]["file"
            ]
        )
    elif tamper == "orphan_export":
        index["rows"][0]["rounds"][0]["zyte_job_id"] = None
    else:
        index["rows"][0]["rounds"][0]["requests"]["extra"] = "fake"
    with pytest.raises(ValueError):
        audit_tuple(args)


def test_missing_raw_evidence_is_a_hold_not_a_fake_success(tmp_path):
    args = list(populated(tmp_path))
    index = args[1]
    index["rows"][0]["rounds"][0]["requests"] = None
    index["rows"][0]["rounds"][0]["logs"] = None
    report, rows = audit_tuple(args)
    assert report["source_rounds_with_requests_export"] == 0
    assert rows[0]["source_round_evidence_state"] == (
        "held_for_source_round_evidence_review"
    )
    assert "requests_export_missing" in rows[0]["issue_codes"]
    assert "logs_export_missing" in rows[0]["issue_codes"]


@pytest.mark.parametrize("change,expected", [
    ("unexpected_url", "unexpected_url_or_redirect_request"),
    ("post", "unexpected_non_get_method"),
    ("duplicate_get", "missing_or_duplicate_exact_primary_get"),
    ("429", "publisher_access_denial_or_rate_limit_observed"),
    ("wrong_response", "primary_request_status_differs_from_source_item"),
    ("future_time", "request_timestamp_outside_job_window"),
    ("stats_mismatch", "requests_export_count_differs_from_scrapy_stats"),
])
def test_unexpected_requests_rate_limits_and_inconsistent_counts_flagged(
        tmp_path, change, expected):
    source = chosen()
    reqs = [robots(source), primary(source)]
    status = 200
    nreq = 2
    if change == "unexpected_url":
        reqs.append(primary(source, url="https://evil.invalid/redirected"))
        nreq = 3
    elif change == "post":
        reqs[1]["method"] = "POST"
    elif change == "duplicate_get":
        reqs.append(primary(source))
        nreq = 3
    elif change == "429":
        reqs[1]["status"] = 429
        status = 429
    elif change == "wrong_response":
        reqs[1]["status"] = 302
    elif change == "future_time":
        reqs[1]["time"] = epoch(timedelta(hours=7))
    else:
        nreq = 3
    args = populated(
        tmp_path, requests=reqs, status=status,
        item_status="needs_review" if status == 429 else "captured",
        num_requests=nreq,
    )
    report, rows = audit_tuple(args)
    assert expected in rows[0]["issue_codes"]
    assert rows[0]["source_round_evidence_state"] == (
        "held_for_source_round_evidence_review"
    )
    assert report["full_460_source_diagnostic_approved"] is False


def test_log_error_is_seen_without_leaking_sensitive_log_messages(tmp_path):
    private_message = "SENSITIVE-LOG-CONTENT-FOR-TEST"
    args = populated(tmp_path, logs=[
        info_log(),
        {
            "level": 40, "time": epoch(timedelta(minutes=-35, seconds=7)),
            "message": private_message,
        },
    ])
    report, rows = audit_tuple(args)
    assert "job_error_or_critical_logs_present" in rows[0]["issue_codes"]
    assert rows[0]["log_error_count"] == 1
    assert private_message not in json.dumps(report)


@pytest.mark.parametrize("bad", [
    "requests_sha", "logs_sha", "missing_export", "symlink",
    "malformed_jsonl", "json_array", "duplicate_field", "request_missing_field",
    "bad_log_level", "wrong_duration_type",
])
def test_malformed_or_corrupt_raw_exports_are_rejected(tmp_path, bad):
    args = list(populated(tmp_path))
    c1, exports, archive_root, export_root, pol, src = args
    slot = exports["rows"][0]["rounds"][0]
    request = export_root / slot["requests"]["file"]
    log = export_root / slot["logs"]["file"]
    if bad == "requests_sha":
        slot["requests"]["sha256"] = "f" * 64
    elif bad == "logs_sha":
        slot["logs"]["sha256"] = "f" * 64
    elif bad == "missing_export":
        request.unlink()
    elif bad == "symlink":
        new = request.with_name("linked.jl")
        new.symlink_to(request)
        slot["requests"]["file"] = (
            slot["requests"]["file"].replace("requests.jl", "linked.jl")
        )
    elif bad == "malformed_jsonl":
        request.write_text("{this is not json}\n")
    elif bad == "json_array":
        request.write_text('["not a Zyte Request"]\n')
    elif bad == "duplicate_field":
        request.write_text(
            '{"time":0,"time":1,"method":"GET","url":"https://example.com",'
            '"status":200,"duration":1,"rs":1}\n'
        )
    elif bad == "request_missing_field":
        request.write_text('{"time":1}\n')
    elif bad == "bad_log_level":
        log.write_text('{"level":99,"message":"bad"}\n')
    else:
        request.write_text(json.dumps({
            **primary(src), "duration": "10",
        }) + "\n")
    if bad in {
        "malformed_jsonl", "json_array", "duplicate_field",
        "request_missing_field", "wrong_duration_type",
    }:
        slot["requests"]["sha256"] = hashlib.sha256(request.read_bytes()).hexdigest()
    if bad == "bad_log_level":
        slot["logs"]["sha256"] = hashlib.sha256(log.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        audit_tuple(args)


def test_optional_p22a1_html_is_cross_checked_but_not_same_job_proof(tmp_path):
    args = populated(tmp_path)
    src = args[-1]
    ledger = blank_html_ledger(frozen_plan())
    html_root = tmp_path / "html"
    html_root.mkdir()
    row = ledger["rows"][0]
    host = src["url"].split("/")[2]
    row["policy_review"] = {
        "decision": "operator_attested_manual_permitted",
        "reviewer": "Synthetic Evidence Reviewer",
        "reviewed_at_utc": at(timedelta(days=-2)),
        "expires_at_utc": at(timedelta(days=2)),
        "ownership_url": src["url"],
        "terms_url": "https://" + host + "/terms",
        "robots_url": "https://" + host + "/robots.txt",
        "retention_reviewed": True, "note": NOTE,
    }
    body = (
        "<html><main><h1>Mock product source</h1><p>"
        + "Synthetic source content, never genuine vendor evidence. " * 24
        + "</p></main></html>"
    ).encode("utf-8")
    path = html_root / "synthetic-raw.html"
    path.write_bytes(body)
    sha = hashlib.sha256(body).hexdigest()
    row["rounds"][0] = {
        "round": 1, "state": "captured",
        "snapshot": {
            "file": "synthetic-raw.html", "sha256": sha,
            "request_url": src["url"], "final_url": src["url"],
            "http_status": 200, "media_type": "text/html",
            "capture_method": "static_html",
            "captured_at_utc": at(timedelta(minutes=-30)),
            "capture_origin_review_status": "operator_supplied_unverified",
        },
        "capture_receipt_id": "SYNTHETIC-P23C2-HTML-ROUND-01",
    }
    report, rows = audit_tuple(
        args, p22a1_ledger=ledger, html_root=html_root,
    )
    assert report["source_rounds_with_independent_original_html_sha"] == 1
    assert rows[0]["original_html_sha256"] == sha
    assert rows[0]["p22a1_original_html_status"] == (
        "independent_p22a1_original_html_sha256_verified"
    )
    assert rows[0]["same_zyte_html_response_proven"] is False
    assert report["raw_original_html_response_from_same_zyte_job_proven"] is False
    assert rows[0]["source_round_evidence_state"] == (
        "all_local_exports_consistent_NOT_origin_verified"
    )


def test_p22a1_html_with_wrong_source_or_snapshot_hash_is_rejected(tmp_path):
    args = populated(tmp_path)
    ledger = blank_html_ledger()
    html_root = tmp_path / "html"
    html_root.mkdir()
    ledger["rows"][0]["source_id"] = "wrong_source"
    with pytest.raises(ValueError):
        audit_tuple(args, p22a1_ledger=ledger, html_root=html_root)
