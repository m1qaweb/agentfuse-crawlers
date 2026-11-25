"""Bounded, in-job containment; never a publisher authorization mechanism.

Group the entire frozen manifest conservatively before choosing a category.
Known product families, exact providers and shared DNS suffixes are joined
transitively. A shared platform may hold multiple independent publishers;
these groups are conservative operational boundaries, not ownership proof.
"""
from math import isfinite
from time import monotonic
from urllib.parse import urlsplit

GROUP_HOLD = "validation_publisher_group_held"
GLOBAL_HOLD = "validation_global_stop_requested"
SYSTEMIC_STOP = "agentfuse_validation_systemic_access_barriers"
INTEGRITY_STOP = "agentfuse_validation_containment_integrity_failure"
PROXY_STOP = "agentfuse_validation_proxy_authentication_failure"
TRANSPORT_STOP = "agentfuse_validation_unresolved_transport_failure"
TIMEOUT_STOP = "agentfuse_validation_containment_runtime_expired"
MAX_RUNTIME_SECONDS = 3300
MAX_BLOCKED_GROUPS = 3
GROUP_BARRIERS = frozenset({
    "agentfuse_validation_http_access_denied", "agentfuse_validation_http_429",
    "agentfuse_validation_unreviewed_redirect", "agentfuse_validation_http_server_failure",
    "agentfuse_validation_robots_or_policy_denied", "agentfuse_validation_access_or_login_challenge",
})
GLOBAL_BARRIERS = frozenset({SYSTEMIC_STOP, INTEGRITY_STOP, PROXY_STOP, TRANSPORT_STOP, TIMEOUT_STOP})
FAMILIES = (
    ("OpenAI", "ChatGPT & Codex"),
    ("Google Gemini", "Google Antigravity", "Gemini CLI", "Google Cloud AI Platform"),
    ("AWS Bedrock", "AWS SageMaker AI", "Amazon Kendra", "Kiro"),
    ("Anthropic", "Claude Code"),
    ("Vercel AI Gateway", "v0"),
    ("GitHub Copilot", "Azure AI Search"),
)


def group_index(sources):
    """Stable source/origin -> component ID; shared suffix overholds safely."""
    parent = {}
    keys = {}
    origins = {}
    families = {provider: family[0] for family in FAMILIES for provider in family}

    def root(sid):
        while parent[sid] != sid:
            parent[sid] = parent[parent[sid]]
            sid = parent[sid]
        return sid

    for source in sources:
        sid, provider = source["id"], source["provider"]
        parts = urlsplit(source["url"])
        host = parts.hostname
        if (sid in parent or not host or parts.scheme != "https"
                or parts.netloc != host or "." not in host):
            raise ValueError("Invalid containment manifest identity/origin")
        parent[sid] = sid
        origins[sid] = host
        # Last two labels deliberately overgroup public suffixes (e.g. co.uk)
        # instead of fetching a mutable public suffix list during a job.
        suffix = ".".join(host.split(".")[-2:])
        for key in (("provider", families.get(provider, provider)), ("dns", suffix)):
            if key in keys:
                a, b = sorted((root(sid), root(keys[key])))
                parent[b] = a
            else:
                keys[key] = sid
    by_source = {sid: root(sid) for sid in parent}
    by_origin = {host: by_source[sid] for sid, host in origins.items()}
    return by_source, by_origin


class Containment:
    """A single spider's monotone group/global stop state, no network I/O."""

    def __init__(self, spider, sources, *, clock=monotonic, consecutive_barriers=False):
        self.spider = spider
        self.clock = clock
        self.started = clock()
        self.deadline = self.started + MAX_RUNTIME_SECONDS
        self.by_source, self.by_origin = group_index(sources)
        self.blocked = {}
        self.consecutive_barriers = consecutive_barriers
        self.recent_blocked_groups = set()
        self.healthy_sources = set()
        self.active = {}
        self.pending_at_hold = set()
        self.held_sources = set()
        self.global_reason = None

    def stop(self, reason):
        if self.global_reason is None:
            self.global_reason = reason
            self.pending_at_hold.update(self.active)
            self.spider._agentfuse_validation_stop_reason = reason

    def barrier(self, group, reason):
        if group not in self.by_source.values() or reason not in GROUP_BARRIERS:
            self.stop(INTEGRITY_STOP)
            return
        if group not in self.blocked:
            self.blocked[group] = reason
            self.recent_blocked_groups.add(group)
            self.pending_at_hold.update(token for token, g in self.active.items() if g == group)
        # Preserve the legacy reviewed-plan threshold. For explicitly selected
        # broad public diagnostics, isolated failures separated by healthy
        # primary responses are not evidence of a systemic outage. Holds
        # themselves are never cleared, and immediate systemic stops remain.
        failures = self.recent_blocked_groups if self.consecutive_barriers else self.blocked
        if len(failures) >= MAX_BLOCKED_GROUPS:
            self.stop(SYSTEMIC_STOP)

    def limit_runtime(self, seconds):
        # Zero is Scrapy's default (no extension timeout); R2 still has a
        # hard admission ceiling. A configured shorter timeout only narrows it.
        if not isinstance(seconds, (int, float)) or not isfinite(seconds) or seconds < 0:
            self.stop(INTEGRITY_STOP)
        elif seconds:
            self.deadline = min(self.deadline, self.started + seconds)

    def hold(self, group):
        if self.clock() >= self.deadline:
            self.stop(TIMEOUT_STOP)
        if self.global_reason or getattr(self.spider, "_agentfuse_validation_stop_reason", None):
            return GLOBAL_HOLD
        if group not in self.by_source.values():
            self.stop(INTEGRITY_STOP)
            return GLOBAL_HOLD
        return GROUP_HOLD if group in self.blocked else None

    def admit(self, token, group):
        if token in self.active or self.hold(group):
            self.stop(INTEGRITY_STOP)
            raise ValueError("Invalid containment admission")
        self.active[token] = group

    def finish(self, token):
        return self.active.pop(token, None)

    def observe(self, item):
        sid = item.get("source_id")
        group = self.by_source.get(sid)
        if group is None:
            self.stop(INTEGRITY_STOP)
            return
        reason, systemic = item_barrier(item)
        if systemic:
            self.stop(reason)
        elif reason:
            self.barrier(group, reason)
        elif (self.consecutive_barriers and group not in self.blocked
                and sid not in self.healthy_sources and item.get("http_status") == 200
                and item.get("status") in {"captured", "needs_review", "partial_capture"}):
            self.healthy_sources.add(sid)
            self.recent_blocked_groups.clear()
        if item.get("error") == GROUP_HOLD:
            if group not in self.blocked:
                self.stop(INTEGRITY_STOP)
            self.held_sources.add(sid)

    def annotate(self, item):
        self.observe(item)
        sid = item["source_id"]
        group = self.by_source[sid]
        item.update(
            validation_containment_group=group,
            validation_containment_block_reason=self.blocked.get(group, ""),
            validation_containment_pending_at_hold=(sid in self.pending_at_hold),
            validation_containment_global_reason=self.global_reason or "",
        )


def state_for(spider):
    state = getattr(spider, "_agentfuse_containment", None)
    return state if (getattr(spider, "collection_mode", None) == "validation"
                     and isinstance(state, Containment)) else None


def http_barrier(status):
    if status == 407:
        return PROXY_STOP, True
    if status in (401, 403, 451):
        return "agentfuse_validation_http_access_denied", False
    if status == 429:
        return "agentfuse_validation_http_429", False
    if type(status) is int and 300 <= status < 400:
        return "agentfuse_validation_unreviewed_redirect", False
    if type(status) is int and 500 <= status < 600:
        return "agentfuse_validation_http_server_failure", False
    return None, False


def item_barrier(item):
    reason, systemic = http_barrier(item.get("http_status"))
    if reason:
        return reason, systemic
    status = item.get("status")
    if status == "robots_or_policy_denied":
        return "agentfuse_validation_robots_or_policy_denied", False
    if status == "source_access_limited":
        return "agentfuse_validation_http_429", False
    if status in {"rejected_redirect", "redirect_needs_review"}:
        return "agentfuse_validation_unreviewed_redirect", False
    if status == "blocked" and item.get("error") == "access_or_login_challenge":
        return "agentfuse_validation_access_or_login_challenge", False
    if status == "fetch_error":
        return TRANSPORT_STOP, True
    return None, False


def intentional_hold(item, by_source):
    """Only exact, unfetched containment Items count as intentional holds."""
    if not (item.get("status") == "source_bulk_validation_not_approved"
            and item.get("policy_observation") == "not_fetched_by_downloader_time_access_gate"
            and item.get("http_status") is None and item.get("final_url") == ""
            and bool(by_source.get(item.get("source_id")))
            and item.get("validation_containment_group") == by_source[item["source_id"]]
            and item.get("validation_containment_pending_at_hold") is False):
        return False
    if item.get("error") == GROUP_HOLD:
        return item.get("validation_containment_block_reason") in GROUP_BARRIERS
    if item.get("error") == GLOBAL_HOLD:
        return item.get("validation_containment_global_reason") in GLOBAL_BARRIERS
    return False
