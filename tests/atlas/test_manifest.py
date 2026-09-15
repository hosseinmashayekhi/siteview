from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas.manifest.models import ArtifactRecord, DatasetManifest, RunManifest


def test_dataset_manifest_accepts_equirectangular_sha256():
    manifest = DatasetManifest(
        id="smoke-room",
        source="https://example.invalid/room.mp4",
        license="CC-BY-4.0",
        sha256="a" * 64,
        projection="equirectangular",
    )
    assert manifest.projection == "equirectangular"


def test_dataset_manifest_rejects_wrong_projection():
    with pytest.raises(ValidationError):
        DatasetManifest(
            id="bad",
            source="local",
            license="test",
            sha256="a" * 64,
            projection="perspective",
        )


def test_dataset_manifest_rejects_invalid_sha256():
    with pytest.raises(ValidationError):
        DatasetManifest(
            id="bad",
            source="local",
            license="test",
            sha256="ABC123",
            projection="equirectangular",
        )


def test_run_manifest_round_trip_preserves_provenance(tmp_path: Path):
    run = RunManifest(
        run_id="run-001",
        input_sha256="b" * 64,
        commands=[["ffprobe", "input.mp4"], ["OpenMVS", "scene.mvs"]],
        tool_versions={"ffmpeg": "8.0", "openmvs": "2.x"},
        artifacts=[ArtifactRecord(kind="mesh", path="mesh.glb", sha256="c" * 64)],
        timing_seconds={"total": 12.5},
        gpu={"name": "NVIDIA Test GPU", "vram_mb": 24576},
    )
    target = tmp_path / "run.json"
    target.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    loaded = RunManifest.model_validate_json(target.read_text(encoding="utf-8"))
    assert loaded == run
    assert loaded.commands[1][0] == "OpenMVS"
