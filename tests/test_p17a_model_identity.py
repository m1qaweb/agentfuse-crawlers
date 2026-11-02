"""P17A model identity regressions: all HTML/amounts are SYNTHETIC.

The main safety invariant is that a marketing description appended to a
model name cannot become a distinct model or a spurious rate-change key.
No synthetic "price" or model is asserted to exist on any real publisher.
"""
from copy import deepcopy

import pytest
from lxml import html

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.model_labels import (
    inspect_model_cell, suspected_model_description_join,
    visible_cell_text,
)
from agentfuse_crawlers.run_context import manifest_sha256, selection_ids_sha256
from agentfuse_crawlers.source_lifecycle import registry_revision_sha256
from agentfuse_crawlers.sources import select_sources
from scripts.triage_pricing_model_identity import (
    audit_pricing_model_identity, write_triage,
)

URL = "https://developers.openai.com/api/docs/pricing"
SOURCE = "openai_api_pricing"


def rates(row, *, scoped=True):
    preface = (
        "<h2>Region: Global</h2><h3>Tier: Standard</h3>"
        if scoped else "<h2>Model pricing</h2>"
    )
    caption = "USD per 1M tokens" if scoped else "per 1M tokens"
    markup = (
        "<html><head><title>Pricing</title></head><body><main>"
        + preface
        + "<table><caption>" + caption + "</caption>"
        "<thead><tr><th>Model</th><th>Input price</th>"
        "<th>Output price</th></tr></thead><tbody>"
        + row +
        "</tbody></table></main></body></html>"
    )
    return extract_evidence(markup, URL, category="pricing", source_id=SOURCE)


def row(model_cell, *, input_rate="$2.00", output_rate="$6.00"):
    return (
        "<tr><th>" + model_cell + "</th>"
        "<td>" + input_rate + "</td><td>" + output_rate + "</td></tr>"
    )


def test_prominent_model_strong_separates_description_without_guessing():
    example = row(
        "<strong>Claude Fable 5.1</strong>"
        "<span>For demanding reasoning and long-horizon agentic work</span>"
    )
    result = rates(example)
    assert result["pricing_parser_revision"] == (
        "evidence_quote_v4_model_identity"
    )
    assert result["pricing_model_label_recovered_rows"] == 1
    assert result["pricing_model_identity_review_rows"] == 0
    assert result["pricing_comparable_candidate_count"] == 2
    observations = result["pricing_observations"]
    assert {x["model_or_service"] for x in observations} == {
        "Claude Fable 5.1"
    }
    assert {x["normalized_amount_decimal"] for x in observations} == {
        "2.00", "6.00"
    }
    assert all(
        x["model_label_hygiene_status"] ==
            "explicit_leading_dom_label_with_description"
        and x["model_label_provenance"] == "explicit_dom_primary_label"
        and not x["model_label_requires_review"]
        and x["model_label_description_present"]
        and x["row_label"].startswith("Claude Fable 5.1")
        and x["approved_for_advisor"] is False
        for x in observations
    )


def test_high_volume_grok_like_row_with_explicit_dom_marked_id():
    result = rates(row(
        '<span class="model-name">grok-4.7</span>'
        "<small>Long context ≥ 200k tokens</small>"
    ))
    observations = result["pricing_observations"]
    assert {x["model_or_service"] for x in observations} == {
        "grok-4.7"
    }, repr([(x["model_or_service"], x["model_label_hygiene_status"],
              x["normalization_blockers"]) for x in observations])
    assert all(x["model_label_provenance"] == "explicit_dom_primary_label"
               for x in observations)
    assert result["pricing_comparable_candidate_count"] == 2, repr([
        (x["model_or_service"], x["normalization_blockers"],
         x["billing_unit"], x["region"], x["tier_or_plan"])
        for x in observations
    ])


def test_inline_dom_fragments_have_word_boundary_in_raw_displayed_cell():
    dom = html.fromstring(
        "<table><tr><th>"
        "<strong>Claude Opus 5.5</strong><span>For long-running coding work</span>"
        "</th><td><span>$</span><span>1.50</span></td></tr></table>"
    )
    th, td = dom.xpath(".//th|.//td")
    assert visible_cell_text(th).startswith(
        "Claude Opus 5.5 For long-running coding"
    )
    assert visible_cell_text(td) == "$ 1.50"
    identity = inspect_model_cell(th)
    assert identity["label"] == "Claude Opus 5.5"
    assert identity["status"] == "explicit_leading_dom_label_with_description"


def test_two_distinct_bold_models_in_same_cell_never_become_rate_identity():
    result = rates(row(
        "<strong>Model Alpha 4</strong> "
        "<strong>Model Beta 4</strong>"
    ))
    assert result["pricing_model_identity_review_rows"] == 1
    assert result["pricing_model_label_recovered_rows"] == 0
    assert result["pricing_comparable_candidate_count"] == 0
    for x in result["pricing_observations"]:
        assert x["model_or_service"] is None
        assert x["model_label_requires_review"]
        assert x["model_label_hygiene_status"] == (
            "ambiguous_multiple_prominent_models"
        )
        assert "missing_model_or_service" in x["normalization_blockers"]


@pytest.mark.parametrize("model", [
    "grok-4.7Long context ≥ 200k tokens",
    "Claude Fable 5.1For demanding reasoning and long-horizon agentic work",
    "Claude Opus 5.5 For long-running agentic coding and knowledge work",
    "Claude Sonnet 5.5The best combination of speed and intelligence",
    "grok-4.7 Long context ≥ 200k tokens",
])
def test_unmarked_model_plus_marketing_text_is_never_promoted(model):
    assert suspected_model_description_join(model)
    result = rates(row(model))
    assert result["pricing_model_identity_review_rows"] == 1
    assert result["pricing_comparable_candidate_count"] == 0
    for obs in result["pricing_observations"]:
        assert obs["model_or_service"] is None
        assert obs["model_label_requires_review"]
        assert obs["normalized_amount_decimal"] is None
        assert obs["review_quote_candidate"] is False


def test_simple_plain_model_table_is_backward_compatible():
    result = rates(
        row("Model Alpha", input_rate="$1.50", output_rate="$4.50")
    )
    assert result["pricing_model_label_recovered_rows"] == 0
    assert result["pricing_model_identity_review_rows"] == 0
    assert result["pricing_comparable_candidate_count"] == 2
    assert {x["model_or_service"] for x in result["pricing_observations"]} == {
        "Model Alpha"
    }
    assert all(x["model_label_hygiene_status"] ==
               "unresolved_plain_row_cell" for x in result["pricing_observations"])


def test_model_recovery_does_not_invent_usd_region_tier_or_price():
    page = rates(row(
        "<strong>Model Alpha 4</strong>"
        "<small>For demanding technical workloads</small>"
    ), scoped=False)
    assert page["pricing_comparable_candidate_count"] == 0
    assert page["pricing_model_label_recovered_rows"] == 1
    for obs in page["pricing_observations"]:
        assert obs["model_or_service"] == "Model Alpha 4"
        assert obs["currency"] is None
        assert obs["region"] is None
        assert obs["tier_or_plan"] is None
        assert obs["normalized_amount_decimal"] is None
        assert not obs["comparable_candidate"]
        assert not obs["approved_for_advisor"]


def test_exact_model_identity_remains_separate_across_two_rates():
    ev = rates(
        row("<strong>Model Alpha 4</strong><p>Long context ≥ 200k tokens</p>")
        + row("<strong>Model Beta 4</strong><p>For demanding tasks</p>",
              input_rate="$3.00", output_rate="$7.00")
    )
    assert ev["pricing_model_label_recovered_rows"] == 2
    assert ev["pricing_comparable_candidate_count"] == 4
    candidates = ev["pricing_observations"]
    assert len({x["observation_id"] for x in candidates}) == 4
    assert all(x["review_status"] == "unverified" for x in candidates)
    assert not ev["approved_for_advisor"]


def fake_pricing_inventory():
    expected = select_sources("pricing", "all")
    fake = []
    for src in expected:
        fake.append({
            "source_id": src["id"], "source_url": src["url"],
            "category": src["category"], "provider": src["provider"],
            "spider_name": "official_pricing", "status": "needs_review",
            "approved_for_advisor": False,
            "requested_cohort": "all", "collection_mode": "validation",
            "run_scope_explicit": True,
            "manifest_sha256": manifest_sha256(),
            "source_registry_sha256": registry_revision_sha256(),
            "selection_ids_sha256": selection_ids_sha256(expected),
            "selection_source_count": 177,
            "zyte_job_id": "883514/3/10",
            "deployment_revision": "f" * 64,
            "deployment_revision_kind": "package_py_json_sha256_v1",
            "pricing_observations": [],
        })
    first = next(x for x in fake if x["source_id"] == "xai_pricing")
    first["pricing_observations"] = [{
        "model_or_service": "grok-4.7Long context ≥ 200k tokens",
        "raw_displayed_price": "$2.00",
        "review_quote_candidate": True,
        "comparable_candidate": False,
        "approved_for_advisor": False,
    }, {
        "model_or_service": "Model Alpha",
        "review_quote_candidate": True,
        "comparable_candidate": False,
        "approved_for_advisor": False,
    }]
    return fake


def test_full_177_source_historical_risk_audit_is_read_only(tmp_path):
    records = fake_pricing_inventory()
    report = audit_pricing_model_identity(records)
    s = report["summary"]
    assert s["source_count"] == 177
    assert s["observed_counts"]["retained_observations"] == 2
    assert s["observed_counts"]["review_quote_candidates"] == 2
    assert s["observed_counts"]["suspicious_review_quotes"] == 1
    assert s["source_ids_with_risky_review_quotes"] == ["xai_pricing"]
    assert not s["parser_change_replayed_on_raw_publisher_html"]
    assert not s["publisher_fact_accuracy_verified"]
    assert s["advisor_fact_approvals"] == 0
    assert s["network_requests_performed"] == 0
    assert s["deployment_authorized"] is False
    write_triage(report, tmp_path)
    assert (tmp_path / "pricing_model_identity_risks.json").exists()
    assert (tmp_path / "pricing_model_identity_review_queue.csv").exists()


def test_historical_audit_refuses_source_drift_or_false_approval():
    rows = fake_pricing_inventory()
    broken = deepcopy(rows)
    broken.pop()
    with pytest.raises(ValueError, match="Exactly 177"):
        audit_pricing_model_identity(broken)
    broken = deepcopy(rows)
    broken[0]["source_url"] = "https://evil.invalid/pricing"
    with pytest.raises(ValueError, match="provenance"):
        audit_pricing_model_identity(broken)
    broken = deepcopy(rows)
    broken[0]["approved_for_advisor"] = True
    with pytest.raises(ValueError, match="provenance"):
        audit_pricing_model_identity(broken)
    broken = deepcopy(rows)
    broken[0]["pricing_observations"] = [{
        "model_or_service": "Model A",
        "approved_for_advisor": True,
    }]
    with pytest.raises(ValueError, match="pre-approved"):
        audit_pricing_model_identity(broken)
