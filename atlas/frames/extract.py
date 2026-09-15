"""Deterministically extract physical frames from a moving 360 video."""

import subprocess
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import NonNegativeFloat, PositiveFloat

from atlas.manifest.models import AtlasModel


class FrameExtractionError(RuntimeError):
    """Raised when deterministic frame extraction cannot be completed."""


class ExtractedFrame(AtlasModel):
    physical_frame_id: str
    filename: str
    timestamp_seconds: NonNegativeFloat


class FrameExtractionManifest(AtlasModel):
    schema_version: Literal[1] = 1
    source_video: str
    sample_interval_seconds: PositiveFloat
    ffmpeg_argv: list[str]
    frames: list[ExtractedFrame]


def extract_frames(
    video_path: Path,
    output_dir: Path,
    *,
    sample_interval_seconds: float,
    ffmpeg_command: Sequence[str] = ("ffmpeg",),
) -> FrameExtractionManifest:
    """Extract stable physical frames and persist nominal sampling timestamps."""
    if sample_interval_seconds <= 0:
        raise FrameExtractionError("sample interval must be greater than zero")

    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.glob("physical_*.png")) or (output_dir / "frames.json").exists():
        raise FrameExtractionError(
            f"output directory already contains Atlas frames: {output_dir}"
        )
    pattern = output_dir / "physical_%06d.png"
    interval = format(sample_interval_seconds, ".12g")
    interval_decimal = Decimal(interval)
    argv = [
        *ffmpeg_command,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(video_path),
        "-map_metadata",
        "-1",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        f"fps=1/{interval}:start_time=0",
        "-start_number",
        "0",
        "-compression_level",
        "3",
        str(pattern),
    ]
    try:
        result = subprocess.run(argv, check=False, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise FrameExtractionError(
            f"ffmpeg executable not found: {ffmpeg_command[0]}"
        ) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or "no stderr"
        raise FrameExtractionError(
            f"ffmpeg failed with exit code {result.returncode}: {detail}"
        )

    files = sorted(output_dir.glob("physical_[0-9][0-9][0-9][0-9][0-9][0-9].png"))
    if not files:
        raise FrameExtractionError("ffmpeg completed but produced no frames")
    expected_names = [f"physical_{index:06d}.png" for index in range(len(files))]
    if [frame_path.name for frame_path in files] != expected_names:
        raise FrameExtractionError("ffmpeg produced a non-contiguous frame sequence")
    frames = [
        ExtractedFrame(
            physical_frame_id=f"physical-{index:06d}",
            filename=frame_path.name,
            timestamp_seconds=float(index * interval_decimal),
        )
        for index, frame_path in enumerate(files)
    ]
    manifest = FrameExtractionManifest(
        source_video=video_path.name,
        sample_interval_seconds=float(interval_decimal),
        ffmpeg_argv=argv,
        frames=frames,
    )
    sidecar = output_dir / "frames.json"
    partial = sidecar.with_suffix(".json.partial")
    partial.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    partial.replace(sidecar)
    return manifest
