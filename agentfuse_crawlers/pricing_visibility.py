"""Explicitly non-rendered HTML guards for pricing evidence, not a browser.

Only deterministic HTML visibility evidence is honored: boolean hidden/inert,
aria-hidden=true, closed details/dialogs, and effective inline CSS display,
visibility, content-visibility or opacity. External stylesheets, responsive
classes, scripts, shadow DOM and dynamic selectors cannot be evaluated here.
An absent price in a static HTML snapshot is NOT proof of no vendor price.
"""
import re

_HIDDEN_CSS = {
    "display": {"none"},
    "visibility": {"hidden", "collapse"},
    "content-visibility": {"hidden"},
    "opacity": {"0", "0.0", "0.00", "0.000"},
}
_IMPORTANT = re.compile(r"!\s*important\s*$", re.I)


def _tag(node):
    return node.tag.casefold() if isinstance(node.tag, str) else ""


def _hidden_css(style):
    if not isinstance(style, str):
        return False
    # Honor the last declaration at the highest !important priority.
    # Avoid accidental substring matches such as --display:none or
    # "display:none" inside a script's quoted text.
    effective = {}
    for index, clause in enumerate(style.split(";")):
        if ":" not in clause:
            continue
        prop, value = clause.split(":", 1)
        prop = prop.strip().casefold()
        if prop not in _HIDDEN_CSS:
            continue
        important = bool(_IMPORTANT.search(value))
        value = _IMPORTANT.sub("", value).strip().casefold()
        if not value:
            continue
        priority = (1 if important else 0, index)
        if prop not in effective or priority >= effective[prop][0]:
            effective[prop] = (priority, value)
    return any(value in _HIDDEN_CSS[prop]
               for prop, (_, value) in effective.items())


def explicitly_nonvisible(node):
    """Whether this node ITSELF explicitly hides its subtree in static HTML."""
    if not hasattr(node, "attrib"):
        return False
    tag = _tag(node)
    if (("hidden" in node.attrib) or ("inert" in node.attrib)
            or str(node.attrib.get("aria-hidden", "")).strip().casefold() == "true"
            or _hidden_css(node.get("style", ""))):
        return True
    # Closed dialogs are not displayed; <details> bodies may be activated
    # interactively, but are not currently visible in the static snapshot.
    if tag in {"dialog", "details"} and "open" not in node.attrib:
        return True
    return False


def in_explicitly_nonvisible_context(node):
    """Require original source scope to be visibly rendered (or refuse it)."""
    if explicitly_nonvisible(node):
        return True
    return any(explicitly_nonvisible(parent) for parent in node.iterancestors())


def prune_explicitly_nonvisible(root):
    """Prune hidden pricing subtrees IN PLACE; return root and honest count.

    Does not change production category classification or fetch anything.
    Root/ancestor-hidden pages become empty, so their rates cannot leak
    through original HTML that does not actually expose the main content.
    """
    if in_explicitly_nonvisible_context(root):
        root.clear()
        return root, 1
    removed = 0
    pending = list(reversed(list(root)))
    while pending:
        node = pending.pop()
        if explicitly_nonvisible(node):
            if node.getparent() is not None:
                node.drop_tree()
                removed += 1
        else:
            pending.extend(reversed(list(node)))
    return root, removed
