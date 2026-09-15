from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas.manifest.models import (
    ArtifactRecord,
    DatasetCharacteristics,
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


def test_dataset_manifest_preserves_download_and_benchmark_provenance():
    expected_probe = VideoProbe(
        width=3840,
        height=1920,
        fps=29.678,
        duration_seconds=118.174,
        codec_name="vp9",
        frame_count=None,
    )
    manifest = DatasetManifest(
        id="benchmark-train-interior",
        tier="benchmark",
        title="Moving 360 train interior",
        source="https://example.invalid/train.webm",
        source_page="https://example.invalid/dataset",
        license="CC-BY-3.0",
        license_url="https://creativecommons.org/licenses/by/3.0/",
        attribution="Example Author",
        sha256="d" * 64,
        size_bytes=200_815_472,
        filename="train-interior.webm",
        projection="equirectangular",
        expected_probe=expected_probe,
        characteristics=DatasetCharacteristics(
            indoor=True,
            moving_camera=True,
            revisits=None,
            visual_overlap=True,
            parallax=True,
        ),
        purpose="Frozen geometry and visual-detail benchmark.",
    )

    assert manifest.expected_probe == expected_probe
    assert manifest.characteristics.revisits is None
    assert manifest.model_dump(mode="json")["filename"] == "train-interior.webm"


@pytest.mark.parametrize("filename", ["../video.webm", "sub/video.webm", r"sub\video.webm"])
def test_dataset_manifest_rejects_filename_path_traversal(filename: str):
    with pytest.raises(ValidationError):
        DatasetManifest(
            id="bad-path",
            source="https://example.invalid/video.webm",
            license="CC-BY-4.0",
            sha256="a" * 64,
            projection="equirectangular",
            filename=filename,
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
