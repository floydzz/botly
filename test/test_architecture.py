import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"

PROVIDER_NAMES = (
    "telegram",
    "whatsapp",
    "shopee",
    "rednote",
    "lazada",
    "tiktok",
    "messenger",
    "instagram",
)


def _docstring_ids(tree: ast.AST) -> set[int]:
    """Identity of every docstring node, so prose may name providers freely."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def test_no_module_outside_channels_names_a_provider():
    """Capability differences belong in a manifest, not scattered conditionals.

    Only string literals are checked. Comments and docstrings may explain what a
    provider is; what they may not do is let code compare against the name.
    """
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if "channels" in path.relative_to(APP).parts:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        docstrings = _docstring_ids(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                lowered = node.value.lower()
                hit = next((n for n in PROVIDER_NAMES if n in lowered), None)
                if hit:
                    offenders.append(
                        f"{path.relative_to(APP.parent)}:{node.lineno} "
                        f"names {hit!r} in {node.value!r}"
                    )
    assert not offenders, (
        "provider names belong in app/channels/<provider>/ only:\n  "
        + "\n  ".join(offenders)
    )


def test_the_guard_would_catch_a_violation():
    """The guard above passes trivially if the walk is wrong. Prove it can fail."""
    tree = ast.parse('def route(p):\n    if p == "telegram":\n        return 1\n')
    docstrings = _docstring_ids(tree)
    found = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in docstrings
        and any(name in n.value.lower() for name in PROVIDER_NAMES)
    ]
    assert found == ["telegram"]
