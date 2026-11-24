"""Keep offline regression tests independent of operator-reviewed live policy.

The production registries may be nonempty. Test-only empty registries retain
the default-deny contract, while individual tests inject their existing
synthetic records. The real packaged registry schema is verified separately.
No environment toggle or production loader change is introduced.
"""
import json
from importlib.resources import files as package_files

import pytest

from agentfuse_crawlers import validation_access as policy


@pytest.fixture(autouse=True)
def isolate_operator_policy(tmp_path_factory, monkeypatch):
    """Redirect only validation_access's two packaged resource reads.

    Patching resource lookup instead of replacing loader functions also covers
    modules that imported the original cached functions by name. It does not
    modify package_fingerprint(), source lifecycle, manifest or disk policy.
    """
    # Keep policy resources outside the calling test's output directory.
    root = tmp_path_factory.mktemp("operator-policy")
    access = {"schema_version": policy.SCHEMA, "kind": policy.ACCESS_KIND,
              "default_decision": "not_reviewed", "reviews": {}}
    plans = {"schema_version": policy.SCHEMA, "kind": policy.PLAN_KIND,
             "default_policy": "no_bulk_runs_authorized", "plans": {}}
    for path, obj in ((policy.ACCESS_PATH, access), (policy.RUN_PLAN_PATH, plans)):
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(obj), encoding="utf-8")
    loaders = (policy.load_access_registry, policy.load_run_plan_registry)
    for loader in loaders:
        loader.cache_clear()
    with monkeypatch.context() as scoped:
        scoped.setattr(policy, "files", lambda name: (
            root if name == "agentfuse_crawlers" else package_files(name)
        ))
        try:
            yield root
        finally:
            # Clear the actual cached functions captured before the test.
            # Individual tests may temporarily replace module-level aliases.
            for loader in loaders:
                loader.cache_clear()
