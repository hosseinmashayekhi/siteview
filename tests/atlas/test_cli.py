import json

from typer.testing import CliRunner

from atlas.cli import app


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
