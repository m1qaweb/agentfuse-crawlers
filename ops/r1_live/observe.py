"""One-time public robots-policy observations, not a crawler or authorization.

No publisher HTML, no proxy, no retry, no redirect, no Zyte or credentials.
Exact original 259-ID queue. Keep policy body bytes only in process memory;
emit bounded status, content hashes, and per-URL Protego decisions.
"""
import hashlib
import json
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from protego import Protego
from agentfuse_crawlers.robots_policy import reviewed_robots_body, MAX_ROBOTS_BYTES
from agentfuse_crawlers.settings import USER_AGENT

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_UA = "AgentFuseResearchBot/0.1 (+https://github.com/m1qaweb/agentfuse-crawlers)"
MANIFEST_SHA = "4e3d73f8e50a7348e22a7748127d5e1eb0163b1d059fb2caaa091a6e5e9c83b3"
QUEUE_SHA = "46dc7a8ef9a7342f929fe3cefafd141a838ee32cd67c77530673c9f29f227b5c"

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def now():
    return datetime.now(timezone.utc).isoformat()

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def origin(url):
    p = urlsplit(url)
    if p.scheme != "https" or p.netloc != p.hostname or not p.hostname or not re.fullmatch(r"[a-z0-9.-]+", p.hostname) or p.fragment:
        raise ValueError("noncanonical manifest URL")
    return "https://" + p.netloc

def observe(o, sources):
    url = o + "/robots.txt"
    start = time.monotonic()
    result = dict(origin=o, robots_url=url, started_at_utc=now(), http_status=None,
                  observation="unresolved", body_sha256=None, body_bytes=None,
                  authorization=False)
    decisions = {s["id"]: "unresolved" for s in sources}
    try:
        req = Request(url, headers={"User-Agent": EXPECTED_UA,
                      "Accept": "text/plain,*/*;q=0.1", "Accept-Encoding": "identity",
                      "Cache-Control": "no-cache"})
        try:
            resp = build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=15)
        except HTTPError as error:
            resp = error
        with resp:
            status = resp.code
            actual = resp.geturl()
            result["http_status"] = status
            if actual != url:
                raise ValueError("robots_exact_origin_mismatch")
            if status not in (200, 404, 410):
                raise ValueError("robots_http_status_unresolved")
            content_type = (resp.headers.get("Content-Type") or "").encode("latin-1")
            if status == 200:
                if (resp.headers.get("Content-Encoding") or "identity").strip().lower() != "identity":
                    raise ValueError("robots_content_encoding_unresolved")
                raw = resp.read(MAX_ROBOTS_BYTES + 1)
                result["body_bytes"] = len(raw)
                if len(raw) > MAX_ROBOTS_BYTES:
                    raise ValueError("robots_body_unresolved_or_oversize")
                result["body_sha256"] = sha(raw)
            else:
                raw = b""
            body = reviewed_robots_body(expected_url=url, response_url=actual,
                    status=status, content_type=content_type, body=raw)
            if status in (404, 410):
                result["observation"] = "missing_file_not_authorization"
                decisions = {s["id"]: "missing_file_not_authorization" for s in sources}
            else:
                parser = Protego.parse(body.decode("utf-8-sig"))
                decisions = {s["id"]: "robots_rules_allow_not_authorization"
                             if parser.can_fetch(s["url"], EXPECTED_UA)
                             else "robots_rules_deny" for s in sources}
                result["observation"] = "strict_plaintext_rules_evaluated"
    except Exception as exc:
        # No response text, redirects, tokens or arbitrary server messages in public logs.
        result["reason"] = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r"robots_[a-z0-9_]+", str(exc)) else type(exc).__name__
    result["source_decisions"] = decisions
    result["finished_at_utc"] = now()
    result["elapsed_seconds"] = round(time.monotonic() - start, 3)
    return result

def write_report(path, report):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)

def main():
    raw = (ROOT / "agentfuse_crawlers/data/sources.json").read_bytes()
    queue = (Path(__file__).parent / "queue_ids.txt").read_bytes()
    if sha(raw) != MANIFEST_SHA or sha(queue) != QUEUE_SHA or USER_AGENT != EXPECTED_UA:
        raise SystemExit("NO-GO: manifest, original queue, or bot identity mismatch")
    rows = json.loads(raw)
    selected = queue.decode("ascii").splitlines()
    index = {s["id"]: s for s in rows}
    assert len(rows) == len(index) == 460
    assert len(selected) == len(set(selected)) == 259
    assert not {"v0_docs", "v0_pricing", "v0_changelog"}.intersection(selected)
    groups = defaultdict(list)
    for sid in selected:
        s = index[sid]
        groups[origin(s["url"])].append(s)
    assert len(groups) == 140
    assert Counter(index[s]["category"] for s in selected) == {"pricing": 100, "documentation": 100, "changelog": 59}
    report = dict(schema="r1_public_policy_observations_without_raw_body_v1",
                  purpose="public_policy_evidence_only_not_approval",
                  manifest_sha256=MANIFEST_SHA, queue_sha256=QUEUE_SHA,
                  user_agent=EXPECTED_UA, started_at_utc=now(), complete=False,
                  origin_count=len(groups), candidate_count=len(selected),
                  publisher_html_requests=0, zyte_jobs=0, source_approvals=0,
                  results=[])
    path = Path("r1_policy_observations.json")
    write_report(path, report)
    print("POLICY_SCOPE", len(groups), len(selected), flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = [pool.submit(observe, o, ss) for o, ss in groups.items()]
        for task in as_completed(tasks):
            result = task.result()
            report["results"].append(result)
            write_report(path, report)
            print("POLICY_OBSERVATION", json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
    report["complete"] = True
    report["finished_at_utc"] = now()
    report["results"].sort(key=lambda x: x["origin"])
    report["counts"] = dict(Counter(d for r in report["results"] for d in r["source_decisions"].values()))
    write_report(path, report)
    print("POLICY_SUMMARY", json.dumps(report["counts"], sort_keys=True), flush=True)

if __name__ == "__main__":
    main()
