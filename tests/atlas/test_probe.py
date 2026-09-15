import json
import sys

import pytest

from atlas.ingest.probe import VideoProbeError, parse_ffprobe_output, probe_video


@pytest.mark.parametrize(("width", "height"), [(7680, 3840), (3840, 1920)])
def test_parse_ffprobe_output_accepts_two_to_one_equirectangular_video(
    width: int, height: int
):
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": width,
                "height": height,
                "avg_frame_rate": "30000/1001",
                "nb_frames": "300",
            }
        ],
        "format": {"duration": "10.01"},
    }

    probe = parse_ffprobe_output(payload)

    assert probe.width == width
    assert probe.height == height
    assert probe.fps == pytest.approx(29.9700299700)
    assert probe.duration_seconds == 10.01
    assert probe.codec_name == "hevc"
    assert probe.frame_count == 300


def test_parse_ffprobe_output_rejects_sixteen_to_nine_video():
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30/1",
            }
        ],
        "format": {"duration": "5.0"},
    }

    with pytest.raises(VideoProbeError, match="2:1"):
        parse_ffprobe_output(payload)


def test_parse_ffprobe_output_rejects_payload_without_video_stream():
    payload = {
        "streams": [{"codec_type": "audio", "codec_name": "aac"}],
        "format": {"duration": "5.0"},
    }

    with pytest.raises(VideoProbeError, match="video stream"):
        parse_ffprobe_output(payload)


def test_parse_ffprobe_output_accepts_ratio_within_one_percent():
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "width": 4038,
                "height": 2000,
                "avg_frame_rate": "30/1",
            }
        ],
        "format": {"duration": "5.0"},
    }

    probe = parse_ffprobe_output(payload)

    assert probe.width == 4038
    assert probe.height == 2000


def test_parse_ffprobe_output_rejects_ratio_beyond_one_percent():
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "width": 4042,
                "height": 2000,
                "avg_frame_rate": "30/1",
            }
        ],
        "format": {"duration": "5.0"},
    }

    with pytest.raises(VideoProbeError, match="2:1"):
        parse_ffprobe_output(payload)


def test_parse_ffprobe_output_reports_malformed_video_metadata():
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "height": 1920,
                "avg_frame_rate": "0/0",
            }
        ],
        "format": {"duration": "5.0"},
    }

    with pytest.raises(VideoProbeError, match="invalid ffprobe metadata"):
        parse_ffprobe_output(payload)


def test_probe_video_executes_ffprobe_with_argv_and_parses_json(
    tmp_path, monkeypatch
):
    args_log = tmp_path / "args.json"
    fake_ffprobe = tmp_path / "fake_ffprobe.py"
    fake_ffprobe.write_text(
        """\
import json
import os
import sys
from pathlib import Path

Path(os.environ["ATLAS_FAKE_ARGS_LOG"]).write_text(
    json.dumps(sys.argv[1:]), encoding="utf-8"
)
print(json.dumps({
    "streams": [{
        "codec_type": "video",
        "codec_name": "hevc",
        "width": 3840,
        "height": 1920,
        "avg_frame_rate": "30000/1001",
        "nb_frames": "300"
    }],
    "format": {"duration": "10.01"}
}))
""",
        encoding="utf-8",
    )
    video_path = tmp_path / "capture $(echo unsafe).mp4"
    video_path.write_bytes(b"fake-video")
    monkeypatch.setenv("ATLAS_FAKE_ARGS_LOG", str(args_log))

    probe = probe_video(
        video_path,
        ffprobe_command=(sys.executable, str(fake_ffprobe)),
    )

    assert probe.width == 3840
    assert json.loads(args_log.read_text(encoding="utf-8")) == [
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


def test_probe_video_reports_ffprobe_failure(tmp_path):
    fake_ffprobe = tmp_path / "failing_ffprobe.py"
    fake_ffprobe.write_text(
        """\
import sys

sys.stderr.write("broken capture")
raise SystemExit(7)
""",
        encoding="utf-8",
    )
    video_path = tmp_path / "capture.mp4"
    video_path.write_bytes(b"fake-video")

    with pytest.raises(VideoProbeError, match="exit code 7: broken capture"):
        probe_video(
            video_path,
            ffprobe_command=(sys.executable, str(fake_ffprobe)),
        )


def test_probe_video_reports_missing_ffprobe_executable(tmp_path):
    video_path = tmp_path / "capture.mp4"
    video_path.write_bytes(b"fake-video")

    with pytest.raises(VideoProbeError, match="ffprobe executable not found"):
        probe_video(
            video_path,
            ffprobe_command=(str(tmp_path / "missing-ffprobe"),),
        )


def test_probe_video_reports_invalid_ffprobe_json(tmp_path):
    fake_ffprobe = tmp_path / "invalid_json_ffprobe.py"
    fake_ffprobe.write_text('print("not-json")\n', encoding="utf-8")
    video_path = tmp_path / "capture.mp4"
    video_path.write_bytes(b"fake-video")

    with pytest.raises(VideoProbeError, match="invalid JSON"):
        probe_video(
            video_path,
            ffprobe_command=(sys.executable, str(fake_ffprobe)),
        )
