"""Create the local Atlas data workspace outside the Git repository."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


DATA_DIRECTORIES = ("datasets", "runs", "frames", "mesh", "splats", "reports")


class WorkspaceError(RuntimeError):
    """Raised when the requested workspace would mix data with source code."""


class WorkspaceLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    atlas_root: str
    repo_root: str
    data_root: str
    directories: dict[str, str]


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def initialize_workspace(*, atlas_root: Path, repo_root: Path) -> WorkspaceLayout:
    """Create idempotent source/data sibling directories and a local manifest."""
    atlas_root = Path(atlas_root).resolve()
    repo_root = Path(repo_root).resolve()
    if not repo_root.is_dir():
        raise WorkspaceError(f"Git repository does not exist: {repo_root}")

    data_root = (atlas_root / "data").resolve()
    if _is_within(data_root, repo_root):
        raise WorkspaceError(
            "Atlas data directory must remain outside the Git repository"
        )

    directories = {
        name: str((data_root / name).resolve()) for name in DATA_DIRECTORIES
    }
    for path in directories.values():
        Path(path).mkdir(parents=True, exist_ok=True)

    layout = WorkspaceLayout(
        atlas_root=str(atlas_root),
        repo_root=str(repo_root),
        data_root=str(data_root),
        directories=directories,
    )
    destination = data_root / "workspace.json"
    partial = data_root / "workspace.json.partial"
    partial.write_text(layout.model_dump_json(indent=2) + "\n", encoding="utf-8")
    partial.replace(destination)
    return layout
