import json
import sys

import pytest

from atlas.frames.extract import FrameExtractionError, extract_frames


def test_extract_frames_writes_stable_names_timestamps_and_sidecar(
    tmp_path, monkeypatch
):
    args_log = tmp_path / "args.json"
    fake_ffmpeg = tmp_path / "fake_ffmpeg.py"
    fake_ffmpeg.write_text(
        """\
import json
import os
import sys
from pathlib import Path

Path(os.environ["ATLAS_FAKE_ARGS_LOG"]).write_text(
    json.dumps(sys.argv[1:]), encoding="utf-8"
)
pattern = sys.argv[-1]
for index in range(2):
    Path(pattern.replace("%06d", f"{index:06d}")).write_bytes(
        f"frame-{index}".encode("utf-8")
    )
""",
        encoding="utf-8",
    )
    video_path = tmp_path / "capture $(echo unsafe).mp4"
    video_path.write_bytes(b"fake-video")
    output_dir = tmp_path / "frames"
    monkeypatch.setenv("ATLAS_FAKE_ARGS_LOG", str(args_log))

    manifest = extract_frames(
        video_path,
        output_dir,
        sample_interval_seconds=0.5,
        ffmpeg_command=(sys.executable, str(fake_ffmpeg)),
    )

    assert [frame.physical_frame_id for frame in manifest.frames] == [
        "physical-000000",
        "physical-000001",
    ]
    assert [frame.filename for frame in manifest.frames] == [
        "physical_000000.png",
        "physical_000001.png",
    ]
    assert [frame.timestamp_seconds for frame in manifest.frames] == [0.0, 0.5]
    persisted = (output_dir / "frames.json").read_text(encoding="utf-8")
    assert persisted == manifest.model_dump_json(indent=2) + "\n"
    assert json.loads(args_log.read_text(encoding="utf-8")) == [
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
        "fps=1/0.5:start_time=0",
        "-start_number",
        "0",
        "-compression_level",
        "3",
        str(output_dir / "physical_%06d.png"),
    ]


def test_extract_frames_rejects_successful_ffmpeg_without_output_frames(tmp_path):
    fake_ffmpeg = tmp_path / "empty_ffmpeg.py"
    fake_ffmpeg.write_text("pass\n", encoding="utf-8")
    video_path = tmp_path / "capture.mp4"
    video_path.write_bytes(b"fake-video")

    with pytest.raises(FrameExtractionError, match="no frames"):
        extract_frames(
            video_path,
            tmp_path / "frames",
            sample_interval_seconds=0.5,
            ffmpeg_command=(sys.executable, str(fake_ffmpeg)),
        )


def test_extract_frames_reports_ffmpeg_failure(tmp_path):
    fake_ffmpeg = tmp_path / "failing_ffmpeg.py"
    fake_ffmpeg.write_text(
        'import sys\nsys.stderr.write("decode failed")\nraise SystemExit(9)\n',
        encoding="utf-8",
    )
    video_path = tmp_path / "capture.mp4"
    video_path.write_bytes(b"fake-video")

    with pytest.raises(FrameExtractionError, match="exit code 9: decode failed"):
        extract_frames(
            video_path,
            tmp_path / "frames",
            sample_interval_seconds=0.5,
            ffmpeg_command=(sys.executable, str(fake_ffmpeg)),
        )


def test_extract_frames_rejects_nonpositive_interval_before_running_ffmpeg(tmp_path):
    marker = tmp_path / "was-run"
    fake_ffmpeg = tmp_path / "marker_ffmpeg.py"
    fake_ffmpeg.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    video_path = tmp_path / "capture.mp4"
    video_path.write_bytes(b"fake-video")

    with pytest.raises(FrameExtractionError, match="sample interval"):
        extract_frames(
            video_path,
            tmp_path / "frames",
            sample_interval_seconds=0,
            ffmpeg_command=(sys.executable, str(fake_ffmpeg)),
        )

    assert not marker.exists()


def test_extract_frames_refuses_to_mix_with_existing_output(tmp_path):
    output_dir = tmp_path / "frames"
    output_dir.mkdir()
    (output_dir / "physical_000099.png").write_bytes(b"stale")
    marker = tmp_path / "was-run"
    fake_ffmpeg = tmp_path / "marker_ffmpeg.py"
    fake_ffmpeg.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    video_path = tmp_path / "capture.mp4"
    video_path.write_bytes(b"fake-video")

    with pytest.raises(FrameExtractionError, match="already contains Atlas frames"):
        extract_frames(
            video_path,
            output_dir,
            sample_interval_seconds=0.5,
            ffmpeg_command=(sys.executable, str(fake_ffmpeg)),
        )

    assert not marker.exists()


def test_extract_frames_rejects_noncontiguous_output_sequence(tmp_path):
    fake_ffmpeg = tmp_path / "gapped_ffmpeg.py"
    fake_ffmpeg.write_text(
        """\
import sys
from pathlib import Path

pattern = sys.argv[-1]
for index in (0, 2):
    Path(pattern.replace("%06d", f"{index:06d}")).write_bytes(b"frame")
""",
        encoding="utf-8",
    )
    video_path = tmp_path / "capture.mp4"
    video_path.write_bytes(b"fake-video")

    with pytest.raises(FrameExtractionError, match="non-contiguous"):
        extract_frames(
            video_path,
            tmp_path / "frames",
            sample_interval_seconds=0.5,
            ffmpeg_command=(sys.executable, str(fake_ffmpeg)),
        )


def test_extract_frames_reports_missing_ffmpeg_executable(tmp_path):
    video_path = tmp_path / "capture.mp4"
    video_path.write_bytes(b"fake-video")

    with pytest.raises(FrameExtractionError, match="ffmpeg executable not found"):
        extract_frames(
            video_path,
            tmp_path / "frames",
            sample_interval_seconds=0.5,
            ffmpeg_command=(str(tmp_path / "missing-ffmpeg"),),
        )


def test_extract_frames_uses_stable_decimal_timestamps(tmp_path):
    fake_ffmpeg = tmp_path / "four_frame_ffmpeg.py"
    fake_ffmpeg.write_text(
        """\
import sys
from pathlib import Path

pattern = sys.argv[-1]
for index in range(4):
    Path(pattern.replace("%06d", f"{index:06d}")).write_bytes(b"frame")
""",
        encoding="utf-8",
    )
    video_path = tmp_path / "capture.mp4"
    video_path.write_bytes(b"fake-video")

    manifest = extract_frames(
        video_path,
        tmp_path / "frames",
        sample_interval_seconds=0.1,
        ffmpeg_command=(sys.executable, str(fake_ffmpeg)),
    )

    assert [frame.timestamp_seconds for frame in manifest.frames] == [
        0.0,
        0.1,
        0.2,
        0.3,
    ]
