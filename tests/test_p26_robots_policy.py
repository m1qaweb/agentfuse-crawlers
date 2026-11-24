"""Network-free tests of the exact-origin robots response policy."""
import pytest

from agentfuse_crawlers.robots_policy import MAX_ROBOTS_BYTES, reviewed_robots_body

URL = "https://example.test/robots.txt"
RULES = b"User-agent: *\nDisallow: /private/\nAllow: /\n"


def evaluate(**updates):
    values = dict(expected_url=URL, response_url=URL, status=200,
                  content_type=b"text/plain; charset=utf-8", body=RULES)
    values.update(updates)
    return reviewed_robots_body(**values)


@pytest.mark.parametrize("body", [
    RULES, b"", b"# only a comment\n",
    b"\xef\xbb\xbfUser-agent: *\r\nDisallow:\r\n",
    b"Sitemap: https://example.test/sitemap.xml\n",
    b"User-agent: *\nContent-Signal: search=yes\nDisallow: /login\n",
])
def test_accepted_robots_keeps_exact_bytes(body):
    assert evaluate(body=body) == body


@pytest.mark.parametrize("status", [404, 410])
def test_missing_robots_does_not_parse_error_page(status):
    assert evaluate(status=status, content_type=b"text/html",
                    body=b"<html>Not found</html>") == b""


@pytest.mark.parametrize("status", [204, 301, 302, 307, 308, 400, 401, 403,
                                     407, 429, 451, 500, 503])
def test_nonmissing_http_failure_is_never_permission(status):
    with pytest.raises(ValueError, match="robots_http_status_unresolved"):
        evaluate(status=status)


@pytest.mark.parametrize("updates,reason", [
    ({"response_url": "https://other.test/robots.txt"}, "origin_mismatch"),
    ({"response_url": URL + "?redirect=1"}, "origin_mismatch"),
    ({"content_type": b"text/html"}, "media_type"),
    ({"content_type": b""}, "media_type"),
    ({"body": b"<html>challenge</html>"}, "not_plain_directives"),
    ({"body": b"Error: Access denied"}, "no_recognizable_rules"),
    ({"body": b"Disallow: /"}, "no_recognizable_rules"),
    ({"body": b"User-agent: *\x00"}, "control_characters"),
    ({"body": b"\xff"}, "invalid_utf8"),
    ({"body": b"x" * (MAX_ROBOTS_BYTES + 1)}, "oversize"),
])
def test_ambiguous_content_is_held(updates, reason):
    with pytest.raises(ValueError, match=reason):
        evaluate(**updates)
