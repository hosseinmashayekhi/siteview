"""Map reconstructed positions back to original physical 360 captures."""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, FiniteFloat, NonNegativeFloat, StringConstraints

from atlas.frames.extract import ExtractedFrame, FrameExtractionManifest
from atlas.manifest.models import AtlasModel


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Position3D = tuple[FiniteFloat, FiniteFloat, FiniteFloat]


class EvidenceIndexError(ValueError):
    """Raised when trustworthy evidence lookup cannot be constructed or queried."""


class ReconstructedViewPose(AtlasModel):
    """One registered reconstruction view with its physical-frame provenance."""

    view_id: NonEmptyText
    physical_frame_id: NonEmptyText
    position: Position3D


class EvidenceCapture(AtlasModel):
    """One reconstructed physical camera location linked to original imagery."""

    physical_frame_id: NonEmptyText
    timestamp_seconds: NonNegativeFloat
    source_frame: NonEmptyText
    position: Position3D
    contributing_view_ids: list[NonEmptyText] = Field(min_length=1)


class EvidenceMatch(AtlasModel):
    """Nearest source capture returned for a 3D viewer position."""

    physical_frame_id: NonEmptyText
    timestamp_seconds: NonNegativeFloat
    source_frame: NonEmptyText
    position: Position3D
    distance: NonNegativeFloat


class EvidenceIndex(AtlasModel):
    """Serializable nearest-capture index in one explicit coordinate system."""

    schema_version: Literal[1] = 1
    source_video: NonEmptyText
    coordinate_system: NonEmptyText
    captures: list[EvidenceCapture] = Field(min_length=1)

    def nearest(self, position: Sequence[float]) -> EvidenceMatch:
        """Return the deterministic nearest physical source capture."""
        query = _finite_position(position)
        capture = min(
            self.captures,
            key=lambda item: (
                _squared_distance(query, item.position),
                item.timestamp_seconds,
                item.physical_frame_id,
            ),
        )
        return EvidenceMatch(
            physical_frame_id=capture.physical_frame_id,
            timestamp_seconds=capture.timestamp_seconds,
            source_frame=capture.source_frame,
            position=capture.position,
            distance=math.sqrt(_squared_distance(query, capture.position)),
        )


def build_evidence_index(
    extraction: FrameExtractionManifest,
    poses: Sequence[ReconstructedViewPose],
    *,
    coordinate_system: str,
) -> EvidenceIndex:
    """Group registered virtual views into physical 360 capture positions."""
    frames_by_id: dict[str, ExtractedFrame] = {}
    for frame in extraction.frames:
        if frame.physical_frame_id in frames_by_id:
            raise EvidenceIndexError(
                f"duplicate physical frame ID: {frame.physical_frame_id}"
            )
        frames_by_id[frame.physical_frame_id] = frame

    if not poses:
        raise EvidenceIndexError("no reconstructed camera poses")

    seen_view_ids: set[str] = set()
    poses_by_frame: dict[str, list[ReconstructedViewPose]] = defaultdict(list)
    for pose in poses:
        if pose.view_id in seen_view_ids:
            raise EvidenceIndexError(f"duplicate reconstructed view ID: {pose.view_id}")
        seen_view_ids.add(pose.view_id)
        if pose.physical_frame_id not in frames_by_id:
            raise EvidenceIndexError(
                f"unknown physical frame: {pose.physical_frame_id}"
            )
        poses_by_frame[pose.physical_frame_id].append(pose)

    captures: list[EvidenceCapture] = []
    for physical_frame_id, grouped_poses in poses_by_frame.items():
        frame = frames_by_id[physical_frame_id]
        ordered_poses = sorted(grouped_poses, key=lambda item: item.view_id)
        captures.append(
            EvidenceCapture(
                physical_frame_id=physical_frame_id,
                timestamp_seconds=frame.timestamp_seconds,
                source_frame=frame.filename,
                position=_centroid([pose.position for pose in ordered_poses]),
                contributing_view_ids=[pose.view_id for pose in ordered_poses],
            )
        )
    captures.sort(key=lambda item: (item.timestamp_seconds, item.physical_frame_id))

    return EvidenceIndex(
        source_video=extraction.source_video,
        coordinate_system=coordinate_system,
        captures=captures,
    )


def write_evidence_index(index: EvidenceIndex, output_dir: Path) -> Path:
    """Atomically export the viewer's ``evidence-index.json`` file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "evidence-index.json"
    partial = destination.with_name(f"{destination.name}.partial")
    contents = json.dumps(
        index.model_dump(mode="json"), indent=2, sort_keys=True
    ) + "\n"
    try:
        partial.write_text(contents, encoding="utf-8")
        os.replace(partial, destination)
    finally:
        if partial.exists():
            partial.unlink()
    return destination


def _centroid(positions: Sequence[Position3D]) -> Position3D:
    count = len(positions)
    return (
        math.fsum(position[0] for position in positions) / count,
        math.fsum(position[1] for position in positions) / count,
        math.fsum(position[2] for position in positions) / count,
    )


def _finite_position(position: Sequence[float]) -> Position3D:
    if len(position) != 3:
        raise EvidenceIndexError("query position must contain three finite coordinates")
    try:
        coordinates = tuple(float(value) for value in position)
    except (TypeError, ValueError) as error:
        raise EvidenceIndexError(
            "query position must contain three finite coordinates"
        ) from error
    if not all(math.isfinite(value) for value in coordinates):
        raise EvidenceIndexError("query position must contain three finite coordinates")
    return coordinates[0], coordinates[1], coordinates[2]


def _squared_distance(left: Position3D, right: Position3D) -> float:
    return math.fsum((a - b) ** 2 for a, b in zip(left, right, strict=True))
