"""Measured, provenance-preserving benchmark reports.

Unknown values deliberately remain ``None`` so JSON renders them as ``null`` and
the human-readable report renders them as ``NULL``.  A report must never fill a
missing measurement with an estimate.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, NonNegativeFloat, NonNegativeInt, model_validator

from atlas.manifest.models import AtlasModel, RunManifest, Sha256


class BenchmarkReportError(RuntimeError):
    """Raised when source provenance cannot be verified."""


class ArtifactMeasurement(AtlasModel):
    """A verified output artifact and its measured byte size."""

    kind: str
    path: str
    sha256: Sha256
    size_bytes: NonNegativeInt


class DetailAssessment(AtlasModel):
    """Structured inspection of one benchmark detail region."""

    region_id: str
    required: bool
    usable: bool | None = None
    visible_holes: bool | None = None
    notes: str | None = None
    evidence_artifacts: list[str] = Field(default_factory=list)


class ViewerAssessment(AtlasModel):
    """Results of loading and navigating an artifact in the Atlas viewer."""

    opened: bool | None = None
    free_walk_verified: bool | None = None


class TrajectoryAssessment(AtlasModel):
    """Measured registration and camera-path continuity."""

    total_frames: NonNegativeInt | None = None
    registered_frames: NonNegativeInt | None = None
    registered_ratio: float | None = None
    continuous: bool | None = None
    max_gap_seconds: NonNegativeFloat | None = None


class ProvenanceStatus(AtlasModel):
    """Whether the report contains the minimum reproducibility records."""

    complete: bool
    missing_fields: list[str]


class BenchmarkMeasurements(AtlasModel):
    """Measurements supplied by tools or a human inspection.

    Every optional field defaults to ``None`` rather than a guessed value.
    """

    pipeline_success: bool
    failure_reason: str | None = None
    wall_clock_seconds: NonNegativeFloat | None = None
    total_frames: NonNegativeInt | None = None
    registered_frames: NonNegativeInt | None = None
    trajectory_continuous: bool | None = None
    trajectory_max_gap_seconds: NonNegativeFloat | None = None
    point_count: NonNegativeInt | None = None
    triangle_count: NonNegativeInt | None = None
    splat_count: NonNegativeInt | None = None
    visible_holes: bool | None = None
    detail_regions: list[DetailAssessment] = Field(default_factory=list)
    viewer: ViewerAssessment = Field(default_factory=ViewerAssessment)
    evidence_lookup_correct: bool | None = None

    @model_validator(mode="after")
    def validate_consistency(self) -> "BenchmarkMeasurements":
        reason_present = bool(self.failure_reason and self.failure_reason.strip())
        if self.pipeline_success and reason_present:
            raise ValueError("successful report cannot have a failure reason")
        if not self.pipeline_success and not reason_present:
            raise ValueError("failed report requires a failure reason")
        if (
            self.total_frames is not None
            and self.registered_frames is not None
            and self.registered_frames > self.total_frames
        ):
            raise ValueError("registered frames cannot exceed total")
        return self


class BenchmarkReport(AtlasModel):
    """Frozen report consumed by the anti-scope-drift gate."""

    schema_version: Literal["atlas-benchmark-report-v1"] = (
        "atlas-benchmark-report-v1"
    )
    benchmark_id: str
    candidate_id: str
    pipeline_version: str
    configuration_sha256: Sha256
    run_id: str
    input_sha256: Sha256
    pipeline_success: bool
    failure_reason: str | None
    wall_clock_seconds: NonNegativeFloat | None
    gpu: dict[str, Any] | None
    tool_versions: dict[str, str]
    commands: list[list[str]]
    artifacts: list[ArtifactMeasurement]
    trajectory: TrajectoryAssessment
    point_count: NonNegativeInt | None
    triangle_count: NonNegativeInt | None
    splat_count: NonNegativeInt | None
    visible_holes: bool | None
    detail_regions: list[DetailAssessment]
    viewer: ViewerAssessment
    evidence_lookup_correct: bool | None
    provenance: ProvenanceStatus


def build_benchmark_report(
    run: RunManifest,
    *,
    benchmark_id: str,
    candidate_id: str,
    pipeline_version: str,
    configuration_sha256: str,
    measurements: BenchmarkMeasurements,
) -> BenchmarkReport:
    """Verify run artifacts and combine them with measured benchmark results."""
    artifacts = [_verify_artifact(record) for record in run.artifacts]
    missing_fields: list[str] = []
    if not run.commands:
        missing_fields.append("commands")
    if not run.tool_versions:
        missing_fields.append("tool_versions")
    if not artifacts:
        missing_fields.append("artifacts")

    ratio: float | None = None
    if measurements.total_frames is not None and measurements.total_frames > 0:
        if measurements.registered_frames is not None:
            ratio = measurements.registered_frames / measurements.total_frames

    return BenchmarkReport(
        benchmark_id=benchmark_id,
        candidate_id=candidate_id,
        pipeline_version=pipeline_version,
        configuration_sha256=configuration_sha256,
        run_id=run.run_id,
        input_sha256=run.input_sha256,
        pipeline_success=measurements.pipeline_success,
        failure_reason=measurements.failure_reason,
        wall_clock_seconds=measurements.wall_clock_seconds,
        gpu=run.gpu,
        tool_versions=dict(run.tool_versions),
        commands=[list(command) for command in run.commands],
        artifacts=artifacts,
        trajectory=TrajectoryAssessment(
            total_frames=measurements.total_frames,
            registered_frames=measurements.registered_frames,
            registered_ratio=ratio,
            continuous=measurements.trajectory_continuous,
            max_gap_seconds=measurements.trajectory_max_gap_seconds,
        ),
        point_count=measurements.point_count,
        triangle_count=measurements.triangle_count,
        splat_count=measurements.splat_count,
        visible_holes=measurements.visible_holes,
        detail_regions=list(measurements.detail_regions),
        viewer=measurements.viewer,
        evidence_lookup_correct=measurements.evidence_lookup_correct,
        provenance=ProvenanceStatus(
            complete=not missing_fields,
            missing_fields=missing_fields,
        ),
    )


def write_benchmark_report(
    report: BenchmarkReport, output_dir: Path
) -> tuple[Path, Path]:
    """Atomically write machine-readable and reviewable benchmark reports."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "benchmark.json"
    markdown_path = output_dir / "benchmark.md"
    payload = json.dumps(
        report.model_dump(mode="json"), indent=2, sort_keys=True
    ) + "\n"
    _write_text_atomic(json_path, payload)
    _write_text_atomic(markdown_path, _render_markdown(report))
    return json_path, markdown_path


def _verify_artifact(record: Any) -> ArtifactMeasurement:
    path = Path(record.path)
    if not path.is_file():
        raise BenchmarkReportError(f"artifact does not exist: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual_hash = digest.hexdigest()
    if actual_hash != record.sha256:
        raise BenchmarkReportError(
            f"artifact hash mismatch for {path}: "
            f"expected {record.sha256}, got {actual_hash}"
        )
    return ArtifactMeasurement(
        kind=record.kind,
        path=str(path),
        sha256=actual_hash,
        size_bytes=path.stat().st_size,
    )


def _write_text_atomic(path: Path, contents: str) -> None:
    partial = path.with_name(f"{path.name}.partial")
    try:
        partial.write_text(contents, encoding="utf-8")
        os.replace(partial, path)
    finally:
        if partial.exists():
            partial.unlink()


def _display(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _render_markdown(report: BenchmarkReport) -> str:
    rows = [
        ("Pipeline success", report.pipeline_success),
        ("Failure reason", report.failure_reason),
        ("Wall clock seconds", report.wall_clock_seconds),
        ("Registered frames", report.trajectory.registered_frames),
        ("Total frames", report.trajectory.total_frames),
        ("Registered-frame ratio", report.trajectory.registered_ratio),
        ("Trajectory continuous", report.trajectory.continuous),
        ("Maximum trajectory gap seconds", report.trajectory.max_gap_seconds),
        ("Point count", report.point_count),
        ("Triangle count", report.triangle_count),
        ("Splat count", report.splat_count),
        ("Visible holes", report.visible_holes),
        ("Viewer opened", report.viewer.opened),
        ("Free walk verified", report.viewer.free_walk_verified),
        ("Evidence lookup correct", report.evidence_lookup_correct),
        ("Provenance complete", report.provenance.complete),
    ]
    lines = [
        f"# Atlas benchmark: {report.candidate_id}",
        "",
        f"- Benchmark: `{report.benchmark_id}`",
        f"- Run: `{report.run_id}`",
        f"- Pipeline: `{report.pipeline_version}`",
        f"- Input SHA256: `{report.input_sha256}`",
        f"- Configuration SHA256: `{report.configuration_sha256}`",
        "",
        "## Measurements",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    lines.extend(f"| {name} | {_display(value)} |" for name, value in rows)
    lines.extend(
        [
            "",
            "## Detail inspection",
            "",
            "| Region | Required | Usable | Visible holes | Notes |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    if report.detail_regions:
        for detail in report.detail_regions:
            notes = _display(detail.notes).replace("|", "\\|").replace("\n", " ")
            lines.append(
                "| "
                + " | ".join(
                    [
                        detail.region_id,
                        _display(detail.required),
                        _display(detail.usable),
                        _display(detail.visible_holes),
                        notes,
                    ]
                )
                + " |"
            )
    else:
        lines.append("| NULL | NULL | NULL | NULL | NULL |")
    lines.extend(
        [
            "",
            "## Provenance",
            "",
            f"- Missing fields: {_display(', '.join(report.provenance.missing_fields) or None)}",
            f"- GPU: `{json.dumps(report.gpu, sort_keys=True) if report.gpu is not None else 'NULL'}`",
            f"- Tool versions: `{json.dumps(report.tool_versions, sort_keys=True)}`",
            "",
        ]
    )
    return "\n".join(lines)
