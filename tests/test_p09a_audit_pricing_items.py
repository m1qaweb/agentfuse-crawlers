"""P09A audit CLI integrity checks using original illustrative Items only."""

import csv
import json

import pytest

from scripts.audit_pricing_items import inspect, save


def _item(source="openai_api_pricing", url="https://developers.openai.com/api/docs/pricing"):
    return {
        "source_id": source, "source_url": url, "category": "pricing",
        "provider": "OpenAI", "status": "needs_review",
        "approved_for_advisor": False,
        "error": "pricing_rate_dimensions_unresolved",
        "pricing_observations": [{
            "source_id": source, "source_url": url,
            "price_state": "numeric_candidate",
            "raw_displayed_price": "$1.20",
            "normalized_amount_decimal": None,
            "currency": None, "billing_unit": "per_1m_tokens",
            "region": None, "tier_or_plan": None, "price_dimension": "input",
            "model_or_service": "Example model",
            "comparable_candidate": False,
            "normalization_blockers": [
                "missing_explicit_currency",
                "missing_explicit_region",
                "missing_explicit_tier_or_plan",
            ],
            "scope_declarations": [{
                "dimension": "billing_unit", "value": "per_1m_tokens",
                "scope": "adjacent_preceding_text",
                "evidence_text": "Prices per 1M tokens.",
                "review_status": "unverified",
            }],
            "approved_for_advisor": False,
        }],
    }


def test_audit_tracks_missing_dimensions_and_provenance_without_approving(tmp_path):
    report = inspect([_item()])
    assert report["source_count"] == 1
    assert report["source_accounting_complete"] is False
    assert report["observed_price_rows"] == 1
    assert report["comparable_candidates"] == 0
    assert report["dimension_coverage"]["billing_unit"]["known"] == 1
    assert report["dimension_coverage"]["region"]["known"] == 0
    assert report["sources"][0]["explicit_scope_declarations"] == 1
    assert report["normalization_blockers"]["missing_explicit_region"] == 1
    assert report["approved_for_advisor"] is False
    save(report, tmp_path)
    loaded = json.loads((tmp_path / "pricing_run_audit.json").read_text())
    assert loaded["observed_price_rows"] == 1
    rows = list(csv.DictReader((tmp_path / "pricing_sources.csv").open()))
    assert rows[0]["source_id"] == "openai_api_pricing"


def test_full_inventory_requires_all_configured_ids():
    with pytest.raises(ValueError, match="177-source"):
        inspect([_item()], expect_all=True)


def test_duplicate_source_and_changed_url_are_rejected():
    with pytest.raises(ValueError, match="Unknown/duplicate"):
        inspect([_item(), _item()])
    changed = _item()
    changed["source_url"] = "https://attacker.invalid/price"
    with pytest.raises(ValueError, match="provenance mismatch"):
        inspect([changed])


def test_bad_price_observation_provenance_fails_closed():
    changed = _item()
    changed["pricing_observations"][0]["source_id"] = "other"
    with pytest.raises(ValueError, match="attribution mismatch"):
        inspect([changed])


def test_comparable_with_missing_currency_is_security_anomaly():
    changed = _item()
    changed["pricing_observations"][0]["comparable_candidate"] = True
    changed["pricing_observations"][0]["normalized_amount_decimal"] = "1.20"
    report = inspect([changed])
    assert report["provenance_or_approval_anomalies"] == 1


def test_advisor_approval_in_items_is_anomaly_not_a_success():
    changed = _item()
    changed["approved_for_advisor"] = True
    report = inspect([changed])
    assert report["provenance_or_approval_anomalies"] == 1



def test_p09a2_card_counts_and_parser_revision_are_auditable_not_approved():
    record = _item()
    record.update(
        pricing_parser_revision="structured_cards_v2",
        pricing_card_total=3,
        pricing_card_price_entries_examined=6,
        pricing_card_observation_count=4,
        pricing_card_omitted=1,
        pricing_card_oversized_count=1,
        pricing_card_duplicate_rate_count=2,
        pricing_observation_total_detected=8,
        pricing_rate_identity_collision_count=0,
        pricing_inventory_complete=False,
    )
    report = inspect([record])
    assert report["parser_revisions"] == {"structured_cards_v2": 1}
    assert report["card_summaries"]["structured_cards_detected"] == 3
    assert report["card_summaries"]["price_card_entries_examined"] == 6
    assert report["card_summaries"]["card_observations_retained"] == 4
    assert report["card_summaries"]["cards_omitted_or_oversized"] == 1
    assert report["card_summaries"]["duplicate_comparable_rates_deduplicated"] == 2
    assert report["sources"][0]["detected_price_entries"] == 8
    assert report["sources"][0]["parser_revision"] == "structured_cards_v2"
    assert report["sources"][0]["inventory_complete"] is False
    assert report["approved_for_advisor"] is False


def test_legacy_no_card_fields_still_explained_as_unversioned():
    report = inspect([_item()])
    assert report["parser_revisions"] == {"legacy_unversioned": 1}
    assert report["card_summaries"]["structured_cards_detected"] == 0
    assert report["sources"][0]["card_observations"] == 0



def test_p17b1_review_only_component_counts_and_no_false_approval():
    record = _item()
    obs = record["pricing_observations"][0]
    obs.update(
        evidence_kind="structured_table_labeled_inline_component",
        inline_component_parent_identity_review_status=(
            "unverified_fireworks_legend_triplet"
        ),
        inline_component_count=3,
        inline_component_index=0,
        raw_parent_cell_text="$3.00 / $0.30 / $15.00",
        normalized_amount_decimal=None,
        comparable_candidate=False,
        review_quote_candidate=False,
        approved_for_advisor=False,
    )
    record.update(
        pricing_parser_revision="evidence_quote_v5_inline_labeled_components",
        pricing_inline_rate_cells_split=1,
        pricing_inline_multi_amount_cells_unresolved=4,
    )
    report = inspect([record])
    summary = report["review_only_rate_family_summaries"]
    assert summary == {
        "inline_labeled_components_retained": 1,
        "fireworks_legend_components_retained": 1,
        "rate_cells_split": 1,
        "multi_amount_cells_still_unresolved": 4,
        "independently_verified_publisher_rate_facts": 0,
        "advisor_fact_approvals": 0,
    }
    assert report["provenance_or_approval_anomalies"] == 0


@pytest.mark.parametrize("mutation", [
    {"comparable_candidate": True},
    {"review_quote_candidate": True},
    {"normalized_amount_decimal": "3.00"},
    {"approved_for_advisor": True},
])
def test_p17b1_review_candidate_accidental_promotion_is_quality_anomaly(mutation):
    record = _item()
    record["pricing_observations"][0].update(
        evidence_kind="structured_table_labeled_inline_component",
        inline_component_parent_identity_review_status=(
            "unverified_fireworks_legend_triplet"
        ),
        **mutation,
    )
    report = inspect([record])
    assert report["provenance_or_approval_anomalies"] >= 1
    assert report["approved_for_advisor"] is False



def test_p22b1_visible_scope_audit_preserves_legacy_unknown_and_new_known(tmp_path):
    legacy = inspect([_item()])
    assert legacy["visibility_summaries"][
        "legacy_or_held_items_without_visibility_audit"
    ] == 1
    assert legacy["sources"][0]["explicitly_hidden_subtrees_omitted"] is None

    current = _item()
    current.update(
        pricing_explicitly_hidden_subtrees_omitted=3,
        pricing_scope_visibility_revision=(
            "static_explicitly_nonvisible_html_exclusion_v1"
        ),
        pricing_static_visible_page_only=True,
    )
    report = inspect([current])
    summary = report["visibility_summaries"]
    assert summary == {
        "source_items_with_visible_html_audit": 1,
        "legacy_or_held_items_without_visibility_audit": 0,
        "explicitly_hidden_subtrees_excluded": 3,
        "sources_with_explicitly_hidden_content": 1,
        "publisher_price_completeness_verified": False,
        "review_status": "unverified",
    }
    assert report["sources"][0]["pricing_visibility_revision"] == (
        "static_explicitly_nonvisible_html_exclusion_v1"
    )
    assert report["sources"][0]["visible_static_html_only"] is True
    assert report["sources"][0]["approved_for_advisor"] is False
    save(report, tmp_path)
    rows = list(csv.DictReader((tmp_path / "pricing_sources.csv").open()))
    assert rows[0]["explicitly_hidden_subtrees_omitted"] == "3"
    assert rows[0]["visible_static_html_only"] == "True"
    assert rows[0]["pricing_visibility_revision"] == (
        "static_explicitly_nonvisible_html_exclusion_v1"
    )


@pytest.mark.parametrize("fields", [
    {"pricing_explicitly_hidden_subtrees_omitted": -1},
    {"pricing_explicitly_hidden_subtrees_omitted": 0},
    {"pricing_explicitly_hidden_subtrees_omitted": "4",
     "pricing_scope_visibility_revision":
        "static_explicitly_nonvisible_html_exclusion_v1",
     "pricing_static_visible_page_only": True},
    {"pricing_explicitly_hidden_subtrees_omitted": 1,
     "pricing_scope_visibility_revision": "forged",
     "pricing_static_visible_page_only": True},
    {"pricing_explicitly_hidden_subtrees_omitted": 1,
     "pricing_scope_visibility_revision":
        "static_explicitly_nonvisible_html_exclusion_v1",
     "pricing_static_visible_page_only": False},
    {"pricing_static_visible_page_only": True},
    {"pricing_scope_visibility_revision":
        "static_explicitly_nonvisible_html_exclusion_v1"},
])
def test_p22b1_malformed_or_partial_visible_scope_audit_fails_closed(fields):
    record = _item()
    record.update(fields)
    with pytest.raises(ValueError, match="visibility|pricing audit"):
        inspect([record])
