"""P07 read-only Zyte API pagination, immutable checksum verification and bounds."""

import gzip
import io
import json
import urllib.request

import pytest

from agentfuse_crawlers.sources import load_sources
from agentfuse_crawlers.run_context import manifest_sha256, selection_ids_sha256
from scripts.archive_jobs import (
    _job_details, _request, archive_job, archive_path, load_archive,
)
from scripts.download_zyte import download_job

SOURCES = {s["id"]: s for s in load_sources()}


def row(source_id, job_id, ordinal, status="captured"):
    source = SOURCES[source_id]
    return {
        "_key": f"{job_id}/{ordinal}", "source_id": source_id,
        "source_url": source["url"], "provider": source["provider"],
        "category": source["category"], "status": status,
        "zyte_job_id": job_id, "fetched_at_utc": "2026-10-31T08:30:00+00:00",
        "run_started_at_utc": "2026-10-31T08:00:00+00:00",
        "content_sha256": "sha-123", "schema_version": "2.1",
        "source_cohort": "proven", "requested_cohort": "proven",
        "selection_source_count": 2,
        "selection_ids_sha256": selection_ids_sha256([
            SOURCES["openai_api_changelog"], SOURCES["anthropic_api_changelog"]
        ]),
        "manifest_sha256": manifest_sha256(), "spider_name": "official_changelogs",
        "review_status": "unverified",
        "approved_for_advisor": False,
    }


def metadata(count=2, state="finished"):
    return {
        "state": state, "spider": "official_changelogs",
        "deploy_id": 20, "version": "deadbee", "finished_time": 1793430000000,
        "close_reason": "finished",
        "spider_args": {
            "cohort": "proven", "source_ids": "openai_api_changelog,anthropic_api_changelog",
            "secret_api_key": "NEVER_ARCHIVE_THIS_SECRET",
        },
        "scrapystats": {"item_scraped_count": count,
                        "elapsed_time_seconds": 13.1,
                        "agentfuse/coverage/missing_sources": 0},
    }


def make_archive(root, job="883514/1/42", rows=None, info=None):
    rows = rows if rows is not None else [
        row("openai_api_changelog", job, 0),
        row("anthropic_api_changelog", job, 1),
    ]
    info = info if info is not None else metadata(count=len(rows))
    calls = []

    def page(requested, key, start, count):
        calls.append((requested, start, count))
        return rows[start:start+count]

    target, envelope, mode = archive_job(
        job, root, api_key="secret-test", fetch_metadata=lambda *_: info,
        fetch_page=page,
    )
    return target, envelope, mode, calls


def test_immutable_archive_replay_and_idempotence_without_key(tmp_path, monkeypatch):
    job = "883514/1/42"
    target, envelope, mode, pages = make_archive(tmp_path)
    assert mode == "archived"
    assert pages == [(job, 0, 2)]
    assert envelope["source_summary_count"] == 2
    assert envelope["approved_for_advisor"] is False
    assert envelope["job"]["expected_item_count"] == 2
    assert envelope["source_scope"]["safe_for_semantic_diff"] is True
    assert "NEVER_ARCHIVE_THIS_SECRET" not in json.dumps(envelope)
    assert gzip.open(target / "items.jsonl.gz", "rt").read().count("\n") == 2

    monkeypatch.delenv("ZYTE_SCRAPY_CLOUD_API_KEY", raising=False)
    stored, rows = load_archive(target)
    assert len(rows) == 2
    assert stored["integrity"]["gzip_sha256"]
    second, again, mode = archive_job(job, tmp_path)
    assert second == target
    assert mode == "already_archived"
    assert again["integrity"] == envelope["integrity"]


def test_archive_detects_tampered_compressed_file(tmp_path):
    target, *_ = make_archive(tmp_path)
    file = target / "items.jsonl.gz"
    file.write_bytes(file.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="gzip checksum"):
        load_archive(target)
    with pytest.raises(ValueError, match="gzip checksum"):
        archive_job("883514/1/42", tmp_path, api_key="secret")


def test_archive_detects_damaged_index_and_missing_file(tmp_path):
    target, *_ = make_archive(tmp_path)
    index = target / "index.json"
    index.write_text('{"items":[]}')
    with pytest.raises(ValueError, match="index checksum"):
        load_archive(target)
    index.unlink()
    with pytest.raises(FileNotFoundError):
        load_archive(target)


def test_page_gap_and_out_of_order_keys_rejected_without_archive(tmp_path):
    job = "883514/1/52"
    rows = [row("openai_api_changelog", job, 1),
            row("anthropic_api_changelog", job, 0)]
    with pytest.raises(ValueError, match="out-of-order"):
        make_archive(tmp_path, job=job, rows=rows)
    assert not archive_path(tmp_path, job).exists()


def test_page_count_mismatch_and_duplicate_sources_fail_closed(tmp_path):
    job = "883514/1/53"
    one = [row("openai_api_changelog", job, 0)]
    with pytest.raises(ValueError, match="page count"):
        make_archive(tmp_path, job=job, rows=one,
                     info=metadata(count=2))
    repeat = [row("openai_api_changelog", job, 0),
              row("openai_api_changelog", job, 1)]
    with pytest.raises(ValueError, match="Duplicate source"):
        make_archive(tmp_path, job=job, rows=repeat)


def test_wrong_category_job_and_unverified_source_identity_rejected(tmp_path):
    job = "883514/1/54"
    rows = [row("openai_api_docs", job, 0),
            row("anthropic_api_changelog", job, 1)]
    with pytest.raises(ValueError, match="mismatched source ID/category"):
        make_archive(tmp_path, job=job, rows=rows)
    rows[0]["category"] = "changelog"
    with pytest.raises(ValueError, match="mismatched source ID/category"):
        make_archive(tmp_path, job=job, rows=rows)


def test_missing_metadata_count_non_finished_job_and_wrong_spider_rejected(tmp_path):
    info = metadata()
    info["state"] = "running"
    with pytest.raises(ValueError, match="not finished"):
        make_archive(tmp_path, job="883514/1/55", info=info)
    info["state"] = "finished"
    info["scrapystats"].pop("item_scraped_count")
    with pytest.raises(ValueError, match="item_scraped_count"):
        make_archive(tmp_path, job="883514/1/55", info=info)
    info["scrapystats"]["item_scraped_count"] = 2
    info["spider"] = "unapproved_spider"
    with pytest.raises(ValueError, match="Unrecognized spider"):
        make_archive(tmp_path, job="883514/1/55", info=info)


def test_bad_job_id_and_missing_credentials_before_http(tmp_path, monkeypatch):
    for value in ("../x", "https://evil.invalid", "a/b/c", "1/2/3?foo=key"):
        with pytest.raises(ValueError, match="job-id"):
            download_job(value, tmp_path, api_key="bogus")
    monkeypatch.delenv("ZYTE_SCRAPY_CLOUD_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ZYTE_SCRAPY_CLOUD_API_KEY"):
        download_job("883514/1/77", tmp_path)


def test_secret_passed_only_in_authorization_header_never_url(monkeypatch):
    captured = {}

    class FakeOpener:
        def open(self, req, timeout=0):
            captured["url"] = req.full_url
            captured["authorization"] = req.get_header("Authorization")
            return io.BytesIO(b'{"state":"finished"}')

    monkeypatch.setattr(urllib.request, "build_opener",
                        lambda *_: FakeOpener())
    raw = _request("https://storage.zyte.com/jobs/1/2/3",
                   "PRIVATE-KEY-FOR-TEST", 200)
    assert json.loads(raw)["state"] == "finished"
    assert captured["url"] == "https://storage.zyte.com/jobs/1/2/3"
    assert "PRIVATE-KEY-FOR-TEST" not in captured["url"]
    assert captured["authorization"].startswith("Basic ")
    with pytest.raises(ValueError, match="official Zyte"):
        _request("https://untrusted.invalid/secret", "password", 100)


def test_metadata_sanitizes_unknown_args_without_storing_values():
    report = _job_details("883514/1/5", metadata())
    assert report["unrecorded_argument_names"] == ["secret_api_key"]
    assert "secret" not in str(report["spider_args"])


def test_job_returns_only_closed_official_metadata_and_fixed_three_spiders():
    for spider in (
        "official_documentation", "official_pricing", "official_changelogs"
    ):
        info = metadata(0)
        info["spider"] = spider
        assert _job_details("883514/1/10", info)["spider"] == spider


def test_empty_finished_job_archived_as_unusable_not_made_success(tmp_path):
    info = metadata(0)
    info["close_reason"] = "agentfuse_no_usable_sources"
    target, data, mode, _ = make_archive(
        tmp_path, job="883514/1/92", rows=[], info=info
    )
    assert data["source_summary_count"] == 0
    assert data["source_scope"]["scope_count_matches_items"] is False
    assert load_archive(target)[1] == []


def test_real_pagination_21_items_uses_start_and_count_without_gaps(tmp_path):
    sources = [s for s in load_sources() if s["category"] == "changelog"][:21]
    job = "883514/1/97"
    rows = [row(source["id"], job, n) for n, source in enumerate(sources)]
    selected_hash = selection_ids_sha256(sources)
    for item in rows:
        item["selection_ids_sha256"] = selected_hash
        item["selection_source_count"] = len(rows)
    target, report, result, calls = make_archive(
        tmp_path, job=job, rows=rows, info=metadata(count=21)
    )
    assert result == "archived"
    assert calls == [(job, 0, 20), (job, 20, 1)]
    assert report["source_scope"]["safe_for_semantic_diff"] is True
    assert len(load_archive(target)[1]) == 21


def test_mismatched_first_party_url_archived_but_never_comparable(tmp_path):
    job = "883514/1/98"
    data = [row("openai_api_changelog", job, 0),
            row("anthropic_api_changelog", job, 1)]
    data[0]["source_url"] = "https://invalid.example/changed-scope"
    _, report, _, _ = make_archive(tmp_path, job=job, rows=data)
    assert report["source_scope"]["source_identity_mismatches"] == 1
    assert report["source_scope"]["safe_for_semantic_diff"] is False


def test_archive_finished_but_nonstandard_close_reason_is_not_comparable(tmp_path):
    job = "883514/1/99"
    info = metadata()
    info["close_reason"] = "closespider_error"
    _, report, _, _ = make_archive(tmp_path, job=job, info=info)
    assert report["source_scope"]["safe_for_semantic_diff"] is False


def test_envelope_cannot_be_edited_to_fake_semantic_comparability(tmp_path):
    target, envelope, *_ = make_archive(tmp_path)
    path = target / "envelope.json"
    metadata = json.loads(path.read_text())
    metadata["source_scope"]["safe_for_semantic_diff"] = False
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="scope/provenance metadata mismatch"):
        load_archive(target)


def test_envelope_summary_count_forgery_detected(tmp_path):
    target, envelope, *_ = make_archive(tmp_path)
    path = target / "envelope.json"
    metadata = json.loads(path.read_text())
    metadata["source_summary_count"] = 999
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="summary count"):
        load_archive(target)
