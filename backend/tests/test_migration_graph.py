from pathlib import Path
import ast


def _literal_assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is missing in {path.name}")


def test_alembic_revision_graph_has_one_connected_head() -> None:
    versions = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    migrations = list(versions.glob("*.py"))
    revisions = {_literal_assignment(path, "revision"): path for path in migrations}
    referenced: set[str] = set()

    for revision, path in revisions.items():
        down_revision = _literal_assignment(path, "down_revision")
        parents = down_revision if isinstance(down_revision, tuple) else (down_revision,)
        for parent in parents:
            if parent is None:
                continue
            assert parent in revisions, f"{revision} references missing parent {parent}"
            referenced.add(parent)

    heads = set(revisions) - referenced
    roots = [path for revision, path in revisions.items() if _literal_assignment(path, "down_revision") is None]
    assert len(roots) == 1, f"Expected one migration root, got {[path.name for path in roots]}"
    assert len(heads) == 1, f"Expected one migration head, got {sorted(heads)}"
