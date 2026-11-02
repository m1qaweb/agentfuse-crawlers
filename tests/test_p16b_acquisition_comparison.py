"""P16B synthetic captures only; no publisher fact/policy or Zyte requests."""
import hashlib
import json
from copy import deepcopy
from datetime import datetime

import pytest

from agentfuse_crawlers import acquisition_experiments as registry
from agentfuse_crawlers.sources import load_sources
from scripts.compare_acquisition_snapshots import (
    compare_acquisition_snapshots, write_acquisition_report,
)

KNOWN = {s["id"]: s for s in load_sources()}
SCOPE = "approved_for_advisor"


def _static_docs(title):
    return (
        "<html><head><title>" + title + "</title></head><body><main>"
        "<h1>" + title + "</h1>"
        "<div id='root'>Loading documentation...</div>"
        "</main></body></html>"
    )


def _rendered_docs(title="Kiro"):
    return (
        "<html><head><title>" + title + " Docs</title></head><body><main>"
        "<h1>" + title + "</h1><h2 id='mcp'>MCP servers and tools</h2>"
        "<p>These synthetic technical documentation paragraphs describe "
        "how model context protocol servers can be configured through "
        "specific tool settings in the application, including permissions "
        "and configuration details which are needed for a correct "
        "integration. Source evidence must still be confirmed independently "
        "before describing any capability as actually available.</p>"
        "<p>Further details cover authentication prerequisites, account "
        "permissions, connector settings and operational limitations. "
        "The synthetic example is for the regression tests only and does "
        "not document any genuine product behavior or paid feature tier.</p>"
        "</main></body></html>"
    )


def _pricing_basic():
    return (
        "<html><head><title>Gemini API Pricing</title></head><body><main>"
        "<h1>Gemini API pricing</h1><p>Plan and usage details are available "
        "in the full pricing tables referenced from this page.</p>"
        "</main></body></html>"
    )


def _pricing_rendered():
    return (
        "<html><head><title>Gemini API Pricing</title></head><body><main>"
        "<h1>Gemini API pricing</h1>"
        "<h2>Region: Global</h2><h3>Tier: Standard</h3>"
        "<table><caption>USD per 1M tokens</caption><thead><tr>"
        "<th>Model</th><th>Input price</th><th>Output price</th>"
        "</tr></thead><tbody>"
        "<tr><th>Model Alpha</th><td>$1.50</td><td>$4.50</td></tr>"
        "</tbody></table>"
        "<p>All values above are purely synthetic integration-test values."
        " They do not represent any real publisher model rates.</p>"
        "</main></body></html>"
    )


def _release_static():
    return (
        "<html><head><title>Claude Code changelog</title></head>"
        "<body><main><h1>Claude Code Changelog</h1>"
        "<p>See the official version history for detailed updates.</p>"
        "</main></body></html>"
    )


def _release_markdown():
    return (
        "# Claude Code changelog\n"
        "## 2.3.1\n"
        "- Improved synthetic tool startup reliability.\n"
        "- Fixed a synthetic application launch issue.\n\n"
        "## 2.3.0\n"
        "- Added a synthetic example of a configuration option.\n"
        "- This test does not claim a publication date.\n"
    )


def _capture(root, source_id, content, role, *, method, capture_at,
             url):
    suffix = ".md" if method == "official_markdown" else ".html"
    path = root / f"{source_id}_{role}{suffix}"
    path.write_bytes(content.encode("utf-8"))
    return {
        "file": path.name,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "request_url": url,
        "final_url": url,
        "http_status": 200,
        "media_type": ("text/markdown" if method == "official_markdown"
                       else "text/html"),
        "capture_method": method,
        "captured_at_utc": capture_at,
        "capture_origin_review_status": "operator_supplied_unverified",
    }


def pair(root, sid, static, alternate):
    exp = registry.load_acquisition_experiments()[sid]
    return {
        "experiment_id": exp["experiment_id"],
        "source_id": sid,
        "static_html": _capture(
            root, sid, static, "original", method="static_html",
            url=KNOWN[sid]["url"], capture_at="2026-11-02T11:00:00Z",
        ),
        "alternate": _capture(
            root, sid, alternate, "alternate",
            method=exp["candidate_acquisition_method"],
            url=exp["candidate_url"],
            capture_at="2026-11-02T11:09:00+00:00",
        ),
    }


def manifest(pairs):
    return {
        "schema_version": "1.0",
        "approved_for_advisor": False,
        "pairs": pairs,
    }


@pytest.fixture
def scenarios(tmp_path):
    root = tmp_path / "private_raw_snapshots"
    root.mkdir()
    docs = pair(
        root, "kiro_docs", _static_docs("Kiro"), _rendered_docs(),
    )
    price = pair(
        root, "gemini_api_pricing", _pricing_basic(), _pricing_rendered(),
    )
    release = pair(
        root, "claude_code_changelog", _release_static(),
        _release_markdown(),
    )
    return root, manifest([docs, price, release])


def test_registry_exact_pins_and_no_automatic_rendering():
    records = registry.load_acquisition_experiments()
    assert len(load_sources()) == 460
    assert len(records) == 8
    assert len(registry.acquisition_registry_sha256()) == 64
    assert sum(x["candidate_acquisition_method"] == "rendered_html"
               for x in records.values()) == 7
    assert sum(x["candidate_acquisition_method"] == "official_markdown"
               for x in records.values()) == 1
    for sid, row in records.items():
        assert row["source_id"] == sid
        assert row["official_source_url"] == KNOWN[sid]["url"]
        assert row["category"] == KNOWN[sid]["category"]
        assert row["operator_publisher_access_review_status"] == "pending"
        assert row["operator_browser_render_budget_review_status"] == "pending"
        assert not row["approved_for_live_acquisition"]
        assert not row["enabled_in_scrapy"]
        assert not row["approved_for_advisor"]
        assert not row["source_product_owner_verified"]
        if row["candidate_acquisition_method"] == "rendered_html":
            assert row["candidate_url"] == KNOWN[sid]["url"]
    md = records["claude_code_changelog"]
    assert md["candidate_url"] == (
        "https://code.claude.com/docs/en/changelog.md"
    )
    plan = registry.acquire_method_plan()
    assert plan["planned_sources"] == 8
    assert plan["network_requests_performed"] == 0
    assert plan["automatic_rendered_html_requests"] == 0
    assert plan["automatic_feed_requests"] == 0
    assert not plan["deployment_authorized"]


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(approved_for_live_acquisition=True),
    lambda d: d.update(automatic_scheduling_enabled=True),
    lambda d: d["experiments"][0].update(enabled_in_scrapy=True),
    lambda d: d["experiments"][0].update(approved_for_advisor=True),
    lambda d: d["experiments"][0].update(source_product_owner_verified=True),
    lambda d: d["experiments"][0].update(
        candidate_url="https://evil.invalid/docs"
    ),
    lambda d: d["experiments"][0].update(
        candidate_url="https://kiro.dev/docs/?token=secret"
    ),
    lambda d: d["experiments"][0].update(
        candidate_url="https://kiro.dev/docs/other-page"
    ),
    lambda d: d["experiments"][-1].update(
        candidate_url="https://code.claude.com/docs/en/unknown.md"
    ),
    lambda d: d["experiments"].append(deepcopy(d["experiments"][0])),
    lambda d: d["experiments"][0].update(source_id="v0_docs"),
])
def test_forged_acquisition_registry_fails_closed(monkeypatch, mutation):
    base = registry._load_registry()
    data = deepcopy(base)
    mutation(data)
    with monkeypatch.context() as ctx:
        ctx.setattr(registry, "_load_registry", lambda: data)
        registry.load_acquisition_experiments.cache_clear()
        with pytest.raises(ValueError):
            registry.load_acquisition_experiments()
    registry.load_acquisition_experiments.cache_clear()
    assert len(registry.load_acquisition_experiments()) == 8


def test_three_real_extractors_consume_paired_private_snapshots_without_network(
        scenarios, tmp_path):
    root, incoming = scenarios
    result = compare_acquisition_snapshots(incoming, root)
    s = result["summary"]
    assert s["paired_sources"] == 3
    assert s["candidate_registry_sources"] == 8
    assert s["network_requests_performed"] == 0
    assert s["approved_for_advisor_facts"] == 0
    assert s["publisher_snapshot_origin_authenticated"] is False
    assert s["independent_accuracy_gold_evaluated"] is False
    assert s["automatic_browser_render_requests"] == 0
    assert s["automatic_source_swaps"] == 0
    assert len(s["local_parser_package_sha256_not_deployed_revision"]) == 64
    observed = {x["source_id"]: x for x in result["pairs"]}
    docs = observed["kiro_docs"]
    assert docs["alternate"]["word_count"] > docs["static"]["word_count"]
    assert docs["alternate"]["page_family"] != "unsupported_category"
    assert docs["observed_comparison"] in {
        "more_scoped_docs_candidate", "more_visible_text_without_scope_proof"
    }
    assert not docs["automatic_method_selected"]
    price = observed["gemini_api_pricing"]
    assert price["alternate"]["pricing_observation_count"] > (
        price["static"]["pricing_observation_count"]
    )
    assert price["observed_comparison"] in {
        "more_comparable_rate_candidates", "more_raw_pricing_evidence"
    }
    assert price["approved_for_advisor"] is False
    release = observed["claude_code_changelog"]
    assert release["alternate"]["structural_evidence_count"] >= 2
    assert release["alternate"]["release_dated_event_count"] == 0
    assert release["observed_comparison"] == (
        "more_version_events_dates_unverified"
    )
    write_acquisition_report(result, tmp_path / "output_private")
    assert (tmp_path / "output_private/acquisition_comparison_summary.json").exists()
    assert (tmp_path / "output_private/acquisition_comparison_pairs.json").exists()
    assert (tmp_path / "output_private/acquisition_review_queue.csv").exists()
    output = (tmp_path / "output_private/acquisition_comparison_pairs.json").read_text()
    assert "Model Alpha</th>" not in output
    assert "Improved synthetic tool startup" not in output
    assert "source_specific_adapter_authorized" in output


def test_product_title_conflict_blocks_automatic_capture_winner(tmp_path):
    root = tmp_path / "snapshots"
    root.mkdir()
    record = pair(
        root, "cursor_docs", _static_docs("Cursor"),
        _rendered_docs("GitHub Copilot"),
    )
    output = compare_acquisition_snapshots(manifest([record]), root)
    row = output["pairs"][0]
    assert row["alternate"]["product_title_conflict"]
    assert row["observed_comparison"] == "alternate_product_title_conflict"
    assert row["manual_review_action"] == "review_exact_product_owner"
    assert not row["source_specific_adapter_authorized"]


@pytest.mark.parametrize("mutate,error", [
    (lambda p: p["static_html"].update(sha256="f" * 64),
     "bytes differ"),
    (lambda p: p["alternate"].update(
        request_url="https://evil.invalid/"),
     "URL/redirect"),
    (lambda p: p["alternate"].update(
        final_url="https://kiro.dev/docs/other"),
     "URL/redirect"),
    (lambda p: p["static_html"].update(http_status=403),
     "HTTP 200"),
    (lambda p: p["alternate"].update(media_type="text/plain"),
     "media type"),
    (lambda p: p["alternate"].update(
        capture_method="official_markdown"),
     "method or provenance"),
    (lambda p: p["alternate"].update(
        capture_origin_review_status="publisher_verified"),
     "method or provenance"),
    (lambda p: p["alternate"].update(
        captured_at_utc="2026-11-03T12:00:00Z"),
     "two hours"),
    (lambda p: p["static_html"].update(
        captured_at_utc="2026-11-02T11:00:00"),
     "UTC offset"),
    (lambda p: p["alternate"].update(file="../escape.html"),
     "traversal"),
])
def test_tampered_or_cross_product_snapshots_rejected(
        scenarios, mutate, error):
    root, data = scenarios
    one = deepcopy(data)
    one["pairs"] = [one["pairs"][0]]
    mutate(one["pairs"][0])
    with pytest.raises(ValueError, match=error):
        compare_acquisition_snapshots(one, root)


def test_symlink_snapshot_not_accepted(scenarios):
    root, incoming = scenarios
    only = deepcopy(incoming)
    only["pairs"] = [only["pairs"][0]]
    link = root / "shortcut.html"
    link.symlink_to(root / only["pairs"][0]["alternate"]["file"])
    only["pairs"][0]["alternate"]["file"] = link.name
    with pytest.raises(ValueError, match="symlink"):
        compare_acquisition_snapshots(only, root)


def test_unknown_source_duplicate_source_and_user_approval_rejected(scenarios):
    root, incoming = scenarios
    bad = deepcopy(incoming)
    bad["pairs"][0]["source_id"] = "v0_docs"
    with pytest.raises(ValueError, match="Duplicate/unknown"):
        compare_acquisition_snapshots(bad, root)
    bad = deepcopy(incoming)
    bad["pairs"].append(deepcopy(bad["pairs"][0]))
    with pytest.raises(ValueError, match="Duplicate/unknown"):
        compare_acquisition_snapshots(bad, root)
    bad = deepcopy(incoming)
    bad["approved_for_advisor"] = True
    with pytest.raises(ValueError, match="manifest"):
        compare_acquisition_snapshots(bad, root)


def test_stable_results_independent_of_manifest_pair_order(scenarios):
    root, packet = scenarios
    first = compare_acquisition_snapshots(packet, root)
    flipped = deepcopy(packet)
    flipped["pairs"] = list(reversed(flipped["pairs"]))
    second = compare_acquisition_snapshots(flipped, root)
    assert first == second


def test_bounded_input_never_approves_crawler_or_vendor_facts(scenarios):
    root, sample = scenarios
    report = compare_acquisition_snapshots(sample, root)
    for row in report["pairs"]:
        assert row["source_id"] in KNOWN
        assert row["static"]["approved_for_advisor"] is False
        assert row["alternate"]["approved_for_advisor"] is False
        assert row["static"]["all_facts_unverified"] is True
        assert row["alternate"]["all_facts_unverified"] is True
        assert not row["publisher_response_origin_independently_authenticated"]
        assert not row["original_robots_terms_permission_independently_verified"]
        assert not row["static_source_replaced"]
        assert not row["automatic_method_selected"]
        assert not row["source_specific_adapter_authorized"]
        assert row["approved_for_advisor"] is False
