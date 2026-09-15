from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas.manifest.models import (
    ArtifactRecord,
    DatasetManifest,
    RunManifest,
    VideoProbe,
)


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


def test_dataset_manifest_rejects_unknown_fields_instead_of_losing_them():
    with pytest.raises(ValidationError):
        DatasetManifest(
            id="smoke-room",
            source="https://example.invalid/room.mp4",
            license="CC-BY-4.0",
            sha256="a" * 64,
            projection="equirectangular",
            untracked_provenance="would otherwise be dropped",
        )


def test_video_probe_records_inspection_metadata():
    probe = VideoProbe(
        width=7680,
        height=3840,
        fps=30000 / 1001,
        duration_seconds=12.5,
        codec_name="hevc",
        frame_count=375,
    )

    assert probe.model_dump() == {
        "width": 7680,
        "height": 3840,
        "fps": 30000 / 1001,
        "duration_seconds": 12.5,
        "codec_name": "hevc",
        "frame_count": 375,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("width", 0),
        ("height", -1),
        ("fps", 0),
        ("duration_seconds", -0.1),
        ("frame_count", -1),
    ],
)
def test_video_probe_rejects_impossible_measurements(field: str, value: float):
    values = {
        "width": 7680,
        "height": 3840,
        "fps": 30.0,
        "duration_seconds": 12.5,
        "frame_count": 375,
    }
    values[field] = value

    with pytest.raises(ValidationError):
        VideoProbe(**values)


def test_artifact_record_rejects_invalid_sha256():
    with pytest.raises(ValidationError):
        ArtifactRecord(kind="mesh", path="mesh.glb", sha256="not-a-hash")


def test_run_manifest_rejects_invalid_input_sha256():
    with pytest.raises(ValidationError):
        RunManifest(
            run_id="run-001",
            input_sha256="not-a-hash",
            commands=[],
            tool_versions={},
            artifacts=[],
            timing_seconds={},
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
