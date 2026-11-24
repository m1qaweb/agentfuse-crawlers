"""Pure validation of a live exact-origin robots response before parsing.

This is a conservative project policy, not a general RFC 9309 implementation
or a publisher license. Scrapy still applies its normal robots parser to
accepted responses; a missing, failed or ambiguous lookup never authorizes
a validation page GET.
"""
import re

MAX_ROBOTS_BYTES = 500 * 1024
DIRECTIVE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*\s*:\s*(.*)$")


def reviewed_robots_body(*, expected_url, response_url, status, content_type, body):
    """Return bytes safe to pass to the actual Scrapy robots parser.

    Only exact-origin 200 plaintext rules and a real 404/410 missing file
    are accepted. In the latter case discard the HTTP error body. Every
    other status, redirected response or non-robots document is unresolved.
    """
    if response_url != expected_url:
        raise ValueError("robots_exact_origin_mismatch")
    if status in (404, 410):
        return b""
    if status != 200:
        raise ValueError("robots_http_status_unresolved")
    if not isinstance(body, bytes) or len(body) > MAX_ROBOTS_BYTES:
        raise ValueError("robots_body_unresolved_or_oversize")
    if (not isinstance(content_type, bytes)
            or content_type.split(b";", 1)[0].strip().lower() != b"text/plain"):
        raise ValueError("robots_media_type_unresolved")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("robots_invalid_utf8") from exc
    if any(ord(c) < 32 and c not in "\t\r\n" for c in text) or "\x7f" in text:
        raise ValueError("robots_invalid_control_characters")
    active = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        match = DIRECTIVE.fullmatch(line)
        if match is None:
            raise ValueError("robots_not_plain_directives")
        key, value = line.split(":", 1)
        active.append((key.strip().lower(), value.strip()))
    # Empty/comment-only files are genuine no-rule responses. Nonempty
    # files must look like robots rules or sitemap-only robots documents,
    # rather than a plaintext error page such as "Error: access denied".
    if active and not any(
            key in ("user-agent", "sitemap") and value
            for key, value in active):
        raise ValueError("robots_no_recognizable_rules")
    # Pass original bytes, not rewritten rules, to Scrapy.
    return body
