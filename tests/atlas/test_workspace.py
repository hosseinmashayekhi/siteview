import json

import pytest

from atlas.environment.workspace import WorkspaceError, initialize_workspace


def test_initialize_workspace_keeps_generated_data_beside_the_repository(tmp_path):
    atlas_root = tmp_path / "3dcamera"
    repo_root = atlas_root / "siteview"
    repo_root.mkdir(parents=True)

    layout = initialize_workspace(atlas_root=atlas_root, repo_root=repo_root)

    assert layout.repo_root == str(repo_root.resolve())
    assert layout.data_root == str((atlas_root / "data").resolve())
    assert set(layout.directories) == {
        "datasets",
        "runs",
        "frames",
        "mesh",
        "splats",
        "reports",
    }
    assert all((atlas_root / "data" / name).is_dir() for name in layout.directories)
    assert not (repo_root / "data").exists()
    manifest = json.loads(
        (atlas_root / "data" / "workspace.json").read_text(encoding="utf-8")
    )
    assert manifest == layout.model_dump()


def test_initialize_workspace_is_idempotent_and_replaces_stale_manifest(tmp_path):
    atlas_root = tmp_path / "3dcamera"
    repo_root = atlas_root / "siteview"
    repo_root.mkdir(parents=True)
    data_root = atlas_root / "data"
    data_root.mkdir()
    (data_root / "workspace.json").write_text("stale", encoding="utf-8")

    first = initialize_workspace(atlas_root=atlas_root, repo_root=repo_root)
    second = initialize_workspace(atlas_root=atlas_root, repo_root=repo_root)

    assert first == second
    assert not (data_root / "workspace.json.partial").exists()


def test_initialize_workspace_rejects_data_directory_inside_repository(tmp_path):
    repo_root = tmp_path / "siteview"
    repo_root.mkdir()

    with pytest.raises(WorkspaceError, match="outside the Git repository"):
        initialize_workspace(atlas_root=repo_root, repo_root=repo_root)
