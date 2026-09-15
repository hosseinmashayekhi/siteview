import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas.viewer.manifest import (
    ViewerAsset,
    ViewerManifest,
    write_viewer_manifest,
)


def _manifest() -> ViewerManifest:
    return ViewerManifest(
        run_id="run-001",
        input_sha256="a" * 64,
        coordinate_system="atlas-world-v1",
        initial_position=(1.0, 1.7, 2.0),
        assets=[
            ViewerAsset(
                mode="mesh",
                format="glb",
                url="artifacts/site.glb",
                sha256="b" * 64,
            ),
            ViewerAsset(
                mode="splat",
                format="gaussian-ply",
                url="artifacts/site.ply",
                sha256="c" * 64,
            ),
        ],
        evidence_index_url="evidence/evidence-index.json",
        original_frame_base_url="evidence/frames/",
        run_manifest_url="provenance/run.json",
        benchmark_report_url="provenance/benchmark.json",
    )


def test_viewer_manifest_round_trips_without_losing_provenance(tmp_path: Path):
    manifest = _manifest()

    output = write_viewer_manifest(manifest, tmp_path / "viewer")
    restored = ViewerManifest.model_validate_json(output.read_text(encoding="utf-8"))

    assert output == tmp_path / "viewer" / "viewer-manifest.json"
    assert restored == manifest
    assert restored.assets[1].sha256 == "c" * 64
    assert json.loads(output.read_text(encoding="utf-8"))["schema_version"] == 1
    assert not list((tmp_path / "viewer").glob("*.partial"))


@pytest.mark.parametrize(
    "url",
    [
        "../secret.glb",
        "/absolute/site.glb",
        "C:\\private\\site.glb",
        "https://example.com/site.glb",
        "artifacts/site.glb?token=secret",
        "artifacts/site.glb#fragment",
    ],
)
def test_viewer_manifest_rejects_non_local_or_credential_bearing_urls(url: str):
    with pytest.raises(ValidationError, match="safe relative URL"):
        ViewerAsset(
            mode="mesh", format="glb", url=url, sha256="b" * 64
        )


@pytest.mark.parametrize(
    ("mode", "format"),
    [
        ("mesh", "gaussian-ply"),
        ("splat", "glb"),
    ],
)
def test_viewer_asset_format_must_match_renderer_mode(mode: str, format: str):
    with pytest.raises(ValidationError, match="format is not valid"):
        ViewerAsset(
            mode=mode,
            format=format,
            url="artifacts/model.bin",
            sha256="b" * 64,
        )


def test_viewer_manifest_requires_assets_and_rejects_duplicate_modes():
    payload = _manifest().model_dump()
    payload["assets"] = []
    with pytest.raises(ValidationError):
        ViewerManifest.model_validate(payload)

    payload["assets"] = [
        _manifest().assets[0].model_dump(),
        _manifest().assets[0].model_dump(),
    ]
    with pytest.raises(ValidationError, match="duplicate viewer mode"):
        ViewerManifest.model_validate(payload)
