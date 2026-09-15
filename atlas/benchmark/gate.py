"""Deterministic promotion gate for reconstruction candidates.

The gate compares only frozen benchmark reports.  It does not infer missing
measurements and it verifies every claimed numerical advantage from report data.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import PositiveFloat, StringConstraints

from atlas.benchmark.report import BenchmarkReport, DetailAssessment
from atlas.manifest.models import AtlasModel


MetricName = Literal[
    "wall_clock_seconds",
    "registered_ratio",
    "trajectory_max_gap_seconds",
    "point_count",
    "triangle_count",
    "splat_count",
    "artifact_size_bytes",
]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MeasurableAdvantage(AtlasModel):
    """A candidate improvement that the gate recalculates from reports."""

    id: NonEmptyText
    metric: MetricName
    direction: Literal["higher", "lower"]
    minimum_delta: PositiveFloat
    description: NonEmptyText


class DetailRegressionAllowance(AtlasModel):
    """A reviewed link from one detail regression to a measured advantage."""

    region_id: NonEmptyText
    advantage_id: NonEmptyText
    rationale: NonEmptyText


class PromotionDecision(AtlasModel):
    """Machine-readable gate result."""

    promote: bool
    reasons: list[str]
    validated_advantages: list[str]


def evaluate_promotion(
    *,
    baseline: BenchmarkReport,
    candidates: list[BenchmarkReport],
    advantages: list[MeasurableAdvantage],
    detail_allowances: list[DetailRegressionAllowance] | None = None,
) -> PromotionDecision:
    """Evaluate a candidate without changing the frozen baseline."""
    reasons: list[str] = []
    allowances = detail_allowances or []

    if len({report.run_id for report in candidates}) < 2:
        reasons.append("candidate requires at least two distinct benchmark runs")
    if not candidates:
        reasons.append("candidate reports are missing")
    else:
        _check_reproducible_contract(baseline, candidates, reasons)

    _check_report_measurements(baseline, "baseline", reasons)
    for report in candidates:
        _check_report_measurements(report, report.run_id, reasons)

    validated = _validate_advantages(baseline, candidates, advantages, reasons)
    if not validated:
        reasons.append("candidate has no validated measurable advantage")

    _check_required_details(
        baseline,
        candidates,
        allowances,
        set(validated),
        reasons,
    )

    unique_reasons = list(dict.fromkeys(reasons))
    return PromotionDecision(
        promote=not unique_reasons,
        reasons=unique_reasons,
        validated_advantages=validated,
    )


def _check_reproducible_contract(
    baseline: BenchmarkReport,
    candidates: list[BenchmarkReport],
    reasons: list[str],
) -> None:
    fields = (
        "schema_version",
        "benchmark_id",
        "input_sha256",
        "candidate_id",
        "pipeline_version",
        "configuration_sha256",
        "tool_versions",
    )
    for field in fields:
        values = [_stable_value(getattr(report, field)) for report in candidates]
        if len(set(values)) > 1:
            reasons.append(f"candidate runs disagree on {field}")

    first = candidates[0]
    for field in ("schema_version", "benchmark_id", "input_sha256"):
        if getattr(first, field) != getattr(baseline, field):
            reasons.append(f"candidate {field} differs from baseline")


def _stable_value(value: object) -> str:
    if isinstance(value, dict):
        return repr(sorted(value.items()))
    return repr(value)


def _check_report_measurements(
    report: BenchmarkReport, label: str, reasons: list[str]
) -> None:
    if not report.pipeline_success:
        reasons.append(f"{label}: pipeline failed")
    if report.wall_clock_seconds is None:
        reasons.append(f"{label}: wall clock seconds is NULL")
    if report.trajectory.registered_ratio is None:
        reasons.append(f"{label}: registered-frame ratio is NULL")
    if report.trajectory.continuous is None:
        reasons.append(f"{label}: trajectory continuity is NULL")
    elif not report.trajectory.continuous:
        reasons.append(f"{label}: trajectory is not continuous")
    if report.trajectory.max_gap_seconds is None:
        reasons.append(f"{label}: maximum trajectory gap is NULL")
    if all(
        value is None
        for value in (report.point_count, report.triangle_count, report.splat_count)
    ):
        reasons.append(f"{label}: output element count is NULL")
    if report.visible_holes is None:
        reasons.append(f"{label}: visible-holes assessment is NULL")
    if report.viewer.opened is None:
        reasons.append(f"{label}: viewer opened is NULL")
    elif not report.viewer.opened:
        reasons.append(f"{label}: output did not open in viewer")
    if report.viewer.free_walk_verified is None:
        reasons.append(f"{label}: free-walk verification is NULL")
    elif not report.viewer.free_walk_verified:
        reasons.append(f"{label}: free walk is not verified")
    if report.evidence_lookup_correct is None:
        reasons.append(f"{label}: evidence lookup correctness is NULL")
    elif not report.evidence_lookup_correct:
        reasons.append(f"{label}: evidence lookup is incorrect")
    if not report.provenance.complete:
        reasons.append(f"{label}: provenance is incomplete")
    if not report.artifacts:
        reasons.append(f"{label}: verified artifacts are missing")

    seen_regions: set[str] = set()
    for detail in report.detail_regions:
        if detail.region_id in seen_regions:
            reasons.append(f"{label}: duplicate detail region {detail.region_id}")
        seen_regions.add(detail.region_id)
        if detail.usable is None:
            reasons.append(f"{label}: detail usability is NULL for {detail.region_id}")
        if detail.visible_holes is None:
            reasons.append(
                f"{label}: detail visible-holes assessment is NULL for {detail.region_id}"
            )
        if not detail.evidence_artifacts:
            reasons.append(f"{label}: detail evidence is missing for {detail.region_id}")


def _validate_advantages(
    baseline: BenchmarkReport,
    candidates: list[BenchmarkReport],
    advantages: list[MeasurableAdvantage],
    reasons: list[str],
) -> list[str]:
    validated: list[str] = []
    seen: set[str] = set()
    for claim in advantages:
        if claim.id in seen:
            reasons.append(f"duplicate advantage id: {claim.id}")
            continue
        seen.add(claim.id)
        baseline_value = _metric_value(baseline, claim.metric)
        candidate_values = [
            _metric_value(report, claim.metric) for report in candidates
        ]
        if baseline_value is None or not candidate_values or any(
            value is None for value in candidate_values
        ):
            reasons.append(f"advantage metric is NULL: {claim.id}")
            continue

        measured_values = [float(value) for value in candidate_values if value is not None]
        if claim.direction == "higher":
            delta = min(measured_values) - float(baseline_value)
        else:
            delta = float(baseline_value) - max(measured_values)
        if delta + 1e-12 < claim.minimum_delta:
            reasons.append(f"advantage did not meet its minimum delta: {claim.id}")
            continue
        validated.append(claim.id)
    return validated


def _metric_value(report: BenchmarkReport, metric: MetricName) -> float | int | None:
    if metric == "registered_ratio":
        return report.trajectory.registered_ratio
    if metric == "trajectory_max_gap_seconds":
        return report.trajectory.max_gap_seconds
    if metric == "artifact_size_bytes":
        return sum(artifact.size_bytes for artifact in report.artifacts)
    return getattr(report, metric)


def _check_required_details(
    baseline: BenchmarkReport,
    candidates: list[BenchmarkReport],
    allowances: list[DetailRegressionAllowance],
    validated_advantages: set[str],
    reasons: list[str],
) -> None:
    required = {
        detail.region_id: detail
        for detail in baseline.detail_regions
        if detail.required
    }
    allowance_by_region: dict[str, DetailRegressionAllowance] = {}
    for allowance in allowances:
        if allowance.region_id in allowance_by_region:
            reasons.append(f"duplicate detail allowance: {allowance.region_id}")
            continue
        allowance_by_region[allowance.region_id] = allowance

    for region_id, baseline_detail in required.items():
        regressed = any(
            _detail_regressed(
                baseline_detail,
                _detail_by_id(report.detail_regions, region_id),
            )
            for report in candidates
        )
        if not regressed:
            continue
        allowance = allowance_by_region.get(region_id)
        if allowance is None:
            reasons.append(
                f"required detail region regressed without allowance: {region_id}"
            )
        elif allowance.advantage_id not in validated_advantages:
            reasons.append(
                f"detail allowance lacks a validated advantage: {region_id}"
            )


def _detail_by_id(
    details: list[DetailAssessment], region_id: str
) -> DetailAssessment | None:
    return next((detail for detail in details if detail.region_id == region_id), None)


def _detail_regressed(
    baseline: DetailAssessment, candidate: DetailAssessment | None
) -> bool:
    if candidate is None:
        return True
    if baseline.usable is True and candidate.usable is not True:
        return True
    return baseline.visible_holes is False and candidate.visible_holes is not False
