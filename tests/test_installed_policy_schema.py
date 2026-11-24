"""Separate validation of actual packaged operator records and test isolation."""
import json
from importlib.resources import files

from agentfuse_crawlers import validation_access as policy


def test_actual_packaged_registries_use_production_schema():
    # This read deliberately bypasses the test-only resource redirection.
    # An actual reviewed campaign may contain 200-300 records and 3 plans.
    # Do not assert that it is empty; validate real data with the actual
    # production validators. This checks schema, not the truth of reviews
    # or remote permission to dispatch.
    root = files("agentfuse_crawlers")
    access = json.loads(root.joinpath(policy.ACCESS_PATH).read_text(encoding="utf-8"))
    plans = json.loads(root.joinpath(policy.RUN_PLAN_PATH).read_text(encoding="utf-8"))
    assert policy.validate_access_registry(access) == access
    assert policy.validate_plan_registry(plans) == plans


def test_test_only_registries_do_not_overwrite_real_package(isolate_operator_policy):
    root = files("agentfuse_crawlers")
    installed = root.joinpath(policy.ACCESS_PATH).read_bytes()
    isolated = isolate_operator_policy / policy.ACCESS_PATH
    assert policy.load_access_registry()["reviews"] == {}
    assert policy.load_run_plan_registry()["plans"] == {}
    data = json.loads(isolated.read_text(encoding="utf-8"))
    data["reviews"]["synthetic_invalid_id"] = {}
    isolated.write_text(json.dumps(data), encoding="utf-8")
    policy.load_access_registry.cache_clear()
    import pytest
    with pytest.raises(ValueError):
        policy.load_access_registry()
    assert root.joinpath(policy.ACCESS_PATH).read_bytes() == installed


def test_test_policy_cache_is_reset_between_cases():
    assert policy.load_access_registry()["reviews"] == {}
    assert policy.load_run_plan_registry()["plans"] == {}


def test_isolated_policy_does_not_pollute_test_output_dir(
        tmp_path, isolate_operator_policy):
    # The old autouse fixture created tmp_path/test-policy and broke tests
    # which correctly assert the exact set of exported artifact filenames.
    assert list(tmp_path.iterdir()) == []
    assert isolate_operator_policy != tmp_path
    assert tmp_path not in isolate_operator_policy.parents
    assert policy.load_access_registry()["reviews"] == {}
    assert policy.load_run_plan_registry()["plans"] == {}
