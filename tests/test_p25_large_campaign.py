"""P25: 200-300-source 3-job campaign and real POST safety tests (NO NETWORK)."""
import base64
import csv
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from agentfuse_crawlers.run_context import manifest_sha256, package_fingerprint, selection_ids_sha256
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources, select_sources
from agentfuse_crawlers import validation_access as policy
from scripts import p25_large_campaign as p
from scripts import p25_launch_full_campaign as launch
from scripts import p25_audit_campaign_items as audit
from scripts.g3_historical_items_triage import COLUMNS as G3_COLUMNS

NOW = datetime(2026, 11, 16, 9, tzinfo=timezone.utc)
PROJECT = "883514"
REVIEWER = "Synthetic Campaign Reviewer"
FAKE_NOTE = (
    "SYNTHETIC TEST ONLY: no real publisher permission is being claimed. "
    "Exact source-specific ownership, robots, governing website terms, "
    "commercial reuse and private raw HTML retention require independent "
    "human verification before any legitimate production publisher request."
)


def _date(delta):
    return (NOW + delta).isoformat(timespec="seconds")


def _g3_rows():
    manifest = load_sources()
    rows = []
    for cat in ("documentation", "pricing", "changelog"):
        # Select genuinely lifecycle-eligible synthetic IDs; the three v0
        # entries are quarantined in the real manifest and MUST never be
        # "approved" even by a positive fake test case.
        group = [s for s in manifest if s["category"] == cat
                 and s["id"] != "v0_" + ("docs" if cat == "documentation" else
                                        "pricing" if cat == "pricing" else
                                        "changelog")]
        for src in group[:p.QUOTA_300[cat]]:
            rows.append({
                "source_id": src["id"], "category": cat,
                "source_url": src["url"], "provider": src["provider"],
                "historical_status_NOT_CURRENT": "needs_review",
            })
    assert len(rows) == 300
    return rows


def _fake_policy(rows, target):
    quotas = {"documentation": target * 2 // 5,
              "pricing": target * 2 // 5,
              "changelog": target // 5}
    known = {s["id"]: s for s in load_sources()}
    chosen = set()
    for cat, n in quotas.items():
        chosen.update([
            row["source_id"] for row in rows
            if row["category"] == cat
        ][:n])
    reviews = {}
    for sid in chosen:
        src = known[sid]
        host = urlsplit(src["url"]).hostname
        reviews[sid] = {
            "source_url": src["url"], "category": src["category"],
            "decision": "allowed_reviewed",
            "scopes": ["bulk_validation"],
            "reviewed_by": REVIEWER,
            "reviewed_at_utc": _date(timedelta(hours=-1)),
            "expires_at_utc": _date(timedelta(days=5)),
            "ownership_evidence_url": src["url"],
            "publisher_access_policy_url": "https://" + host + "/terms",
            "robots_url": "https://" + host + "/robots.txt",
            "publisher_terms_reviewed": True,
            "robots_reviewed": True,
            "private_retention_reviewed": True,
            "evidence_note": FAKE_NOTE,
        }
    access = {
        "schema_version": policy.SCHEMA, "kind": policy.ACCESS_KIND,
        "default_decision": "not_reviewed", "reviews": reviews,
    }
    plans = {}
    for cat in p.ORDER:
        whole = select_sources(cat, "all")
        ids = [s["id"] for s in whole]
        allowed = [sid for sid in ids if sid in chosen]
        assert len(allowed) == quotas[cat]
        plans["synthetic_p25_" + cat] = {
            "category": cat, "collection_mode": "validation",
            "cohort": "all", "source_ids": ids,
            "authorized_source_ids": allowed,
            "manifest_sha256": manifest_sha256(),
            "source_registry_sha256": registry_revision_sha256(),
            "access_registry_sha256": policy.validation_access_revision_sha256(access),
            "selection_ids_sha256": selection_ids_sha256(whole),
            "source_urls_sha256": policy._urls_digest(whole),
            "approved_by": REVIEWER,
            "reviewed_at_utc": _date(timedelta(hours=-1)),
            "expires_at_utc": _date(timedelta(hours=3)),
            "max_primary_requests": len(allowed),
            "max_redirects_per_source": 0,
            "purpose": "bounded_human_supervised_diagnostic",
            "publisher_policy_review_attested": True,
        }
    approved = {
        "schema_version": policy.SCHEMA, "kind": policy.PLAN_KIND,
        "default_policy": "no_bulk_runs_authorized", "plans": plans,
    }
    return access, approved


def _clean_account(project, key):
    assert key == "SYNTHETIC_KEY_NO_HTTP"
    return {
        "project_id": project, "only_three_zyte_api_gets": True,
        "queue_list_single_pages_complete": True,
        "periodic_schedule_list_complete": True,
        "no_pending_or_running_jobs_observed": True,
        "no_enabled_periodic_schedules_observed": True,
        "readiness_to_run": False, "new_jobs_created_or_modified": 0,
    }


def _params(tmp_path, target=300):
    rows = _g3_rows()
    access, plans = _fake_policy(rows, target)
    report = p.build_campaign(rows, target, access=access, plans=plans, now=NOW)
    return {
        "g3_rows": rows, "target": target, "category": "pricing",
        "project": PROJECT, "campaign_sha256": report["campaign_sha256"],
        "observed_remote_package_sha256": package_fingerprint(),
        "ledger_dir": tmp_path / "private-ledger",
        "ack_account_billing": launch.ACK_BUDGET,
        "ack_source_rights": launch.ACK_SOURCE,
        "key": "SYNTHETIC_KEY_NO_HTTP",
        "access": access, "plans": plans, "now": NOW,
        "account_preflight": _clean_account,
    }


@pytest.mark.parametrize("target,quotas", [
    (200, {"documentation": 80, "pricing": 80, "changelog": 40}),
    (250, {"documentation": 100, "pricing": 100, "changelog": 50}),
    (300, {"documentation": 120, "pricing": 120, "changelog": 60}),
])
def test_full_campaign_has_three_large_category_jobs_not_tiny_shards(target, quotas):
    rows = _g3_rows()
    access, plans = _fake_policy(rows, target)
    report = p.build_campaign(rows, target, access=access, plans=plans, now=NOW)
    assert report["target_primary_urls"] == target
    assert report["category_quotas"] == quotas
    assert report["total_accounted_manifest_source_ids"] == 460
    assert report["target_held_manifest_items"] == 460 - target
    assert report["reviewed_bulk_source_count_in_campaign"] == target
    assert report["missing_current_source_access_reviews"] == 0
    assert report["planned_full_category_jobs"] == 3
    assert report["local_policy_and_three_plan_scope_complete"] is True
    assert report["readiness_to_launch_from_this_report"] is False
    assert report["new_scrapy_cloud_jobs"] == report["publisher_requests_performed"] == 0
    assert sum(j["target_authorized_primary_urls"] for j in report["jobs"]) == target
    assert sum(j["requested_manifest_items"] for j in report["jobs"]) == 460
    assert sum(j["held_manifest_items_target"] for j in report["jobs"]) == 460 - target
    assert {j["category"] for j in report["jobs"]} == set(quotas)
    assert all(j["spider_args"] == {
        "cohort": "all", "confirm_full_inventory": "yes",
        "collection_mode": "validation"
    } for j in report["jobs"])


def test_installed_unreviewed_registries_block_every_full_job(tmp_path):
    rows = _g3_rows()
    report = p.build_campaign(rows, 300)
    assert report["reviewed_bulk_source_count_in_campaign"] == 0
    assert report["missing_current_source_access_reviews"] == 300
    assert report["local_policy_and_three_plan_scope_complete"] is False
    assert len(report["blockers"]) >= 3
    output = tmp_path / "private-report"
    p.write_report(report, output)
    saved = json.loads((output / "p25_full_campaign_plan_NO_GO.json").read_text())
    assert saved == report
    with pytest.raises(ValueError):
        p.write_report(report, output)
    with pytest.raises(ValueError, match="NO-GO"):
        launch.dispatch_one(
            g3_rows=rows, target=300, category="documentation",
            project=PROJECT, campaign_sha256=report["campaign_sha256"],
            observed_remote_package_sha256=package_fingerprint(),
            ledger_dir=tmp_path / "ledger", ack_account_billing=launch.ACK_BUDGET,
            ack_source_rights=launch.ACK_SOURCE,
            key="SYNTHETIC_KEY_NO_HTTP",
            account_preflight=lambda *_: pytest.fail("would contact Zyte"),
            post=lambda *_: pytest.fail("must not dispatch"),
        )


@pytest.mark.parametrize("target", [0, 199, 201, 299, 301, True, "300"])
def test_invalid_campaign_size_is_rejected(target):
    with pytest.raises(ValueError):
        p.build_campaign(_g3_rows(), target)


def test_scope_plan_mismatch_and_missing_review_both_block_launch(tmp_path):
    args = _params(tmp_path)
    corrupted_plan = deepcopy(args["plans"])
    corrupted_plan["plans"]["synthetic_p25_pricing"]["authorized_source_ids"].pop()
    corrupted_plan["plans"]["synthetic_p25_pricing"]["max_primary_requests"] -= 1
    changed = p.build_campaign(args["g3_rows"], 300, access=args["access"],
                               plans=corrupted_plan, now=NOW)
    assert not changed["local_policy_and_three_plan_scope_complete"]
    assert "pricing:authorized_subset_does_not_match_campaign" in changed["blockers"]
    with pytest.raises(ValueError, match="NO-GO"):
        launch.dispatch_one(**{**args, "plans": corrupted_plan},
                            post=lambda *_: pytest.fail("unsafe POST"))
    missing_access = deepcopy(args["access"])
    missing_access["reviews"].pop(next(iter(missing_access["reviews"])))
    unapproved = p.build_campaign(args["g3_rows"], 300, access=missing_access,
                                  plans=args["plans"], now=NOW)
    assert not unapproved["local_policy_and_three_plan_scope_complete"]
    with pytest.raises(ValueError, match="NO-GO"):
        launch.dispatch_one(**{**args, "access": missing_access},
                            post=lambda *_: pytest.fail("unsafe POST"))


def test_one_real_post_path_and_private_immutable_receipt(tmp_path):
    args = _params(tmp_path)
    invoked = []

    def fake_post(project, job, key, timeout):
        invoked.append((project, job["category"], job["target_authorized_primary_urls"],
                        key, timeout))
        return b'{"status":"ok","jobid":"883514/3/225"}'

    result = launch.dispatch_one(**args, post=fake_post)
    assert result["status"] == "SCHEDULED_NOT_FINISHED_NOT_AUDITED"
    assert result["job_id"] == "883514/3/225"
    assert result["target_primary_urls"] == 120
    assert len(invoked) == 1
    assert invoked[0] == (PROJECT, "pricing", 120, "SYNTHETIC_KEY_NO_HTTP", 3300)
    files = sorted(args["ledger_dir"].iterdir())
    assert len(files) == 2
    assert all(file.stat().st_mode & 0o077 == 0 for file in files)
    assert files[0].name.endswith("ATTEMPTED_NO_BLIND_RETRY.json")
    assert files[1].name.endswith("SCHEDULED.json")
    payload = "".join(f.read_text() for f in files)
    assert "SYNTHETIC_KEY_NO_HTTP" not in payload
    assert "completion_verified" in payload
    assert "SCHEDULED_NOT_FINISHED_NOT_AUDITED" in payload
    with pytest.raises(FileExistsError):
        launch.dispatch_one(**args, post=lambda *_: pytest.fail("duplicate POST"))


def test_unknown_post_response_persists_irrevocable_attempt_marker(tmp_path):
    args = _params(tmp_path)
    invoked = []

    def fail_after_possible_post(*values):
        invoked.append(values)
        raise TimeoutError("synthetic timeout; job status UNKNOWN")

    with pytest.raises(TimeoutError):
        launch.dispatch_one(**args, post=fail_after_possible_post)
    assert len(invoked) == 1
    assert len(list(args["ledger_dir"].iterdir())) == 1
    assert next(args["ledger_dir"].iterdir()).name.endswith(
        "ATTEMPTED_NO_BLIND_RETRY.json"
    )
    with pytest.raises(FileExistsError):
        launch.dispatch_one(**args, post=lambda *_: pytest.fail("duplicate POST"))


@pytest.mark.parametrize("mutation", [
    {"observed_remote_package_sha256": "f" * 64},
    {"campaign_sha256": "0" * 64},
    {"ack_source_rights": "not-reviewed"},
    {"ack_account_billing": "not-reviewed"},
    {"timeout_seconds": 4000},
    {"project": "https://evil.invalid"},
])
def test_wrong_deployment_budget_or_scope_refuses_before_api(tmp_path, mutation):
    args = {**_params(tmp_path), **mutation}
    with pytest.raises(ValueError):
        launch.dispatch_one(
            **{**args, "account_preflight": lambda *_: pytest.fail("unsafe GET")},
            post=lambda *_: pytest.fail("unsafe POST"))
    assert not (tmp_path / "private-ledger").exists()


@pytest.mark.parametrize("bad_field", [
    "queue_list_single_pages_complete", "periodic_schedule_list_complete",
    "no_pending_or_running_jobs_observed",
    "no_enabled_periodic_schedules_observed", "only_three_zyte_api_gets"
])
def test_account_snapshot_incomplete_active_or_invalid_refuses(tmp_path, bad_field):
    args = _params(tmp_path)
    def bad_account(pj, key):
        r = _clean_account(pj, key)
        r[bad_field] = False
        return r
    with pytest.raises(ValueError, match="NO-GO"):
        launch.dispatch_one(**{**args, "account_preflight": bad_account},
                            post=lambda *_: pytest.fail("unsafe POST"))
    assert not (tmp_path / "private-ledger").exists()


@pytest.mark.parametrize("raw", [
    b'{"status":"error","jobid":"883514/3/2"}',
    b'{"status":"ok","jobid":"999999/3/2"}',
    b'{"status":"ok","jobid":"883514/3/2","status":"ok"}',
    b'{"status":"ok","jobid":"not-a-job"}',
    b'not-json',
])
def test_untrusted_zyte_dispatch_responses_are_rejected(raw):
    with pytest.raises(ValueError):
        launch._response_job_id(raw, PROJECT)


def test_exact_post_to_official_scrapy_cloud_jobs_api_only(monkeypatch):
    calls = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def read(self, size):
            assert size == launch.MAX_RETURN + 1
            return b'{"status":"ok","jobid":"883514/3/225"}'
    class Opener:
        def open(self, req, timeout):
            calls.append(req)
            assert timeout == 30
            return Response()
    monkeypatch.setattr(launch.urllib.request, "build_opener",
                        lambda handler: Opener())
    job = {"spider": "official_pricing", "spider_args": {
        "cohort": "all", "collection_mode": "validation",
        "confirm_full_inventory": "yes",
    }}
    body = launch._post_run(PROJECT, job, "FAKE_NOT_A_SECRET", 3300)
    assert launch._response_job_id(body, PROJECT) == "883514/3/225"
    assert len(calls) == 1
    req = calls[0]
    assert req.get_method() == "POST"
    assert req.full_url == "https://app.zyte.com/api/run.json"
    params = parse_qs(req.data.decode())
    assert params == {
        "project": [PROJECT], "spider": ["official_pricing"],
        "priority": ["2"], "units": ["1"],
        "job_settings": ['{"CLOSESPIDER_TIMEOUT":3300}'],
        "cohort": ["all"], "collection_mode": ["validation"],
        "confirm_full_inventory": ["yes"],
    }
    assert req.get_header("Authorization").startswith("Basic ")
    auth = req.get_header("Authorization").split(" ")[1]
    assert base64.b64decode(auth).decode() == "FAKE_NOT_A_SECRET:"


def test_g3_csv_enforces_bound_source_ids_and_no_spreadsheet_injection(tmp_path):
    rows = _g3_rows()
    path = tmp_path / p.G3_FILENAME
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=G3_COLUMNS)
        writer.writeheader()
        for i, row in enumerate(rows, 1):
            record = dict(row)
            record["historical_review_rank"] = i
            record["top_300_historical_REVIEW_ONLY"] = True
            record["publisher_permission_independently_verified"] = False
            record["approved_for_advisor"] = False
            writer.writerow(record)
    loaded = p.read_g3_review_csv(path)
    assert len(loaded) == 300
    report = p.build_campaign(loaded, 300)
    assert report["target_primary_urls"] == 300
    tampered = path.read_text(encoding="utf-8-sig").replace(
        rows[0]["source_url"], "https://evil.invalid", 1
    )
    path.write_text(tampered, encoding="utf-8-sig")
    with pytest.raises(ValueError):
        p.read_g3_review_csv(path)



def _synthetic_campaign_archives(rows, target, access, plans):
    report = p.build_campaign(rows, target, access=access, plans=plans, now=NOW)
    manifest = load_sources()
    records = {}
    for i, job in enumerate(report["jobs"], 1):
        category = job["category"]
        selected = set(job["target_source_ids_manifest_order"])
        group = select_sources(category, "all")
        job_id = f"{PROJECT}/{i}/{i+100}"
        category_rows = []
        for src in group:
            targeted = src["id"] in selected
            held_status = ("source_quarantined" if src["id"].startswith("v0_")
                           else "source_bulk_validation_not_approved")
            category_rows.append({
                "source_id": src["id"], "source_url": src["url"],
                "provider": src["provider"], "category": category,
                "spider_name": job["spider"], "approved_for_advisor": False,
                "collection_mode": "validation", "requested_cohort": "all",
                "manifest_sha256": report["manifest_sha256"],
                "source_registry_sha256": report["source_registry_sha256"],
                "selection_ids_sha256": selection_ids_sha256(group),
                "selection_source_count": len(group),
                "zyte_job_id": job_id,
                "deployment_revision": package_fingerprint(),
                "status": "needs_review" if targeted else held_status,
                "http_status": 200 if targeted else None,
                "policy_observation": (
                    "" if targeted else "not_fetched_by_bulk_source_access_gate"
                ),
            })
        records[category] = [{
            "job": {
                "category": category, "spider": job["spider"],
                "state": "finished", "close_reason": "finished",
                "spider_args": audit.EXPECTED_ARGS,
                "unrecorded_argument_names": [], "job_id": job_id,
            },
            "source_scope": {"safe_for_semantic_diff": True},
        }, category_rows]
    paths = [Path("/FAKE_SYNTHETIC_P25_ARCHIVE") / category
             for category in audit.ORDER]
    def loader(path):
        # In production, audit loads and byte-verifies actual P07 archives.
        return records[Path(path).name]
    return paths, records, loader


def test_three_real_archives_can_be_audited_with_p23e0_compact_args(tmp_path):
    args = _params(tmp_path, target=300)
    paths, records, loader = _synthetic_campaign_archives(
        args["g3_rows"], 300, args["access"], args["plans"],
    )
    result = audit.audit_archives(
        args["g3_rows"], 300, paths,
        access=args["access"], plans=args["plans"], now=NOW, loader=loader,
    )
    assert result["total_manifest_slots"] == 460
    assert result["manifest_slots_observed"] == 460
    assert result["target_primary_urls"] == 300
    assert result["target_http200_items_NOT_ACCURACY"] == 300
    assert result["full_campaign_items_coverage_complete"] is True
    assert result["status"] == "NO_GO_ARCHIVED_ITEMS_COMPLETE_NOT_REQUESTS_OR_GOLD"
    assert result["requests_and_logs_independently_reconciled"] is False
    assert result["publisher_html_and_human_gold_independently_verified"] is False
    assert result["approved_for_advisor"] is False
    assert sum(x["observed_items"] for x in result["categories"].values()) == 460
    out = tmp_path / "p25-audit"
    audit.write_audit(result, out)
    assert json.loads((out / "p25_immutable_items_full_campaign_NO_GO.json").read_text()) == result
    with pytest.raises(ValueError):
        audit.write_audit(result, out)


def test_archive_detects_full_campaign_incomplete_and_http_access_barriers(tmp_path):
    args = _params(tmp_path, target=200)
    paths, records, loader = _synthetic_campaign_archives(
        args["g3_rows"], 200, args["access"], args["plans"],
    )
    records["documentation"][1].pop()  # missing one expected manifest item
    one = records["pricing"][1][0]
    assert one["status"] == "needs_review"
    one["status"] = "robots_or_policy_denied"
    one["http_status"] = None
    result = audit.audit_archives(
        args["g3_rows"], 200, paths,
        access=args["access"], plans=args["plans"], now=NOW, loader=loader,
    )
    assert result["manifest_slots_observed"] == 459
    assert result["target_access_barrier_count"] == 1
    assert result["full_campaign_items_coverage_complete"] is False
    assert result["status"] == "NO_GO_INCOMPLETE_OR_ACCESS_BARRIER"


@pytest.mark.parametrize("tamper", [
    "unauthorized_extra_fetch",
    "false_advisor_promotion",
    "wrong_package",
    "wrong_spider_args",
    "policy_held_target",
])
def test_archive_scope_tampering_and_unauthorized_extra_are_rejected(tmp_path, tamper):
    args = _params(tmp_path)
    paths, records, loader = _synthetic_campaign_archives(
        args["g3_rows"], 300, args["access"], args["plans"],
    )
    row = records["pricing"][1][-1]  # nonselected tail
    if tamper == "unauthorized_extra_fetch":
        row["http_status"] = 200
    elif tamper == "false_advisor_promotion":
        row["approved_for_advisor"] = True
    elif tamper == "wrong_package":
        row["deployment_revision"] = "f" * 64
    elif tamper == "wrong_spider_args":
        records["pricing"][0]["job"]["spider_args"] = {
            "cohort": "all", "source_ids": "openai_api_pricing",
            "collection_mode": "validation",
        }
    elif tamper == "policy_held_target":
        first = records["pricing"][1][0]
        first["status"] = "source_bulk_validation_not_approved"
        first["http_status"] = None
    with pytest.raises(ValueError):
        audit.audit_archives(
            args["g3_rows"], 300, paths,
            access=args["access"], plans=args["plans"], now=NOW, loader=loader,
        )


def test_audit_rejects_archive_duplicates_before_trusting_counts(tmp_path):
    args = _params(tmp_path)
    paths, records, loader = _synthetic_campaign_archives(
        args["g3_rows"], 300, args["access"], args["plans"],
    )
    with pytest.raises(ValueError, match="Exactly 3 distinct"):
        audit.audit_archives(args["g3_rows"], 300, [paths[0]] * 3,
                             access=args["access"], plans=args["plans"], now=NOW,
                             loader=loader)
