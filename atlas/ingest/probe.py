"""Inspect moving 360 video metadata with ffprobe."""

import json
import subprocess
from collections.abc import Mapping, Sequence
from fractions import Fraction
from math import isclose
from pathlib import Path
from typing import Any

from atlas.manifest.models import VideoProbe


class VideoProbeError(ValueError):
    """Raised when ffprobe output cannot satisfy the Atlas input contract."""


def probe_video(
    video_path: Path,
    *,
    ffprobe_command: Sequence[str] = ("ffprobe",),
) -> VideoProbe:
    """Run ffprobe for one video and return validated metadata."""
    argv = [
        *ffprobe_command,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_type,codec_name,width,height,avg_frame_rate,nb_frames:format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise VideoProbeError(
            f"ffprobe executable not found: {ffprobe_command[0]}"
        ) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or "no stderr"
        raise VideoProbeError(
            f"ffprobe failed with exit code {result.returncode}: {detail}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise VideoProbeError("ffprobe returned invalid JSON") from error
    return parse_ffprobe_output(payload)


def parse_ffprobe_output(payload: Mapping[str, Any]) -> VideoProbe:
    """Parse ffprobe JSON into the Atlas video contract."""
    video = next(
        (
            stream
            for stream in payload.get("streams", [])
            if stream.get("codec_type") == "video"
        ),
        None,
    )
    if video is None:
        raise VideoProbeError("ffprobe output contains no video stream")

    try:
        width = video["width"]
        height = video["height"]
        if not isclose(width / height, 2.0, rel_tol=0.01):
            raise VideoProbeError(
                f"expected 2:1 equirectangular video, received {width}x{height}"
            )

        frame_count = video.get("nb_frames")
        return VideoProbe(
            width=width,
            height=height,
            fps=float(Fraction(video["avg_frame_rate"])),
            duration_seconds=float(payload["format"]["duration"]),
            codec_name=video.get("codec_name"),
            frame_count=None if frame_count in (None, "N/A") else int(frame_count),
        )
    except VideoProbeError:
        raise
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as error:
        raise VideoProbeError(f"invalid ffprobe metadata: {error}") from error
