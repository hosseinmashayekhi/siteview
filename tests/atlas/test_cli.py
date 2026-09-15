import json

from typer.testing import CliRunner

from atlas.cli import app
from atlas.environment.probe import probe_environment
from atlas.ingest.probe import VideoProbeError
from atlas.manifest.models import VideoProbe


runner = CliRunner()


def test_inspect_manifest_prints_normalized_dataset_json(tmp_path):
    manifest_path = tmp_path / "dataset.json"
    manifest_path.write_text(
        json.dumps(
            {
                "id": "smoke-room",
                "source": "https://example.invalid/room.mp4",
                "license": "CC-BY-4.0",
                "sha256": "a" * 64,
                "projection": "equirectangular",
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["inspect-manifest", str(manifest_path)])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "id": "smoke-room",
        "source": "https://example.invalid/room.mp4",
        "license": "CC-BY-4.0",
        "sha256": "a" * 64,
        "projection": "equirectangular",
    }


def test_inspect_manifest_prints_normalized_run_json(tmp_path):
    manifest_path = tmp_path / "run.json"
    manifest_path.write_text(
        json.dumps(
            {
                "run_id": "run-001",
                "input_sha256": "b" * 64,
                "commands": [["ffprobe", "input.mp4"]],
                "tool_versions": {"ffmpeg": "8.0"},
                "artifacts": [],
                "timing_seconds": {"total": 12.5},
                "gpu": None,
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["inspect-manifest", str(manifest_path)])

    assert result.exit_code == 0
    assert json.loads(result.stdout)["run_id"] == "run-001"
    assert json.loads(result.stdout)["commands"] == [["ffprobe", "input.mp4"]]


def test_inspect_manifest_reports_invalid_json_without_traceback(tmp_path):
    manifest_path = tmp_path / "invalid.json"
    manifest_path.write_text("not-json", encoding="utf-8")

    result = runner.invoke(app, ["inspect-manifest", str(manifest_path)])

    assert result.exit_code == 2
    assert "Invalid Atlas manifest" in result.output


def test_probe_prints_validated_video_metadata_as_json(tmp_path, monkeypatch):
    video_path = tmp_path / "capture.mp4"
    video_path.write_bytes(b"fake-video")
    monkeypatch.setattr(
        "atlas.cli.probe_video",
        lambda _path: VideoProbe(
            width=7680,
            height=3840,
            fps=30000 / 1001,
            duration_seconds=10.01,
            codec_name="hevc",
            frame_count=300,
        ),
    )

    result = runner.invoke(app, ["probe", str(video_path)])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "width": 7680,
        "height": 3840,
        "fps": 30000 / 1001,
        "duration_seconds": 10.01,
        "codec_name": "hevc",
        "frame_count": 300,
    }


def test_probe_reports_validation_failure_without_traceback(tmp_path, monkeypatch):
    video_path = tmp_path / "capture.mp4"
    video_path.write_bytes(b"fake-video")

    def reject_video(_path):
        raise VideoProbeError("expected 2:1 equirectangular video")

    monkeypatch.setattr("atlas.cli.probe_video", reject_video)

    result = runner.invoke(app, ["probe", str(video_path)])

    assert result.exit_code == 2
    assert "Video inspection failed: expected 2:1" in result.output


def test_probe_environment_prints_and_writes_the_same_json(tmp_path, monkeypatch):
    missing = str(tmp_path / "not-installed")
    report = probe_environment(
        commands={
            name: (missing,)
            for name in (
                "git",
                "ffmpeg",
                "ffprobe",
                "docker",
                "wsl",
                "nvidia_smi",
                "nvidia_query",
            )
        },
        environ={"ATLAS_ROOT": r"C:\3dcamera"},
        platform_description="Windows-11-test",
    )
    monkeypatch.setattr("atlas.cli.probe_environment", lambda: report)
    output_path = tmp_path / "environment.json"

    result = runner.invoke(
        app, ["probe-environment", "--output", str(output_path)]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == json.loads(
        output_path.read_text(encoding="utf-8")
    )
    assert json.loads(result.stdout)["docker_gpu_verified"] is None


def test_init_workspace_creates_data_beside_repo(tmp_path):
    atlas_root = tmp_path / "3dcamera"
    repo_root = atlas_root / "siteview"
    repo_root.mkdir(parents=True)

    result = runner.invoke(
        app,
        [
            "init-workspace",
            "--root",
            str(atlas_root),
            "--repo",
            str(repo_root),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data_root"] == str((atlas_root / "data").resolve())
    assert (atlas_root / "data" / "datasets").is_dir()
