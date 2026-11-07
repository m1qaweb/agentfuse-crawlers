"""P23C3A: synthetic only read-only Zyte job export regression tests.

The injected client NEVER makes a real Zyte or publisher request.
Fictional source reviews do not authorize real publisher collection.
"""
import hashlib
import json
import stat
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest

import agentfuse_crawlers.validation_access as access
from agentfuse_crawlers.run_context import (
    manifest_sha256, package_fingerprint, selection_ids_sha256,
)
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import load_sources
from scripts.archive_jobs import archive_job, archive_path
from scripts.p23c1_zyte_canary_archive_gate import blank_receipts
from scripts.p23c2_zyte_requests_logs_html_gate import audit_evidence
from scripts.p23c3a_download_completed_zyte_evidence import (
    _download_paged, _parse_page, _preflight,
    download_existing_job_evidence,
)

NOW = datetime(2026, 11, 7, 13, 0, tzinfo=timezone.utc)
NOTE = (
    "Synthetic code test only, not legal permission to access a real site. "
    "Real source review must check ownership, publisher terms, robots and "
    "retention before any source-specific crawl is independently approved."
)


def ts(delta=timedelta()):
    return (NOW + delta).isoformat(timespec="seconds")


def ms(delta=timedelta()):
    return int((NOW + delta).timestamp() * 1000)


def first_source():
    from scripts.accession_cross_category_html import frozen_plan
    sid = frozen_plan()["sources"][0]["source_id"]
    return next(x for x in load_sources() if x["id"] == sid)


def synthetic_policy(source):
    host = urllib.parse.urlsplit(source["url"]).hostname
    data = {
        "schema_version": access.SCHEMA,
        "kind": access.ACCESS_KIND,
        "default_decision": "not_reviewed",
        "reviews": {
            source["id"]: {
                "source_url": source["url"],
                "category": source["category"],
                "decision": "allowed_reviewed",
                "scopes": ["single_validation"],
                "reviewed_by": "Fictional Test Reviewer",
                "reviewed_at_utc": ts(timedelta(days=-2)),
                "expires_at_utc": ts(timedelta(days=2)),
                "ownership_evidence_url": source["url"],
                "publisher_access_policy_url": "https://" + host + "/terms",
                "robots_url": "https://" + host + "/robots.txt",
                "publisher_terms_reviewed": True,
                "robots_reviewed": True,
                "private_retention_reviewed": True,
                "evidence_note": NOTE,
            },
        },
    }
    access.validate_access_registry(data, now=NOW)
    return data


def make_meta(source, count, *, job_id="883514/1/2001"):
    return {
        "state": "finished",
        "spider": {
            "documentation": "official_documentation",
            "pricing": "official_pricing",
            "changelog": "official_changelogs",
        }[source["category"]],
        "close_reason": "finished",
        "scrapystats": {
            "item_scraped_count": 1,
            "downloader/request_count": count,
        },
        "spider_args": {
            "cohort": "all",
            "source_ids": source["id"],
            "collection_mode": "validation",
            "expected_manifest_sha256": manifest_sha256(),
            "expected_selection_ids_sha256": selection_ids_sha256([source]),
            "expected_source_registry_sha256": registry_revision_sha256(),
        },
        "version": "synthetic-xy-package-1",
        "deploy_id": "synthetic-only-deployment",
    }


def make_archive(root, source, policy, job_id, count):
    meta = make_meta(source, count, job_id=job_id)
    item = {
        "_key": job_id + "/0",
        "source_id": source["id"],
        "source_url": source["url"],
        "provider": source["provider"],
        "category": source["category"],
        "spider_name": meta["spider"],
        "collection_mode": "validation",
        "validation_scope": "single_exact_source",
        "single_validation_access_required": True,
        "bulk_validation_required": False,
        "run_scope_explicit": True,
        "selection_source_count": 1,
        "selection_ids_sha256": selection_ids_sha256([source]),
        "manifest_sha256": manifest_sha256(),
        "source_registry_sha256": registry_revision_sha256(),
        "bulk_access_registry_sha256":
            access.validation_access_revision_sha256(policy),
        "deployment_revision": package_fingerprint(),
        "zyte_job_id": job_id,
        "run_started_at_utc": ts(timedelta(minutes=-35)),
        "http_status": 200,
        "status": "captured",
        "final_url": source["url"],
        "approved_for_advisor": False,
    }
    archive_job(
        job_id, root, api_key="SYNTHETIC_TEST_NOT_CREDENTIAL",
        fetch_metadata=lambda *_: meta,
        fetch_page=lambda *_: [item],
    )
    return meta


def robots(source):
    p = urllib.parse.urlsplit(source["url"])
    return p._replace(path="/robots.txt", query="", fragment="").geturl()


def req(source, url, delta=timedelta(minutes=-35, seconds=2)):
    return {
        "time": ms(delta), "method": "GET",
        "url": url, "status": 200, "duration": 35, "rs": 1100,
    }


def log(idx=0, *, secret=None):
    return {
        "time": ms(timedelta(minutes=-35, seconds=3+idx)),
        "level": 20, "message": (
            "SYNTHETIC-PRIVATE-STRING-" + str(idx)
            if secret is None else secret
        ),
    }


class FakeZyte:
    def __init__(self, job_id, meta, reqs, logs):
        self.job_id = job_id
        self.meta = meta
        self.reqs = reqs
        self.logs = logs
        self.calls = []
        self.mutations = {}

    def __call__(self, url, key, limit):
        assert key == "SYNTHETIC_NOT_A_SECRET"
        assert url.startswith("https://storage.zyte.com/")
        assert "/api/run" not in url
        assert "/api/deploy" not in url
        self.calls.append(url)
        if url in self.mutations:
            return self.mutations[url]
        path = urllib.parse.urlsplit(url)
        if path.path == "/jobs/" + self.job_id:
            return json.dumps(self.meta).encode("utf-8")
        if path.path == "/requests/" + self.job_id + "/stats":
            return json.dumps({
                "totals": {"input_values": len(self.reqs), "input_bytes": 200},
                "counts": {"url": len(self.reqs)},
            }).encode("utf-8")
        for kind, rows in (("requests", self.reqs), ("logs", self.logs)):
            if path.path == "/" + kind + "/" + self.job_id:
                params = urllib.parse.parse_qs(path.query)
                assert params["format"] == ["jl"]
                assert params["meta"] == ["_key"]
                count = int(params["count"][0])
                start = params["start"][0]
                assert start.startswith(self.job_id + "/")
                index = int(start.split("/")[-1])
                batch = rows[index:index+count]
                return ("".join(json.dumps({
                    "_key": f"{self.job_id}/{index + i}", **row,
                }) + "\n" for i, row in enumerate(batch))).encode("utf-8")
        raise AssertionError("The client tried an unreviewed Zyte endpoint")


def fixture(tmp_path, *, job_id="883514/1/2001", count=2,
            num_logs=2):
    source = first_source()
    pol = synthetic_policy(source)
    receipts = blank_receipts()
    receipts["rows"][0]["rounds"][0]["zyte_job_id"] = job_id
    archive_root = tmp_path / "archive"
    meta = make_archive(archive_root, source, pol, job_id, count=count)
    requests = [req(source, robots(source)), req(source, source["url"])]
    while len(requests) < count:
        requests.append(req(source, source["url"]))
    logs = [log(i) for i in range(num_logs)]
    client = FakeZyte(job_id, meta, requests, logs)
    return receipts, archive_root, source, pol, client


def download(args, tmp_path, **kwargs):
    receipts, archive_root, source, pol, client = args
    return download_existing_job_evidence(
        receipts, archive_root, tmp_path / "private",
        source["id"], api_key="SYNTHETIC_NOT_A_SECRET",
        fetch=client, now=NOW, access_registry=pol, **kwargs,
    )


def test_preflight_is_offline_and_rejects_missing_real_source_reviews(tmp_path):
    receipts, archive_root, source, pol, client = fixture(tmp_path)
    report, jobs = _preflight(receipts, archive_root, source["id"],
                              access_registry=pol, now=NOW)
    assert jobs == [client.job_id]
    assert report["status"] == "NO_GO"
    assert client.calls == []
    denied = {
        "schema_version": access.SCHEMA,
        "kind": access.ACCESS_KIND,
        "default_decision": "not_reviewed", "reviews": {},
    }
    with pytest.raises(ValueError):
        download_existing_job_evidence(
            receipts, archive_root, tmp_path / "fail",
            source["id"], api_key="SYNTHETIC_NOT_A_SECRET",
            fetch=client, access_registry=denied, now=NOW,
        )
    assert client.calls == []
    assert not (tmp_path / "fail").exists()


def test_readonly_download_produces_p23c2_index_and_18_36_accounting(tmp_path):
    args = fixture(tmp_path)
    out, report, index = download(args, tmp_path)
    source = args[2]
    client = args[-1]
    assert report["source_rounds_downloaded"] == 1
    assert report["new_zyte_jobs"] == report["new_publisher_requests"] == 0
    assert report["publisher_response_html_proven"] is False
    assert report["full_inventory_go"] is False
    assert report["approved_for_advisor"] is False
    assert len(index["rows"]) == 18
    assert sum(len(x["rounds"]) for x in index["rows"]) == 36
    assert index["rows"][0]["rounds"][0]["zyte_job_id"] == client.job_id
    assert index["rows"][0]["rounds"][1]["zyte_job_id"] is None
    assert all(
        row["rounds"][n]["requests"] is None
        for row in index["rows"][1:] for n in (0, 1)
    )
    jobdir = client.job_id.replace("/", "_")
    requests_file = out / jobdir / "requests.jl"
    logs_file = out / jobdir / "logs.jl"
    assert requests_file.is_file() and logs_file.is_file()
    assert stat.S_IMODE(requests_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(logs_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    assert hashlib.sha256(logs_file.read_bytes()).hexdigest() == (
        index["rows"][0]["rounds"][0]["logs"]["sha256"]
    )
    assert all(x.startswith("https://storage.zyte.com/")
               for x in client.calls)
    assert any("/requests/" in x and "/stats" in x for x in client.calls)
    assert any("/logs/" in x and "meta=_key" in x for x in client.calls)
    assert any("/jobs/" in x for x in client.calls)
    assert len(client.calls) == 4
    private_report = (out / "read_only_completed_job_export_receipt_NOT_GO.json"
                      ).read_text()
    assert "SYNTHETIC_NOT_A_SECRET" not in private_report
    assert "SYNTHETIC-PRIVATE-STRING-" not in private_report
    assert report["report_sha256"] == access.digest({
        k: v for k, v in report.items() if k != "report_sha256"
    })
    c2, rows = audit_evidence(
        args[0], index, args[1], out,
        now=NOW, access_registry=args[3],
    )
    assert len(rows) == 36
    assert c2["source_rounds_with_requests_export"] == 1
    assert c2["source_rounds_with_logs_export"] == 1
    assert c2["source_rounds_with_evidence_issues"] == 0
    assert rows[0]["source_round_evidence_state"] == (
        "requests_logs_consistent_HTML_NOT_SUPPLIED"
    )
    assert c2["status"] == "NO_GO"


def test_pagination_matches_full_ordinal_without_dropping_logs(tmp_path):
    args = fixture(tmp_path, count=45, num_logs=81)
    out, report, index = download(args, tmp_path)
    assert report["completed_jobs"][0]["requests_exported"] == 45
    assert report["completed_jobs"][0]["logs_exported"] == 81
    client = args[-1]
    urls = client.calls
    assert sum("/requests/" in x and "stats" not in x for x in urls) == 2
    assert sum("/logs/" in x for x in urls) == 3
    job = client.job_id.replace("/", "_")
    assert len((out / job / "requests.jl").read_text().splitlines()) == 45
    assert len((out / job / "logs.jl").read_text().splitlines()) == 81
    assert index["rows"][0]["rounds"][0]["logs"]["sha256"]


def test_private_logs_containing_sensitive_messages_never_appear_in_output(tmp_path):
    args = fixture(tmp_path)
    args[-1].logs = [log(secret="CONFIDENTIAL_JOB_ERROR_EXAMPLE")]
    out, report, _index = download(args, tmp_path)
    assert "CONFIDENTIAL_JOB_ERROR_EXAMPLE" not in json.dumps(report)
    job = args[-1].job_id.replace("/", "_")
    assert "CONFIDENTIAL_JOB_ERROR_EXAMPLE" in (
        out / job / "logs.jl"
    ).read_text()


@pytest.mark.parametrize("damage", [
    "metadata_spider_changed",
    "metadata_state_running",
    "requests_stats_missing",
    "requests_stats_wrong",
    "missing_ordinal",
    "duplicate_ordinal",
    "unexpected_host",
    "bad_request",
    "bad_log",
    "max_rows",
])
def test_tampered_or_incomplete_remote_evidence_refused_without_partial_files(
        tmp_path, damage):
    args = fixture(tmp_path)
    client = args[-1]
    job = client.job_id
    req_url = (
        "https://storage.zyte.com/requests/" + job +
        "?format=jl&meta=_key&count=32&start=" + job + "/0"
    )
    if damage == "metadata_spider_changed":
        client.meta["spider"] = "wrong_spider"
    elif damage == "metadata_state_running":
        client.meta["state"] = "running"
    elif damage == "requests_stats_missing":
        client.mutations["https://storage.zyte.com/requests/" + job +
                         "/stats"] = b'{"totals":{}}'
    elif damage == "requests_stats_wrong":
        client.reqs.append(req(args[2], args[2]["url"]))
        client.mutations["https://storage.zyte.com/requests/" + job +
                         "/stats"] = b'{"totals":{"input_values":1}}'
    elif damage == "missing_ordinal":
        client.mutations[req_url] = (
            json.dumps({"_key": job + "/7", **client.reqs[0]}) + "\n"
        ).encode("utf-8")
    elif damage == "duplicate_ordinal":
        client.mutations[req_url] = (
            json.dumps({"_key": job + "/0", **client.reqs[0]}) + "\n"
            + json.dumps({"_key": job + "/0", **client.reqs[1]}) + "\n"
        ).encode("utf-8")
    elif damage == "unexpected_host":
        client.mutations[req_url] = b""
        client.mutations["https://storage.zyte.com/requests/" + job +
                         "/stats"] = b'{"totals":{"input_values":2}}'
    elif damage == "bad_request":
        client.reqs[0]["status"] = "200"
    elif damage == "bad_log":
        client.logs[0]["level"] = 99
    else:
        client.reqs = [req(args[2], args[2]["url"]) for _ in range(97)]
    with pytest.raises(ValueError):
        download(args, tmp_path)
    assert not (tmp_path / "private").exists()


def test_existing_output_refused_before_remote_reads(tmp_path):
    args = fixture(tmp_path)
    (tmp_path / "private").mkdir()
    with pytest.raises(ValueError, match="NEW private"):
        download(args, tmp_path)
    assert args[-1].calls == []


def test_wrong_source_or_missing_key_refused_before_remote_reads(tmp_path):
    args = fixture(tmp_path)
    receipts, archive_root, source, pol, client = args
    with pytest.raises(ValueError):
        download_existing_job_evidence(
            receipts, archive_root, tmp_path / "bad-source",
            "not_an_original_canary_id",
            api_key="SYNTHETIC_NOT_A_SECRET",
            fetch=client, access_registry=pol, now=NOW,
        )
    with pytest.raises(ValueError, match="Scrapy Cloud API key"):
        download_existing_job_evidence(
            receipts, archive_root, tmp_path / "bad-key",
            source["id"], api_key="", fetch=client,
            access_registry=pol, now=NOW,
        )
    assert client.calls == []


def test_page_rejects_wrong_ordinal_and_non_object():
    with pytest.raises(ValueError, match="out-of-order"):
        _parse_page(
            b'{"_key":"883514/1/100/19","level":20,"message":"test"}\n',
            "logs", "883514/1/100", 0, 40,
        )
    with pytest.raises(ValueError, match="object"):
        _parse_page(b'{"_key":"883514/1/100/0"}\n' if False else
                    b'[]\n', "logs", "883514/1/100", 0, 40)
