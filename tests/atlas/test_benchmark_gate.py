from copy import deepcopy

import pytest

from atlas.benchmark.gate import (
    DetailRegressionAllowance,
    MeasurableAdvantage,
    evaluate_promotion,
)
from atlas.benchmark.report import (
    ArtifactMeasurement,
    BenchmarkReport,
    DetailAssessment,
    ProvenanceStatus,
    TrajectoryAssessment,
    ViewerAssessment,
)


def _report(
    *,
    candidate_id: str,
    run_id: str,
    registered_ratio: float,
) -> BenchmarkReport:
    return BenchmarkReport(
        benchmark_id="atlas-indoor-360-v1",
        candidate_id=candidate_id,
        pipeline_version=f"git:{candidate_id}",
        configuration_sha256=("a" if candidate_id == "baseline" else "b") * 64,
        run_id=run_id,
        input_sha256="c" * 64,
        pipeline_success=True,
        failure_reason=None,
        wall_clock_seconds=120.0,
        gpu={"model": "Fake RTX"},
        tool_versions={"engine": "1.0"},
        commands=[["engine", "--run", run_id]],
        artifacts=[
            ArtifactMeasurement(
                kind="viewer-output",
                path=f"{run_id}.ply",
                sha256=("d" if run_id.endswith("1") else "e") * 64,
                size_bytes=1000,
            )
        ],
        trajectory=TrajectoryAssessment(
            total_frames=100,
            registered_frames=int(registered_ratio * 100),
            registered_ratio=registered_ratio,
            continuous=True,
            max_gap_seconds=0.5,
        ),
        point_count=None,
        triangle_count=None,
        splat_count=1_000_000,
        visible_holes=False,
        detail_regions=[
            DetailAssessment(
                region_id="pipe-joint",
                required=True,
                usable=True,
                visible_holes=False,
                notes="Reviewed at the frozen viewpoint.",
                evidence_artifacts=["pipe-joint.png"],
            )
        ],
        viewer=ViewerAssessment(opened=True, free_walk_verified=True),
        evidence_lookup_correct=True,
        provenance=ProvenanceStatus(complete=True, missing_fields=[]),
    )


def _reports() -> tuple[BenchmarkReport, list[BenchmarkReport]]:
    baseline = _report(candidate_id="baseline", run_id="baseline-1", registered_ratio=0.80)
    candidates = [
        _report(candidate_id="candidate", run_id="candidate-1", registered_ratio=0.90),
        _report(candidate_id="candidate", run_id="candidate-2", registered_ratio=0.88),
    ]
    return baseline, candidates


def _registration_advantage() -> MeasurableAdvantage:
    return MeasurableAdvantage(
        id="more-registered-frames",
        metric="registered_ratio",
        direction="higher",
        minimum_delta=0.05,
        description="Registers at least five percentage points more keyframes.",
    )


def test_promotes_two_reproducible_runs_with_a_measured_advantage():
    baseline, candidates = _reports()

    decision = evaluate_promotion(
        baseline=baseline,
        candidates=candidates,
        advantages=[_registration_advantage()],
    )

    assert decision.promote is True
    assert decision.reasons == []
    assert decision.validated_advantages == ["more-registered-frames"]


def test_rejects_candidate_without_two_distinct_runs():
    baseline, candidates = _reports()

    decision = evaluate_promotion(
        baseline=baseline,
        candidates=[candidates[0]],
        advantages=[_registration_advantage()],
    )

    assert decision.promote is False
    assert "candidate requires at least two distinct benchmark runs" in decision.reasons


@pytest.mark.parametrize("field", ["benchmark_id", "input_sha256"])
def test_rejects_a_candidate_run_on_a_different_frozen_input(field: str):
    baseline, candidates = _reports()
    candidates[1] = candidates[1].model_copy(
        update={field: "different" if field == "benchmark_id" else "f" * 64}
    )

    decision = evaluate_promotion(
        baseline=baseline,
        candidates=candidates,
        advantages=[_registration_advantage()],
    )

    assert decision.promote is False
    assert f"candidate runs disagree on {field}" in decision.reasons


def test_unknown_required_measurement_blocks_promotion():
    baseline, candidates = _reports()
    candidates[1] = candidates[1].model_copy(
        update={"viewer": ViewerAssessment(opened=None, free_walk_verified=True)}
    )

    decision = evaluate_promotion(
        baseline=baseline,
        candidates=candidates,
        advantages=[_registration_advantage()],
    )

    assert decision.promote is False
    assert "candidate-2: viewer opened is NULL" in decision.reasons


def test_required_detail_regression_needs_a_compensating_advantage():
    baseline, candidates = _reports()
    regressed = DetailAssessment(
        region_id="pipe-joint",
        required=True,
        usable=False,
        visible_holes=True,
        notes="Joint is no longer inspectable.",
        evidence_artifacts=["pipe-joint.png"],
    )
    candidates = [
        report.model_copy(update={"detail_regions": [deepcopy(regressed)]})
        for report in candidates
    ]

    blocked = evaluate_promotion(
        baseline=baseline,
        candidates=candidates,
        advantages=[_registration_advantage()],
    )
    allowed = evaluate_promotion(
        baseline=baseline,
        candidates=candidates,
        advantages=[_registration_advantage()],
        detail_allowances=[
            DetailRegressionAllowance(
                region_id="pipe-joint",
                advantage_id="more-registered-frames",
                rationale="Wider registered coverage is required for this candidate trial.",
            )
        ],
    )

    assert blocked.promote is False
    assert "required detail region regressed without allowance: pipe-joint" in blocked.reasons
    assert allowed.promote is True


def test_unmeasured_advantage_cannot_compensate_for_a_detail_regression():
    baseline, candidates = _reports()
    regressed = DetailAssessment(
        region_id="pipe-joint",
        required=True,
        usable=False,
        visible_holes=True,
        evidence_artifacts=["pipe-joint.png"],
    )
    candidates = [
        report.model_copy(update={"detail_regions": [regressed]})
        for report in candidates
    ]
    impossible_claim = MeasurableAdvantage(
        id="faster",
        metric="wall_clock_seconds",
        direction="lower",
        minimum_delta=10.0,
        description="At least ten seconds faster.",
    )

    decision = evaluate_promotion(
        baseline=baseline,
        candidates=candidates,
        advantages=[impossible_claim],
        detail_allowances=[
            DetailRegressionAllowance(
                region_id="pipe-joint",
                advantage_id="faster",
                rationale="Would compensate if the speed claim were measured.",
            )
        ],
    )

    assert decision.promote is False
    assert "advantage did not meet its minimum delta: faster" in decision.reasons
    assert "detail allowance lacks a validated advantage: pipe-joint" in decision.reasons


def test_candidate_must_have_complete_provenance_and_a_measurable_advantage():
    baseline, candidates = _reports()
    candidates[0] = candidates[0].model_copy(
        update={
            "provenance": ProvenanceStatus(
                complete=False, missing_fields=["tool_versions"]
            )
        }
    )

    decision = evaluate_promotion(
        baseline=baseline,
        candidates=candidates,
        advantages=[],
    )

    assert decision.promote is False
    assert "candidate-1: provenance is incomplete" in decision.reasons
    assert "candidate has no validated measurable advantage" in decision.reasons
