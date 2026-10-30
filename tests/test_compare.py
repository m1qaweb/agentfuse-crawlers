from scripts.compare_exports import compare


def row(source_id, content_hash, status="captured"):
    return {
        "source_id": source_id,
        "provider": "Example",
        "category": "pricing",
        "status": status,
        "content_sha256": content_hash,
        "source_url": "https://example.com/pricing",
    }


def test_compare_hashes_without_claiming_price_changes():
    current = {
        "x": row("x", "b"),
        "y": row("y", "a"),
        "z": row("z", "", status="http_error"),
    }
    previous = {"x": row("x", "a"), "y": row("y", "a")}
    result = {c["source_id"]: c["change_type"] for c in compare(current, previous)}
    assert result == {"x": "page_text_changed", "y": "unchanged", "z": "not_captured"}


def test_new_baseline():
    assert compare({"x": row("x", "a")}, {})[0]["change_type"] == "new_baseline"
