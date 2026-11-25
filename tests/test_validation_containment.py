"""Synthetic state-machine regressions; no publisher access or permission."""
from types import SimpleNamespace

import pytest

from agentfuse_crawlers.validation_containment import (
    Containment, GLOBAL_HOLD, GROUP_HOLD, INTEGRITY_STOP, PROXY_STOP,
    SYSTEMIC_STOP, TRANSPORT_STOP, group_index, http_barrier, intentional_hold,
    item_barrier, state_for,
)


def source(sid, provider, host):
    return dict(id=sid, provider=provider, category="documentation",
                url="https://" + host + "/" + sid)


SOURCES = [source("alpha_docs", "Alpha", "docs.alpha.invalid"),
           source("alpha_price", "Alpha", "alpha.other"),
           source("shared_alpha", "Other", "api.alpha.invalid"),
           source("shared_other", "Other", "other.example"),
           source("beta_docs", "Beta", "beta.example"),
           source("gamma_docs", "Gamma", "gamma.example"),
           source("delta_docs", "Delta", "delta.example")]


def state():
    spider = SimpleNamespace(collection_mode="validation")
    c = Containment(spider, SOURCES)
    spider._agentfuse_containment = c
    return c


def test_groups_transitive_and_stable_across_order():
    by_source, by_origin = group_index(SOURCES)
    assert group_index(list(reversed(SOURCES))) == (by_source, by_origin)
    assert len({by_source[s["id"]] for s in SOURCES[:4]}) == 1
    assert by_origin["docs.alpha.invalid"] == by_origin["other.example"]
    assert len(set(by_source.values())) == 4


def test_explicit_cross_domain_family_grouping():
    a = source("openai_docs", "OpenAI", "openai.com")
    b = source("codex_docs", "ChatGPT & Codex", "chatgpt.com")
    groups, _ = group_index([a, b])
    assert groups[a["id"]] == groups[b["id"]]


@pytest.mark.parametrize("mutation", ["duplicate", "http", "port"])
def test_invalid_manifest_fails_closed(mutation):
    rows = [dict(s) for s in SOURCES]
    if mutation == "duplicate":
        rows.append(dict(rows[0]))
    elif mutation == "http":
        rows[0]["url"] = "http://alpha.invalid/"
    else:
        rows[0]["url"] = "https://alpha.invalid:444/"
    with pytest.raises(ValueError):
        group_index(rows)


def test_isolated_barrier_holds_linked_groups_and_records_pending():
    c = state()
    alpha, beta = c.by_source["alpha_docs"], c.by_source["beta_docs"]
    c.admit("alpha_docs", alpha)
    c.admit("https://alpha.other/robots.txt", alpha)
    c.admit("beta_docs", beta)
    c.finish("alpha_docs")
    c.barrier(alpha, "agentfuse_validation_http_429")
    c.barrier(alpha, "agentfuse_validation_http_access_denied")
    assert c.blocked == {alpha: "agentfuse_validation_http_429"}
    assert c.pending_at_hold == {"https://alpha.other/robots.txt"}
    assert c.hold(c.by_source["shared_other"]) == GROUP_HOLD
    assert c.hold(beta) is None
    assert c.global_reason is None
    assert c.finish("beta_docs") == beta


def test_third_distinct_group_globally_stops_and_latches():
    c = state()
    for sid in ("alpha_docs", "shared_other", "beta_docs"):
        c.barrier(c.by_source[sid], "agentfuse_validation_http_429")
    assert c.global_reason is None
    c.barrier(c.by_source["gamma_docs"], "agentfuse_validation_robots_or_policy_denied")
    assert c.global_reason == c.spider._agentfuse_validation_stop_reason == SYSTEMIC_STOP
    assert c.hold(c.by_source["delta_docs"]) == GLOBAL_HOLD
    c.stop(PROXY_STOP)
    assert c.global_reason == SYSTEMIC_STOP


def test_unknown_group_is_systemic():
    c = state()
    c.barrier("unknown", "failure")
    assert c.global_reason == INTEGRITY_STOP


@pytest.mark.parametrize("status,systemic,blocked", [(407, True, True), (403, False, True),
    (401, False, True), (451, False, True), (429, False, True), (302, False, True),
    (503, False, True), (404, False, False), (410, False, False), (200, False, False)])
def test_http_barrier_classification(status, systemic, blocked):
    reason, force = http_barrier(status)
    assert force == systemic and bool(reason) == blocked


def test_proxy_and_unknown_transport_remain_systemic():
    for item, expected in (({"http_status": 407}, PROXY_STOP),
                           ({"status": "fetch_error"}, TRANSPORT_STOP)):
        c = state()
        c.observe({"source_id": "alpha_docs", **item})
        assert c.global_reason == expected


def test_robots_and_challenge_items_hold_group_not_entire_job():
    c = state()
    for item in ({"source_id": "alpha_docs", "status": "robots_or_policy_denied"},
                 {"source_id": "beta_docs", "status": "blocked", "error": "access_or_login_challenge"}):
        c.observe(item)
    assert len(c.blocked) == 2 and c.global_reason is None
    assert item_barrier({"status": "captured", "http_status": 200}) == (None, False)


def test_intentional_hold_is_distinct_from_fetch_and_missing_metadata():
    c = state()
    c.barrier(c.by_source["alpha_docs"], "agentfuse_validation_robots_or_policy_denied")
    row = {"source_id": "alpha_price", "status": "source_bulk_validation_not_approved",
           "error": GROUP_HOLD, "policy_observation": "not_fetched_by_downloader_time_access_gate",
           "http_status": None, "final_url": ""}
    c.annotate(row)
    assert intentional_hold(row, c.by_source)
    assert c.held_sources == {"alpha_price"}
    assert not intentional_hold(dict(row, http_status=200), c.by_source)
    assert not intentional_hold(dict(row, validation_containment_group="wrong"), c.by_source)
    assert not intentional_hold(dict(row, validation_containment_block_reason=""), c.by_source)


def test_monitor_does_not_activate_state():
    c = state()
    assert state_for(c.spider) is c
    c.spider.collection_mode = "monitor"
    assert state_for(c.spider) is None


def test_global_hold_and_pending_are_distinguished():
    c = state()
    c.stop(PROXY_STOP)
    row = {"source_id": "beta_docs", "status": "source_bulk_validation_not_approved",
           "error": GLOBAL_HOLD, "policy_observation": "not_fetched_by_downloader_time_access_gate",
           "http_status": None, "final_url": ""}
    c.annotate(row)
    assert intentional_hold(row, c.by_source)
    assert not intentional_hold(dict(row, validation_containment_pending_at_hold=True), c.by_source)
    assert not intentional_hold(dict(row, validation_containment_global_reason=""), c.by_source)


def test_runtime_cutoff_cannot_be_extended():
    from agentfuse_crawlers.validation_containment import TIMEOUT_STOP
    ticks = [100.0]
    c = Containment(SimpleNamespace(collection_mode="validation"), SOURCES,
                    clock=lambda: ticks[0])
    c.limit_runtime(10)
    c.limit_runtime(100)
    ticks[0] = 109.9
    assert c.hold(c.by_source["alpha_docs"]) is None
    ticks[0] = 110.0
    assert c.hold(c.by_source["alpha_docs"]) == GLOBAL_HOLD
    assert c.global_reason == TIMEOUT_STOP
