import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas.evidence.index import (
    EvidenceIndexError,
    ReconstructedViewPose,
    build_evidence_index,
    write_evidence_index,
)
from atlas.frames.extract import (
    ExtractedFrame,
    FrameExtractionManifest,
)


def _frames() -> FrameExtractionManifest:
    return FrameExtractionManifest(
        source_video="walk.mp4",
        sample_interval_seconds=0.5,
        ffmpeg_argv=["ffmpeg", "-i", "walk.mp4"],
        frames=[
            ExtractedFrame(
                physical_frame_id="physical-000000",
                filename="physical_000000.png",
                timestamp_seconds=0.0,
            ),
            ExtractedFrame(
                physical_frame_id="physical-000001",
                filename="physical_000001.png",
                timestamp_seconds=0.5,
            ),
            ExtractedFrame(
                physical_frame_id="physical-000002",
                filename="physical_000002.png",
                timestamp_seconds=1.0,
            ),
        ],
    )


def test_build_index_groups_virtual_views_into_physical_capture_positions():
    poses = [
        ReconstructedViewPose(
            view_id="physical-000001__view-001",
            physical_frame_id="physical-000001",
            position=(2.0, 1.0, 0.0),
        ),
        ReconstructedViewPose(
            view_id="physical-000000__view-001",
            physical_frame_id="physical-000000",
            position=(0.2, 0.0, 0.0),
        ),
        ReconstructedViewPose(
            view_id="physical-000001__view-000",
            physical_frame_id="physical-000001",
            position=(0.0, 1.0, 0.0),
        ),
        ReconstructedViewPose(
            view_id="physical-000000__view-000",
            physical_frame_id="physical-000000",
            position=(-0.2, 0.0, 0.0),
        ),
    ]

    index = build_evidence_index(
        _frames(), poses, coordinate_system="atlas-world-v1"
    )

    assert [capture.physical_frame_id for capture in index.captures] == [
        "physical-000000",
        "physical-000001",
    ]
    assert index.captures[0].position == (0.0, 0.0, 0.0)
    assert index.captures[1].position == (1.0, 1.0, 0.0)
    assert index.captures[1].timestamp_seconds == 0.5
    assert index.captures[1].source_frame == "physical_000001.png"
    assert index.captures[1].contributing_view_ids == [
        "physical-000001__view-000",
        "physical-000001__view-001",
    ]
    assert index.source_video == "walk.mp4"
    # Unregistered physical frame 2 is not invented as a reconstructed position.
    assert len(index.captures) == 2


def test_nearest_returns_original_capture_and_distance():
    index = build_evidence_index(
        _frames(),
        [
            ReconstructedViewPose(
                view_id="view-0",
                physical_frame_id="physical-000000",
                position=(0.0, 0.0, 0.0),
            ),
            ReconstructedViewPose(
                view_id="view-1",
                physical_frame_id="physical-000001",
                position=(3.0, 0.0, 0.0),
            ),
        ],
        coordinate_system="atlas-world-v1",
    )

    match = index.nearest((2.6, 0.0, 0.0))

    assert match.physical_frame_id == "physical-000001"
    assert match.source_frame == "physical_000001.png"
    assert match.timestamp_seconds == 0.5
    assert match.distance == pytest.approx(0.4)


def test_nearest_tie_breaks_by_timestamp_then_physical_frame_id():
    frames = _frames().model_copy(
        update={
            "frames": [
                ExtractedFrame(
                    physical_frame_id="physical-z",
                    filename="z.png",
                    timestamp_seconds=1.0,
                ),
                ExtractedFrame(
                    physical_frame_id="physical-b",
                    filename="b.png",
                    timestamp_seconds=0.5,
                ),
                ExtractedFrame(
                    physical_frame_id="physical-a",
                    filename="a.png",
                    timestamp_seconds=0.5,
                ),
            ]
        }
    )
    index = build_evidence_index(
        frames,
        [
            ReconstructedViewPose(
                view_id="z", physical_frame_id="physical-z", position=(1, 0, 0)
            ),
            ReconstructedViewPose(
                view_id="b", physical_frame_id="physical-b", position=(-1, 0, 0)
            ),
            ReconstructedViewPose(
                view_id="a", physical_frame_id="physical-a", position=(0, 1, 0)
            ),
        ],
        coordinate_system="atlas-world-v1",
    )

    assert index.nearest((0, 0, 0)).physical_frame_id == "physical-a"


def test_build_is_deterministic_when_pose_input_order_changes():
    poses = [
        ReconstructedViewPose(
            view_id="view-b",
            physical_frame_id="physical-000000",
            position=(2.0, 0.0, 0.0),
        ),
        ReconstructedViewPose(
            view_id="view-a",
            physical_frame_id="physical-000000",
            position=(0.0, 0.0, 0.0),
        ),
    ]

    forward = build_evidence_index(
        _frames(), poses, coordinate_system="atlas-world-v1"
    )
    reverse = build_evidence_index(
        _frames(), list(reversed(poses)), coordinate_system="atlas-world-v1"
    )

    assert forward.model_dump_json() == reverse.model_dump_json()


def test_write_index_is_atomic_and_keeps_null_values(tmp_path: Path):
    index = build_evidence_index(
        _frames(),
        [
            ReconstructedViewPose(
                view_id="view-0",
                physical_frame_id="physical-000000",
                position=(0, 0, 0),
            )
        ],
        coordinate_system="atlas-world-v1",
    )

    output = write_evidence_index(index, tmp_path / "viewer")

    assert output == tmp_path / "viewer" / "evidence-index.json"
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["coordinate_system"] == "atlas-world-v1"
    assert payload["captures"][0]["physical_frame_id"] == "physical-000000"
    assert not list((tmp_path / "viewer").glob("*.partial"))


def test_build_rejects_unknown_physical_frame_and_duplicate_view_id():
    with pytest.raises(EvidenceIndexError, match="unknown physical frame"):
        build_evidence_index(
            _frames(),
            [
                ReconstructedViewPose(
                    view_id="view-0",
                    physical_frame_id="physical-999999",
                    position=(0, 0, 0),
                )
            ],
            coordinate_system="atlas-world-v1",
        )

    with pytest.raises(EvidenceIndexError, match="duplicate reconstructed view ID"):
        build_evidence_index(
            _frames(),
            [
                ReconstructedViewPose(
                    view_id="same",
                    physical_frame_id="physical-000000",
                    position=(0, 0, 0),
                ),
                ReconstructedViewPose(
                    view_id="same",
                    physical_frame_id="physical-000001",
                    position=(1, 0, 0),
                ),
            ],
            coordinate_system="atlas-world-v1",
        )


def test_build_rejects_no_registered_poses_and_duplicate_physical_frames():
    with pytest.raises(EvidenceIndexError, match="no reconstructed camera poses"):
        build_evidence_index(
            _frames(), [], coordinate_system="atlas-world-v1"
        )

    frames = _frames()
    frames.frames.append(frames.frames[0].model_copy())
    with pytest.raises(EvidenceIndexError, match="duplicate physical frame ID"):
        build_evidence_index(
            frames,
            [
                ReconstructedViewPose(
                    view_id="view-0",
                    physical_frame_id="physical-000000",
                    position=(0, 0, 0),
                )
            ],
            coordinate_system="atlas-world-v1",
        )


def test_pose_and_query_positions_must_be_finite():
    with pytest.raises(ValidationError):
        ReconstructedViewPose(
            view_id="bad",
            physical_frame_id="physical-000000",
            position=(float("nan"), 0, 0),
        )

    index = build_evidence_index(
        _frames(),
        [
            ReconstructedViewPose(
                view_id="view-0",
                physical_frame_id="physical-000000",
                position=(0, 0, 0),
            )
        ],
        coordinate_system="atlas-world-v1",
    )
    with pytest.raises(EvidenceIndexError, match="query position must contain"):
        index.nearest((float("inf"), 0, 0))
