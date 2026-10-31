from scripts.plan_validation import plan_validation, static_warnings, write_plan
from agentfuse_crawlers.sources import load_sources, load_proven_source_ids, select_sources

import pytest


def test_candidate_plan_covers_all_451_unproven_urls_exactly_once():
    plan = plan_validation(batch_size=15)
    assert plan["manifest_sources"] == 460
    assert plan["candidate_sources"] == 451
    assert plan["proven_sources"] == 9
    assert plan["planned_sources"] == 451
    assert plan["planned_jobs"] == 31
    assert plan["category_counts"] == {
        "changelog": 86, "documentation": 191, "pricing": 174,
    }
    ids = [sid for job in plan["batches"] for sid in job["source_ids"]]
    assert len(ids) == 451 == len(set(ids))
    assert not set(ids).intersection(load_proven_source_ids())
    assert all(job["requested_count"] <= 15 and
               job["spider"] in ("official_changelogs", "official_documentation",
                                 "official_pricing") for job in plan["batches"])
    assert plan["approved_for_advisor"] is False


def test_batches_use_same_selector_as_spiders():
    for job in plan_validation(batch_size=15)["batches"]:
        expected = select_sources(job["category"], cohort=job["cohort"],
                                  offset=job["offset"], limit=job["limit"])
        assert [s["id"] for s in expected] == job["source_ids"]


def test_proven_plan_still_has_exactly_nine_original_sources():
    plan = plan_validation("proven", batch_size=15)
    assert plan["planned_sources"] == 9
    assert plan["planned_jobs"] == 3


def test_warn_static_year_scoped_and_broad_blog_sources():
    sources = {s["id"]: s for s in load_sources()}
    assert "year_pinned_changelog_requires_rollover_review" in static_warnings(
        sources["pinecone_changelog"])
    assert "year_pinned_changelog_requires_rollover_review" in static_warnings(
        sources["warp_changelog"])
    assert "generic_blog_not_dedicated_release_notes" in static_warnings(
        sources["inception_labs_changelog"])


def test_plan_outputs_review_files_without_network_or_approval(tmp_path):
    plan = plan_validation("candidate", batch_size=30)
    write_plan(plan, tmp_path)
    assert (tmp_path / "validation_batches.json").exists()
    assert (tmp_path / "validation_batches.csv").exists()
    assert (tmp_path / "static_review_flags.csv").exists()
    assert plan["approved_for_advisor"] is False


@pytest.mark.parametrize("size", [0, -1, 101, "15", 15.2, True, None])
def test_unbounded_or_invalid_batch_size_rejected(size):
    with pytest.raises(ValueError):
        plan_validation(batch_size=size)


@pytest.mark.parametrize("cohort", ["all", "", None, "unsupported"])
def test_validation_planner_rejects_unscoped_cohort(cohort):
    with pytest.raises(ValueError):
        plan_validation(cohort=cohort)



def test_every_pinned_batch_uses_a_manifest_revision_and_exact_selected_ids():
    from agentfuse_crawlers.sources import load_sources, select_sources
    from agentfuse_crawlers.run_context import manifest_sha256, selection_ids_sha256
    plan = plan_validation(batch_size=15)
    assert plan["schema_version"] == 2
    assert plan["manifest_sha256"] == manifest_sha256(load_sources())
    for batch in plan["batches"]:
        assert batch["pinned_cohort"] == "all"
        assert batch["expected_manifest_sha256"] == plan["manifest_sha256"]
        ids = batch["source_ids"]
        assert batch["source_ids_csv"] == ",".join(ids)
        selected = select_sources(batch["category"], "all", source_ids=ids)
        assert selection_ids_sha256(selected) == batch["expected_selection_ids_sha256"]


def test_pinned_csv_export_has_reproducible_selection_columns(tmp_path):
    import csv
    from scripts.plan_validation import write_plan
    plan = plan_validation(batch_size=15)
    write_plan(plan, tmp_path)
    with (tmp_path / "validation_batches.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["source_ids_csv"] == ",".join(plan["batches"][0]["source_ids"])
    assert rows[0]["expected_manifest_sha256"] == plan["manifest_sha256"]
