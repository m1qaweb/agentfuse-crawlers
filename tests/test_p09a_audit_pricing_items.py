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
