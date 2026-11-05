"""P22B1 fail-closed static HTML pricing visibility, synthetic-only.

These examples represent a defect class, NOT captured original vendor pages
or evidence that today's publisher pricing is correct. No network requests.
"""
import pytest
from lxml import html

from agentfuse_crawlers.extract import extract_evidence
from agentfuse_crawlers.pricing_cards import extract_card_evidence
from agentfuse_crawlers.pricing_scope import table_declarations
from agentfuse_crawlers.pricing_visibility import (
    _hidden_css, explicitly_nonvisible, in_explicitly_nonvisible_context,
)

SOURCE = "https://developers.openai.com/api/docs/pricing"
SID = "openai_api_pricing"


def analyze(markup, *, source=SOURCE, sid=SID):
    return extract_evidence(
        "<html><head><title>FAKE illustrative source</title></head>"
        "<body><main>" + markup + "</main></body></html>",
        source, category="pricing", source_id=sid,
    )


def table(name="Visible Model", amount="USD 1.25 / 1M tokens"):
    return (
        "<table><caption>USD per 1M tokens</caption>"
        "<thead><tr><th>Model</th><th>Input price</th></tr></thead>"
        "<tbody><tr><th>" + name + "</th><td>" + amount +
        "</td></tr></tbody></table>"
    )


def scopes(*, currency=True):
    return (
        ("<p>All prices are in USD.</p>" if currency else "")
        + "<p>Region: Global</p>"
        + "<p>Tier: Standard</p>"
        + "<p>Prices per 1M tokens.</p>"
    )


def card(name="Visible Subscription", amount="USD 1.25 / MTok"):
    return (
        "<article class='pricing-card'>"
        "<h3>" + name + "</h3>"
        "<p>Region: Global</p><p>Tier: Standard</p>"
        "<p>Input price: " + amount + "</p>"
        "</article>"
    )


def test_normal_visible_table_remains_unverified_compatible():
    ev = analyze(scopes() + table())
    obs = ev["pricing_observations"]
    assert len(obs) == 1
    assert obs[0]["model_or_service"] == "Visible Model"
    assert obs[0]["currency"] == "USD"
    assert obs[0]["billing_unit"] == "per_1m_tokens"
    assert obs[0]["region"] == "Global"
    assert obs[0]["tier_or_plan"] == "Standard"
    assert obs[0]["comparable_candidate"] is True
    assert obs[0]["normalized_amount_decimal"] == "1.25"
    assert obs[0]["approved_for_advisor"] is False
    assert ev["pricing_explicitly_hidden_subtrees_omitted"] == 0
    assert ev["pricing_static_visible_page_only"] is True
    assert ev["pricing_scope_visibility_revision"] == (
        "static_explicitly_nonvisible_html_exclusion_v1"
    )


@pytest.mark.parametrize("container", [
    "<section hidden>{}</section>",
    "<div hidden='false'>{}</div>",  # HTML boolean attribute still hides
    "<div inert>{}</div>",
    "<div aria-hidden='true'>{}</div>",
    "<div style='display:none'>{}</div>",
    "<div style='display : none !important; display: block'>{}</div>",
    "<div style='visibility:hidden'>{}</div>",
    "<div style='visibility:collapse'>{}</div>",
    "<div style='content-visibility:hidden'>{}</div>",
    "<div style='opacity: 0'>{}</div>",
    "<dialog>{}</dialog>",
    "<details>{}</details>",  # closed details cannot establish visible price
])
def test_hidden_stale_table_must_not_create_a_second_comparable_price(container):
    ev = analyze(scopes() + container.format(
        table(name="Inactive Model", amount="USD 999 / MTok")
    ) + table())
    assert ev["pricing_table_total"] == 1
    assert ev["pricing_observation_count"] == 1
    assert ev["pricing_observations"][0]["model_or_service"] == "Visible Model"
    assert ev["pricing_observations"][0]["normalized_amount_decimal"] == "1.25"
    assert all(x["approved_for_advisor"] is False
               for x in ev["pricing_observations"])
    # aria-hidden is also stripped by the pre-existing noisy-markup cleaner;
    # all other explicit states are counted by the P22B1 visibility audit.
    assert ev["pricing_explicitly_hidden_subtrees_omitted"] >= 1


@pytest.mark.parametrize("hidden", [
    "<div hidden><p>All prices are in USD.</p></div>",
    "<div style='display:none'><p>All prices are in USD.</p></div>",
    "<details><p>All prices are in USD.</p></details>",
    "<div inert><p>All prices are in USD.</p></div>",
])
def test_hidden_global_currency_never_normalizes_a_visible_dollar_price(hidden):
    ev = analyze(hidden + scopes(currency=False) + table(
        amount="$1.25 / MTok"
    ))
    assert ev["pricing_observation_count"] == 1
    obs = ev["pricing_observations"][0]
    assert obs["currency"] is None
    assert obs["normalized_amount_decimal"] is None
    assert obs["comparable_candidate"] is False
    assert "missing_explicit_currency" in obs["normalization_blockers"]


@pytest.mark.parametrize("hidden", [
    "<div hidden><p>Region: Global</p><p>Tier: Standard</p></div>",
    "<div style='visibility:hidden'>"
    "<p>Region: Global</p><p>Tier: Standard</p></div>",
    "<dialog><p>Region: Global</p><p>Tier: Standard</p></dialog>",
])
def test_hidden_region_or_tier_declaration_never_fills_visible_scope(hidden):
    ev = analyze(
        "<p>All prices are in USD.</p>" + hidden +
        "<p>Prices per 1M tokens.</p>" + table()
    )
    x = ev["pricing_observations"][0]
    assert x["region"] is None and x["tier_or_plan"] is None
    assert x["comparable_candidate"] is False
    assert "missing_explicit_region" in x["normalization_blockers"]
    assert "missing_explicit_tier_or_plan" in x["normalization_blockers"]


def test_hidden_conflicting_currency_must_not_discard_valid_visible_currency():
    ev = analyze(
        "<p>All prices are in USD.</p>"
        "<div hidden><p>All prices are in EUR.</p></div>"
        + scopes(currency=False) + table()
    )
    obs = ev["pricing_observations"][0]
    assert obs["currency"] == "USD"
    assert obs["normalized_amount_decimal"] == "1.25"
    assert obs["comparable_candidate"] is True


def test_visible_conflicting_currency_must_remain_unresolved():
    ev = analyze(
        "<p>All prices are in USD.</p>"
        "<p>All prices are in EUR.</p>"
        + scopes(currency=False) + table(amount="$1.25 / MTok")
    )
    obs = ev["pricing_observations"][0]
    assert obs["currency"] is None
    assert obs["normalized_amount_decimal"] is None
    assert obs["comparable_candidate"] is False


@pytest.mark.parametrize("hidden", [
    "<section hidden>{}</section>",
    "<section style='display:none'>{}</section>",
    "<section inert>{}</section>",
    "<dialog>{}</dialog>",
])
def test_inactive_card_is_not_a_live_price_candidate(hidden):
    ev = analyze(hidden.format(card(name="Hidden Old Rate")) + card())
    assert ev["pricing_card_total"] == 1
    assert ev["pricing_card_observation_count"] == 1
    assert ev["pricing_observation_count"] == 1
    assert ev["pricing_observations"][0]["model_or_service"] == (
        "Visible Subscription"
    )
    assert ev["pricing_observations"][0]["normalized_amount_decimal"] == "1.25"


def test_hidden_local_plan_and_region_inside_visible_card_do_not_apply():
    ev = analyze(
        "<section class='pricing-card'>"
        "<h3>Visible Service</h3>"
        "<div hidden><p>Region: Global</p>"
        "<p>Tier: Standard</p></div>"
        "<p>Input price: USD 1.25 / MTok</p>"
        "</section>"
    )
    assert len(ev["pricing_observations"]) == 1
    x = ev["pricing_observations"][0]
    assert x["currency"] == "USD"
    assert x["region"] is None and x["tier_or_plan"] is None
    assert x["comparable_candidate"] is False


def test_visible_card_scope_remains_positive_after_hidden_scope_exclusion():
    ev = analyze(
        "<div hidden><p>All prices are in EUR.</p></div>" + card()
    )
    x = ev["pricing_observations"][0]
    assert x["currency"] == "USD"
    assert x["region"] == "Global"
    assert x["tier_or_plan"] == "Standard"
    assert x["normalized_amount_decimal"] == "1.25"
    assert x["comparable_candidate"] is True


def test_root_main_hidden_blocks_all_pricing_observations():
    markup = (
        "<html><body><main hidden>"
        + scopes() + table() +
        "</main></body></html>"
    )
    ev = extract_evidence(markup, SOURCE, category="pricing", source_id=SID)
    assert ev["pricing_observation_count"] == 0
    assert ev["pricing_comparable_candidate_count"] == 0
    assert ev["pricing_explicitly_hidden_subtrees_omitted"] >= 1
    assert ev["approved_for_advisor"] is False


def test_main_inside_hidden_parent_cannot_inherit_visible_rates():
    markup = (
        "<html><body><div style='display:none'><main>"
        + scopes() + table() +
        "</main></div></body></html>"
    )
    ev = extract_evidence(markup, SOURCE, category="pricing", source_id=SID)
    assert ev["pricing_observation_count"] == 0
    assert ev["pricing_explicitly_hidden_subtrees_omitted"] >= 1


def test_table_helper_skips_hidden_table_without_consuming_visible_unit_scope():
    root = html.fromstring(
        "<main><p>Prices per 1M tokens.</p>"
        "<table hidden><tr><td>USD 9.25</td></tr></table>" +
        table() +
        "</main>"
    )
    scoped = table_declarations(root)
    visible = root.xpath(".//table")[1]
    assert list(scoped) == [id(visible)]
    assert scoped[id(visible)][0]["dimension"] == "billing_unit"
    assert scoped[id(visible)][0]["value"] == "per_1m_tokens"


def test_direct_raw_card_extractor_rejects_wholly_hidden_pricing_card():
    root = html.fromstring("<main>" + (
        "<div hidden>" + card() + "</div>"
    ) + "</main>")
    result = extract_card_evidence(root, SOURCE, SID)
    assert result["card_observations"] == []


def test_inline_css_cascade_only_hides_effectively_invisible_display():
    assert _hidden_css("display:none") is True
    assert _hidden_css("DISPLAY : none ! IMPORTANT; display:block") is True
    assert _hidden_css("display:none; display:block !important") is False
    assert _hidden_css("display:none;display:block") is False
    assert _hidden_css("--display:none; color: red") is False
    assert _hidden_css("display:noneish") is False
    assert _hidden_css("visibility:visible; opacity:1") is False
    assert _hidden_css("content-visibility:hidden") is True
    assert _hidden_css("opacity:0.000") is True


def test_hidden_ancestor_protects_direct_pricing_scope_helper():
    root = html.fromstring(
        "<main><section inert><p>Prices per 1M tokens.</p></section></main>"
    )
    p = root.xpath(".//p")[0]
    assert not explicitly_nonvisible(p)
    assert in_explicitly_nonvisible_context(p)
    assert not in_explicitly_nonvisible_context(root)


def test_nonpricing_categories_remain_intentionally_unchanged():
    markup = (
        "<html><body><main>"
        "<div hidden><p>Placeholder documentation note.</p></div>"
        "<h1>Example API docs</h1>"
        "<h2>Authentication</h2><p>" +
        ("This is a synthetic documentation-only paragraph. " * 12) +
        "</p></main></body></html>"
    )
    doc = extract_evidence(markup, SOURCE, category="documentation", source_id=SID)
    assert "pricing_scope_visibility_revision" not in doc
    assert "pricing_explicitly_hidden_subtrees_omitted" not in doc
