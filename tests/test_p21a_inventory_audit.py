"""P21A synthetic evidence audit negative cases. No publisher calls."""
import csv
import hashlib
import json
import os
from copy import deepcopy

import pytest

from agentfuse_crawlers.run_context import manifest_sha256, selection_ids_sha256
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources, select_sources
from scripts.audit_nov04_inventory import (
    BASELINES, MANIFEST_SHA, PACKAGE_SHA, REGISTRY_SHA,
    _csv_bytes, _raw_exports, _holdout, audit_bundle, write_private_audit,
    SOURCE_FIELDS, REQUEST_FIELDS,
)

KEY = "synthetic-p21a-private-holdout-seed-not-a-publisher-key-2026"


def fake_bundle():
    all_sources = load_sources()
    assert manifest_sha256(all_sources) == MANIFEST_SHA
    assert registry_revision_sha256() == REGISTRY_SHA
    data = {}
    for category, baseline in BASELINES.items():
        selected = select_sources(category, "all")
        items, requests = [], []
        for source in selected:
            sid = source["id"]
            held = sid in {"v0_docs", "v0_pricing", "v0_changelog"}
            item = {
                "source_id": sid,
                "source_url": source["url"],
                "provider": source["provider"],
                "category": category,
                "spider_name": baseline["spider"],
                "zyte_job_id": baseline["job"],
                "requested_cohort": "all",
                "selection_source_count": baseline["count"],
                "selection_ids_sha256": selection_ids_sha256(selected),
                "manifest_sha256": MANIFEST_SHA,
                "source_registry_sha256": REGISTRY_SHA,
                "deployment_revision": PACKAGE_SHA,
                "deployment_revision_kind": "package_py_json_sha256_v1",
                "deployment_source_revision_claim": "",
                "collection_mode": "validation",
                "run_scope_explicit": True,
                "review_status": "unverified",
                "approved_for_advisor": False,
                "status": "source_quarantined" if held else "needs_review",
                "http_status": None if held else 200,
                "source_policy_status": (
                    "unresolved" if held else "not_reviewed"
                ),
                "source_lifecycle_state": (
                    "quarantined" if held else "needs_validation"
                ),
                "diagnostic_reason_codes": [
                    "policy_unresolved_or_quarantined" if held
                    else "unverified_source_quality"
                ],
                "error": "",
                "final_url": "" if held else source["url"],
                "content_sha256": None if held else "a"*64,
                "pricing_observation_count": 0,
                "pricing_observation_total_detected": 0,
                "pricing_observations": [],
                "pricing_inventory_complete": False,
                "release_event_count": 0,
                "release_recent_event_count": 0,
                "release_events": [],
                "release_window_complete": False,
                "documentation_scope_status": "scope_not_established",
            }
            items.append(item)
            if not held:
                requests.append({
                    "time": 1793798700100 + len(requests) * 100,
                    "duration": 20,
                    "status": 200, "method": "GET", "rs": 1000,
                    "url": source["url"],
                    "fp": hashlib.sha1(sid.encode()).hexdigest(),
                })
        log = [
            {"time": 1793798700000, "level": 20,
             "message": f"Starting {category}: {baseline['count']} configured URLs"},
            {"time": 1793798800000, "level": 20,
             "message": ("'agentfuse/coverage/expected_sources': "
                         f"{baseline['count']}, 'agentfuse/coverage/reported_sources': "
                         f"{baseline['count']}, 'agentfuse/coverage/captured_sources': 0")},
            {"time": 1793798900000, "level": 20,
             "message": "[scrapy.core.engine] Spider closed (finished)"},
        ]
        data[category] = {"items": items, "requests": requests, "log": log}
    return data


def test_synthetic_full_460_source_accounting_and_two_distinct_reports():
    data = fake_bundle()
    audit, rows, requests, groups, holdout = audit_bundle(
        data, holdout_key=KEY,
    )
    assert audit["operational_run_integrity"]["accounted_source_count"] == 460
    assert audit["operational_run_integrity"]["source_accounting_complete"]
    assert audit["operational_run_integrity"][
        "complete_immutable_zyte_archives_authenticated"
    ] is False
    assert not audit["evidence_and_semantic_quality"]["accuracy_established"]
    assert audit["evidence_and_semantic_quality"]["advisor_fact_approvals"] == 0
    assert len(rows) == 460
    assert len(requests) == 457
    assert sum(g["count"] for g in groups["groups"].values()) == 460
    assert holdout["source_count"] == 18
    assert all(len(ids) == 6 for ids in holdout["categories"].values())
    assert sum(not x["rank"] for x in rows) == 18
    assert audit["input_integrity"]["nine_original_export_sha256_pins_checked"] is False
    assert audit["network_requests_performed"] == audit["new_zyte_jobs"] == 0


def test_holdout_is_reproducible_but_private_and_independent_of_parser_results():
    src = load_sources()
    a = _holdout(src, KEY)
    b = _holdout(list(reversed(src)), KEY)
    assert a == b
    assert KEY not in json.dumps(a)
    assert a["selection_before_new_parser_replay"] is True
    assert a["source_count"] == 18
    assert a["holdout_sha256"] == hashlib.sha256(json.dumps(
        {k: v for k, v in a.items() if k != "holdout_sha256"},
        sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    with pytest.raises(ValueError, match=">=32"):
        _holdout(src, "too-short")


@pytest.mark.parametrize(("attack", "expected"), [
    ("drop_source", "count mismatch"),
    ("duplicate_source", "duplicated or unknown"),
    ("change_source_url", "trust violated"),
    ("claim_fact_approved", "trust violated"),
    ("change_manifest", "trust violated"),
    ("change_registry", "trust violated"),
    ("change_package", "trust violated"),
    ("change_job", "trust violated"),
    ("change_selection_hash", "trust violated"),
    ("change_cohort", "trust violated"),
    ("change_spider", "trust violated"),
    ("change_status_http", "non-200"),
    ("missing_request", "missing initial GET"),
    ("bad_final_response", "No final URL"),
    ("fake_quarantine_request", "source GET"),
    ("fake_price_source", "Unbound pricing observation"),
    ("fake_log_capture", "captured count differs"),
    ("missing_log", "Request trace and finished"),
])
def test_synthetic_malformed_json_and_provenance_fail_closed(attack, expected):
    data = fake_bundle()
    category = "pricing"
    item = next(x for x in data[category]["items"]
                if x["source_id"] != "v0_pricing")
    if attack == "drop_source":
        data[category]["items"].pop()
    elif attack == "duplicate_source":
        data[category]["items"][-1]["source_id"] = item["source_id"]
    elif attack == "change_source_url":
        item["source_url"] = "https://hostile.invalid/pricing"
    elif attack == "claim_fact_approved":
        item["approved_for_advisor"] = True
    elif attack == "change_manifest":
        item["manifest_sha256"] = "a"*64
    elif attack == "change_registry":
        item["source_registry_sha256"] = "b"*64
    elif attack == "change_package":
        item["deployment_revision"] = "c"*64
    elif attack == "change_job":
        item["zyte_job_id"] = "123/4/5"
    elif attack == "change_selection_hash":
        item["selection_ids_sha256"] = "d"*64
    elif attack == "change_cohort":
        item["requested_cohort"] = "proven"
    elif attack == "change_spider":
        item["spider_name"] = "other"
    elif attack == "change_status_http":
        item["http_status"] = 403
    elif attack == "missing_request":
        data[category]["requests"] = [
            q for q in data[category]["requests"]
            if q["url"] != item["source_url"]
        ]
    elif attack == "bad_final_response":
        item["final_url"] = "https://notactuallyfetched.invalid"
    elif attack == "fake_quarantine_request":
        quarantined = next(
            x for x in data[category]["items"] if x["source_id"] == "v0_pricing"
        )
        data[category]["requests"].append({
            "time": 1793799800000, "duration": 10, "status": 200,
            "method": "GET", "rs": 1000,
            "url": quarantined["source_url"],
        })
    elif attack == "fake_price_source":
        item["pricing_observation_count"] = 1
        item["pricing_observation_total_detected"] = 1
        item["pricing_observations"] = [{
            "source_id": "wrong", "source_url": item["source_url"],
            "approved_for_advisor": False,
        }]
    elif attack == "fake_log_capture":
        data[category]["log"][1]["message"] = (
            "'agentfuse/coverage/expected_sources': 177, "
            "'agentfuse/coverage/reported_sources': 177, "
            "'agentfuse/coverage/captured_sources': 5"
        )
    elif attack == "missing_log":
        data[category]["log"] = []
    with pytest.raises(ValueError, match=expected):
        audit_bundle(data, holdout_key=KEY)


def test_two_stage_same_host_redirect_uses_final_request_not_initial_308():
    data = fake_bundle()
    item = next(x for x in data["documentation"]["items"]
                if x["source_id"] == "anthropic_api_docs")
    reqs = data["documentation"]["requests"]
    first = next(x for x in reqs if x["url"] == item["source_url"])
    first["status"] = 308
    final = item["source_url"].rstrip("/") + "/guide"
    item["final_url"] = final
    reqs.append({
        "time": first["time"] + 100, "duration": 80,
        "status": 200, "method": "GET", "rs": 2500, "url": final,
        "parent": 0,
    })
    report, rows, req_rows, *_ = audit_bundle(data, holdout_key=KEY)
    observed = next(x for x in rows if x["source_id"] == item["source_id"])
    assert observed["request_chain_status"] == "same_run_redirect_chain_observed"
    assert observed["final_response_matched"] is True
    assert any(x["request_class"] == "redirected_final_request" for x in req_rows)


def test_source_json_export_exact_pinned_sha_and_symlink_rejection(tmp_path):
    fake = tmp_path / "files"
    fake.mkdir()
    name = "items_official_pricing_11.json"
    (fake / name).write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        _raw_exports(fake)
    link = tmp_path / "symlink"
    try:
        link.symlink_to(fake, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks not supported")
    with pytest.raises(ValueError, match="symlink"):
        _raw_exports(link)


def test_offline_writes_are_private_non_overwriting_and_csv_safe(tmp_path):
    outputs = audit_bundle(fake_bundle(), holdout_key=KEY)
    root = tmp_path / "p21a-private"
    assert write_private_audit(outputs, root) == root
    files = sorted(p.name for p in root.iterdir())
    assert files == [
        "README.md", "baseline_metrics.json", "holdout_source_ids_PRIVATE.json",
        "request_outcomes.csv", "risk_clusters.json", "source_triage.csv",
    ]
    with (root / "source_triage.csv").open(
        encoding="utf-8-sig", newline=""
    ) as f:
        assert len(list(csv.DictReader(f))) == 460
    with (root / "request_outcomes.csv").open(
        encoding="utf-8-sig", newline=""
    ) as f:
        assert len(list(csv.DictReader(f))) == 457
    if os.name == "posix":
        assert root.stat().st_mode & 0o777 == 0o700
        assert all(p.stat().st_mode & 0o777 == 0o600
                   for p in root.iterdir())
    with pytest.raises(ValueError, match="NEW"):
        write_private_audit(outputs, root)
    assert b"'=2+4" in _csv_bytes(
        SOURCE_FIELDS, [{name: "=2+4" for name in SOURCE_FIELDS}]
    )
