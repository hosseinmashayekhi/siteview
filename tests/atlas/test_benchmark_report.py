import hashlib
import json
from pathlib import Path

import pytest

from atlas.benchmark.report import (
    BenchmarkMeasurements,
    BenchmarkReportError,
    DetailAssessment,
    ViewerAssessment,
    build_benchmark_report,
    write_benchmark_report,
)
from atlas.manifest.models import ArtifactRecord, RunManifest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_manifest(tmp_path: Path, *, valid_hash: bool = True) -> RunManifest:
    splat = tmp_path / "viewer-splat.ply"
    splat.write_bytes(b"ply\nformat ascii 1.0\nend_header\n")
    digest = _sha256(splat) if valid_hash else "0" * 64
    return RunManifest(
        run_id="run-001",
        input_sha256="a" * 64,
        commands=[["gsplat", "--data_dir", "prepared"]],
        tool_versions={"gsplat": "1.6.0", "torch": "2.7.1"},
        artifacts=[
            ArtifactRecord(
                kind="viewer-splat",
                path=str(splat),
                sha256=digest,
            )
        ],
        timing_seconds={"total": 120.5},
        gpu={"model": "Fake RTX", "memory_bytes": 24_000_000_000},
    )


def _measurements() -> BenchmarkMeasurements:
    return BenchmarkMeasurements(
        pipeline_success=True,
        wall_clock_seconds=120.5,
        total_frames=100,
        registered_frames=92,
        trajectory_continuous=True,
        trajectory_max_gap_seconds=0.8,
        point_count=1_000_000,
        triangle_count=None,
        splat_count=2_000_000,
        visible_holes=False,
        detail_regions=[
            DetailAssessment(
                region_id="pipe-joint",
                required=True,
                usable=True,
                visible_holes=False,
                notes="Joint remains distinguishable.",
                evidence_artifacts=["detail-pipe-joint.png"],
            )
        ],
        viewer=ViewerAssessment(opened=True, free_walk_verified=True),
        evidence_lookup_correct=True,
    )


def test_build_report_verifies_artifacts_and_calculates_registration_ratio(
    tmp_path: Path,
):
    run = _run_manifest(tmp_path)

    report = build_benchmark_report(
        run,
        benchmark_id="atlas-indoor-360-v1",
        candidate_id="gsplat-baseline",
        pipeline_version="git:abc123",
        configuration_sha256="b" * 64,
        measurements=_measurements(),
    )

    assert report.trajectory.registered_ratio == pytest.approx(0.92)
    assert report.artifacts[0].size_bytes == (tmp_path / "viewer-splat.ply").stat().st_size
    assert report.artifacts[0].sha256 == run.artifacts[0].sha256
    assert report.provenance.complete is True
    assert report.provenance.missing_fields == []
    assert report.gpu == {"model": "Fake RTX", "memory_bytes": 24_000_000_000}


def test_missing_measurements_remain_null_in_json_and_markdown(tmp_path: Path):
    report = build_benchmark_report(
        _run_manifest(tmp_path),
        benchmark_id="atlas-indoor-360-v1",
        candidate_id="gsplat-baseline",
        pipeline_version="git:abc123",
        configuration_sha256="b" * 64,
        measurements=BenchmarkMeasurements(pipeline_success=True),
    )

    json_path, markdown_path = write_benchmark_report(report, tmp_path / "report")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["wall_clock_seconds"] is None
    assert payload["trajectory"]["registered_ratio"] is None
    assert payload["triangle_count"] is None
    assert payload["viewer"]["opened"] is None
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "| Wall clock seconds | NULL |" in markdown
    assert "| Registered-frame ratio | NULL |" in markdown
    assert "| Triangle count | NULL |" in markdown
    assert not list((tmp_path / "report").glob("*.partial"))


def test_build_report_rejects_artifact_hash_mismatch(tmp_path: Path):
    with pytest.raises(BenchmarkReportError, match="artifact hash mismatch"):
        build_benchmark_report(
            _run_manifest(tmp_path, valid_hash=False),
            benchmark_id="atlas-indoor-360-v1",
            candidate_id="gsplat-baseline",
            pipeline_version="git:abc123",
            configuration_sha256="b" * 64,
            measurements=BenchmarkMeasurements(pipeline_success=True),
        )


@pytest.mark.parametrize(
    ("success", "failure_reason", "message"),
    [
        (True, "CUDA failed", "successful report cannot have a failure reason"),
        (False, None, "failed report requires a failure reason"),
    ],
)
def test_measurements_require_consistent_failure_reason(
    success: bool,
    failure_reason: str | None,
    message: str,
):
    with pytest.raises(ValueError, match=message):
        BenchmarkMeasurements(
            pipeline_success=success,
            failure_reason=failure_reason,
        )


def test_registered_frames_cannot_exceed_total_frames():
    with pytest.raises(ValueError, match="registered frames cannot exceed total"):
        BenchmarkMeasurements(
            pipeline_success=True,
            total_frames=10,
            registered_frames=11,
        )


def test_provenance_marks_empty_command_and_version_records_incomplete(tmp_path: Path):
    run = _run_manifest(tmp_path)
    run.commands = []
    run.tool_versions = {}

    report = build_benchmark_report(
        run,
        benchmark_id="atlas-indoor-360-v1",
        candidate_id="gsplat-baseline",
        pipeline_version="git:abc123",
        configuration_sha256="b" * 64,
        measurements=BenchmarkMeasurements(pipeline_success=True),
    )

    assert report.provenance.complete is False
    assert report.provenance.missing_fields == ["commands", "tool_versions"]
