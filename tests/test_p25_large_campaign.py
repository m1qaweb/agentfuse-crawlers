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



def _g3_all460_rows():
    """Synthetic G3 all460 ranking: first original top300, then remaining 160."""
    top = _g3_rows()
    known = {r["source_id"] for r in top}
    remainder = [{
        "source_id": s["id"], "category": s["category"],
        "source_url": s["url"], "provider": s["provider"],
        "historical_status_NOT_CURRENT": "needs_review",
    } for s in load_sources() if s["id"] not in known]
    assert len(remainder) == 160
    assert len(top + remainder) == 460
    return top + remainder


def _write_synthetic_g3_csv(rows, path):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=G3_COLUMNS)
        writer.writeheader()
        for i, row in enumerate(rows, 1):
            record = dict(row)
            record["historical_review_rank"] = i
            record["top_300_historical_REVIEW_ONLY"] = i <= 300
            record["publisher_permission_independently_verified"] = False
            record["approved_for_advisor"] = False
            writer.writerow(record)


def _fake_policy(rows, target, *, use_later_ranked=False):
    quotas = {"documentation": target * 2 // 5,
              "pricing": target * 2 // 5,
              "changelog": target // 5}
    known = {s["id"]: s for s in load_sources()}
    chosen = set()
    for cat, n in quotas.items():
        candidate_ids = [
            row["source_id"] for row in rows if row["category"] == cat
        ]
        if use_later_ranked:
            # A quarantined source can never get a positive, even fake,
            # permission. In the real G3 all-460 tail the three v0 entries
            # remain present for inventory but are not crawl eligible.
            candidate_ids = [sid for sid in candidate_ids
                             if not sid.startswith("v0_")]
        chosen.update(candidate_ids[-n:] if use_later_ranked else candidate_ids[:n])
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


def test_200_full_campaign_can_use_later_ranked_but_human_reviewed_sources():
    rows = _g3_rows()
    access, plans = _fake_policy(rows, 200, use_later_ranked=True)
    report = p.build_campaign(rows, 200, access=access, plans=plans, now=NOW)
    assert report["reviewed_bulk_source_count_in_campaign"] == 200
    assert report["local_policy_and_three_plan_scope_complete"] is True
    assert not report["blockers"]
    assert report["target_primary_urls"] == 200
    assert report["reviewed_first_with_same_category_historical_fallback"] is True
    # A formerly higher-ranked, but not reviewed source is not silently
    # selected just because it appeared at the top of historical G3.
    top_doc_id = next(r["source_id"] for r in rows
                      if r["category"] == "documentation")
    selected = next(j for j in report["jobs"]
                    if j["category"] == "documentation")["target_source_ids_manifest_order"]
    assert top_doc_id not in selected


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



@pytest.mark.parametrize("target", [200, 250, 300])
def test_full_460_review_pool_fills_real_200_to_300_campaign_from_later_cleared_sources(target):
    rows = _g3_all460_rows()
    access, plans = _fake_policy(rows, target, use_later_ranked=True)
    report = p.build_campaign(rows, target, access=access, plans=plans, now=NOW)
    assert report["historical_review_candidate_pool"] == 460
    assert report["reviewed_bulk_source_count_in_campaign"] == target
    assert report["local_policy_and_three_plan_scope_complete"] is True
    assert report["missing_current_source_access_reviews"] == 0
    assert report["target_held_manifest_items"] == 460 - target
    assert sum(j["target_authorized_primary_urls"] for j in report["jobs"]) == target
    # The original top-300 may contain denied/unreviewed IDs, even with
    # historical capture. A genuinely reviewed lower-ranked source should
    # fill the exact same category's quota; it does NOT confer permissions.
    last = {r["source_id"] for r in rows[-160:]}
    chosen = {sid for j in report["jobs"]
              for sid in j["target_source_ids_manifest_order"]}
    assert chosen & last
    assert report["new_scrapy_cloud_jobs"] == 0
    assert report["readiness_to_launch_from_this_report"] is False


def test_p25_accepts_exact_g3_all460_and_denies_rank_or_quota_tampering(tmp_path):
    rows = _g3_all460_rows()
    path = tmp_path / p.G3_ALL_FILENAME
    _write_synthetic_g3_csv(rows, path)
    parsed = p.read_g3_review_csv(path)
    assert len(parsed) == 460
    assert p.build_campaign(parsed, 300)["historical_review_candidate_pool"] == 460
    bad = path.read_text(encoding="utf-8-sig").replace("False", "True", 1)
    path.write_text(bad, encoding="utf-8-sig")
    with pytest.raises(ValueError):
        p.read_g3_review_csv(path)
    _write_synthetic_g3_csv(rows, path)
    content = path.read_text(encoding="utf-8-sig")
    content = content.replace("161,", "162,", 1) if "161," in content else (
        content.replace("461,", "460,", 1)
    )
    path.write_text(content, encoding="utf-8-sig")
    with pytest.raises(ValueError):
        p.read_g3_review_csv(path)




# P26B uses a completed category and the real P25 receipt shapes, never a
# live credential or network. The fixtures deliberately retain a historical
# dispatch time so the current system clock cannot change replay results.
from scripts import p26b_campaign_evidence as evidence


def _evidence_context(tmp_path):
    args = _params(tmp_path, target=200)
    report = p.build_campaign(args["g3_rows"], 200, access=args["access"],
                              plans=args["plans"], now=NOW)
    paths, records, loader = _synthetic_campaign_archives(
        args["g3_rows"], 200, args["access"], args["plans"])
    envelope, items = records["pricing"]
    job = envelope["job"]
    job_id = job["job_id"]
    start = int(NOW.timestamp() * 1000) + 1000
    end = start + 3000
    job.update(expected_item_count=len(items), deploy_id="7",
               deployment_version="synthetic", finished_time_ms=end,
               stats={"downloader/request_count": 101})
    category = next(j for j in report["jobs"] if j["category"] == "pricing")
    plan_id = category["matching_plan_id_NOT_REMOTE_PROOF"]
    plan = args["plans"]["plans"][plan_id]
    ids = set(category["target_source_ids_manifest_order"])
    for item in items:
        item.update(
            bulk_access_registry_sha256=report["access_registry_sha256"],
            bulk_run_plan_registry_sha256=report["bulk_run_registry_sha256"],
            bulk_run_plan_id=plan_id, bulk_run_plan_sha256=policy.digest(plan),
            bulk_source_authorized_by_reviewed_plan=item["source_id"] in ids)
    # A safely stopped job still contains diagnostic evidence.
    items.pop()
    job["expected_item_count"] = len(items)
    job["close_reason"] = "agentfuse_validation_http_429"
    archive_dir = tmp_path / "pricing"
    archive_dir.mkdir()
    (archive_dir / "envelope.json").write_text(json.dumps(envelope))
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    label = report["campaign_sha256"] + ".pricing"
    attempt = {
        "status": "DISPATCH_ATTEMPTED_UNKNOWN_UNTIL_ZYTE_RESPONSE",
        "campaign_sha256": report["campaign_sha256"], "category": "pricing",
        "project": PROJECT, "target_primary_urls": len(ids),
        "remote_package_digest_OPERATOR_ATTESTATION_NOT_API_VERIFIED":
            report["local_package_sha256_NOT_REMOTE_PROOF"],
        "attempted_at_utc": NOW.isoformat(),
    }
    accepted = {
        "status": "SCHEDULED_NOT_FINISHED_NOT_AUDITED",
        "campaign_sha256": report["campaign_sha256"], "category": "pricing",
        "job_id": job_id, "target_primary_urls": len(ids),
        "requested_manifest_items": category["requested_manifest_items"],
    }
    attempt_path = ledger / (label + ".ATTEMPTED_NO_BLIND_RETRY.json")
    accepted_path = ledger / (label + ".SCHEDULED.json")
    attempt_path.write_text(json.dumps(attempt))
    accepted_path.write_text(json.dumps(accepted))

    def context():
        return evidence.load_context(
            args["g3_rows"], 200, report["campaign_sha256"], "pricing", ledger,
            archive_dir, access=args["access"], plans=args["plans"],
            loader=lambda _: (envelope, items),
        )

    urls = [s["source_url"] for s in items if s["source_id"] in ids]
    requests = [
        {"_key": f"{job_id}/{i}", "url": url, "method": "GET",
         "time": start + 500, "status": 200, "duration": 20, "rs": 100}
        for i, url in enumerate(urls)
    ]
    # More rows than the old single-source 96-request limit.
    for i in range(len(requests), 101):
        requests.append({"_key": f"{job_id}/{i}", "url": "https://unexpected.invalid/",
                         "method": "GET", "time": start + 500,
                         "status": 429, "duration": 20, "rs": 100})
    logs = [{"_key": f"{job_id}/0", "level": 30, "message": "Synthetic stop", "time": end}]
    remote = {
        "state": "finished", "spider": job["spider"],
        "spider_args": job["spider_args"], "close_reason": job["close_reason"],
        "deploy_id": 7, "version": job["deployment_version"],
        "running_time": start, "finished_time": end,
        "scrapystats": {"item_scraped_count": len(items), "downloader/request_count": 101},
    }
    return context, attempt_path, accepted_path, remote, requests, logs


def _fake_evidence_fetch(remote, requests, logs, *, stats_count=None):
    def fetch(url, key, limit):
        assert key == "SYNTHETIC_KEY_NO_HTTP"
        parts = urlsplit(url)
        assert parts.scheme == "https" and parts.netloc == "storage.zyte.com"
        kind = parts.path.split("/")[1]
        if kind == "jobs":
            return json.dumps(remote).encode()
        if parts.path.endswith("/stats"):
            return json.dumps({"totals": {"input_values":
                               len(requests) if stats_count is None else stats_count}}).encode()
        query = parse_qs(parts.query)
        offset = int(query["start"][0].rsplit("/", 1)[-1])
        # Intentionally return short nonempty pages to ensure no premature stop.
        count = min(int(query["count"][0]), 9)
        rows = (requests if kind == "requests" else logs)[offset:offset + count]
        return b"".join((json.dumps(row) + "\n").encode() for row in rows)
    return fetch


def test_p26b_category_export_replays_incomplete_historical_job(tmp_path):
    context, _, _, remote, requests, logs = _evidence_context(tmp_path)
    ctx = context()
    out = tmp_path / "evidence"
    result = evidence.export_evidence(
        ctx, out, key="SYNTHETIC_KEY_NO_HTTP",
        fetch=_fake_evidence_fetch(remote, requests, logs))
    assert result["request_records"] == 101
    assert result["manifest_slots"] == 177
    assert len(result["missing_manifest_ids"]) == 1
    assert result["issues"]["job_not_normally_closed"] == 1
    assert result["issues"]["unreconciled_or_out_of_scope_url"] > 0
    assert result["approved_for_advisor"] is False
    assert evidence.replay_evidence(context(), out) == result
    (out / "requests.jl").write_bytes(b"")
    with pytest.raises(ValueError):
        evidence.replay_evidence(context(), out)


def test_p26b_export_refuses_truncated_requests_and_wrong_ordinals(tmp_path):
    context, _, _, remote, requests, logs = _evidence_context(tmp_path)
    out = tmp_path / "evidence"
    with pytest.raises(ValueError, match="official storage stats"):
        evidence.export_evidence(context(), out, key="SYNTHETIC_KEY_NO_HTTP",
                                 fetch=_fake_evidence_fetch(remote, requests, logs, stats_count=102))
    assert not out.exists()
    requests[50]["_key"] = requests[49]["_key"]
    with pytest.raises(ValueError, match="out-of-order"):
        evidence.export_evidence(context(), out, key="SYNTHETIC_KEY_NO_HTTP",
                                 fetch=_fake_evidence_fetch(remote, requests, logs))
    assert not out.exists()


def test_p26b_refuses_expired_at_dispatch_or_mismatched_job_receipt(tmp_path):
    context, attempt, accepted, *_ = _evidence_context(tmp_path)
    original = json.loads(attempt.read_text())
    expired = dict(original, attempted_at_utc=(NOW + timedelta(days=10)).isoformat())
    attempt.write_text(json.dumps(expired))
    with pytest.raises(ValueError):
        context()
    attempt.write_text(json.dumps(original))
    raw = json.loads(accepted.read_text())
    raw["job_id"] = "883514/99/999"
    accepted.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="scheduled P25 category"):
        context()


def test_p26b_reports_request_after_plan_expiry(tmp_path):
    context, _, _, remote, requests, logs = _evidence_context(tmp_path)
    ctx = context()
    # A hypothetical bad exported timestamp is a diagnostic, not permission.
    requests[0]["time"] = int((NOW + timedelta(hours=4)).timestamp() * 1000)
    result = evidence.export_evidence(ctx, tmp_path / "late", key="SYNTHETIC_KEY_NO_HTTP",
                                      fetch=_fake_evidence_fetch(remote, requests, logs))
    assert result["issues"]["primary_request_timestamp_outside_review_window"] == 1
    assert result["issues"]["request_outside_official_job_window"] == 1
