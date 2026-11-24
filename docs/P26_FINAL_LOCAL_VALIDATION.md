# P26 preflight correction — tests with reviewed source registries

Once P26A operator-reviewed records are merged, the production registries are
intentionally nonempty. Several historical regression cases previously
asserted that the *installed* registries were empty; those tests would reject
an otherwise valid P25 campaign. This change isolates default-deny and
synthetic tests using test-only resources, without weakening the production
loader, exact URL gate, plan bindings or other crawler logic.

The real packaged JSON is validated independently with the existing production
validators. Its contents are not replaced in the egg or repository.
The manual read-only preflight still checks no launch authorization and no
network actions; it reports the actual eligible count rather than insisting
it is always zero. A source review or locally eligible plan is not a verified
deployment, actual publisher permission or an advisor fact.

## One final local validation (after real source and plan review)

Use the actual final reviewed checkout, not an earlier synthetic policy
snapshot. With a preinstalled dev environment:

    python -m pytest -q
    python setup.py bdist_egg
    python -m scripts.verify_package_fingerprint
    python -m scripts.p25_large_campaign \
      --g3-all460 /secure/g3_historical_triage_all460_REVIEW_ONLY.csv \
      --target 250 --out-dir /secure/p25-final-NEW

The last report must show all selected exact URLs with current reviews and
three exact approved plans, but still cannot authorize a remote launch itself.
Check actual account budget, queue/schedules, deployment identity and
retention before the existing pinned P25 launcher is used.

Do not use the test-only empty policy directory as a deployment package.
Do not manufacture reviews or skip final validation simply to meet a count.
This correction is prepared without requesting GitHub Actions or launching a
Zyte job.

## Live robots runtime correction

The pinned Scrapy 2.18 RobotsTxtMiddleware parses HTTP error bodies and
resolves lookup/parser failures to None; its default process_request_2
allows None. ValidationRobotsMiddleware now keeps its existing parser,
but refuses unresolved robots results before the source gate. Validation
robots GETs disable redirects/retries. Exact HTTPS origin, 200 UTF-8
text/plain robots rules (or empty/comment-only file), and genuine 404/410
absence are accepted. Other statuses, redirects and ambiguous content
remain held. A denied robots response still triggers the existing global
validation stop; no further publisher access is authorized by this change.
Legacy monitoring behavior is unchanged. The conservative MIME/body checks
may hold valid but nonstandard robots files; investigate such sources
individually rather than bypassing access controls.

Upstream implementation: https://github.com/scrapy/scrapy/blob/2.18.0/scrapy/downloadermiddlewares/robotstxt.py


## R0: November 24 held-only run correction

The merged Python 3.12 suite reported 1772 passes and one failure because
the autouse fixture created `tmp_path/test-policy` inside the output
directory being tested. Use a separate `tmp_path_factory.mktemp` resource
directory; retain the original exact-directory assertion.

The three November 24 Cloud jobs returned 460 Items, no Requests, and no
usable captures. The 457 no-plan holds and 3 existing quarantine holds
are authorization/accounting evidence, not parser-quality measurements.

A recognized Cloud bulk job with zero authorized URLs now fails
construction with a NO-GO error instead of producing a held-only export.
Local held-only diagnostics still work. A positive reviewed plan is still
checked by the existing production gate; no rights are changed.

Targeted local regression command:

    python -m pytest -q tests/test_p08_canary_gates.py::test_dry_run_canary_plan_uses_exact_ids_twice_and_never_calls_network tests/test_installed_policy_schema.py tests/test_p21b_run_authorization.py

This does not replace the final full regression suite and egg validation.
Do not run a live Cloud job to test a missing plan. The P25 dispatcher
already checks positive campaign scope before scheduling. Do not commit
private Items/Requests/Logs or fabricated permissions to the public repo.
