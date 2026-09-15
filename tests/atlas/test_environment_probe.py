import json
import sys

from atlas.environment.probe import (
    parse_nvidia_smi_csv,
    probe_environment,
    write_environment_report,
)


def test_parse_nvidia_smi_csv_preserves_each_gpu_without_guessing():
    gpus = parse_nvidia_smi_csv(
        "NVIDIA GeForce RTX 5090, 581.15, 32607\n"
        "NVIDIA RTX 6000 Ada, 581.15, 49140\n"
    )

    assert [gpu.model_dump() for gpu in gpus] == [
        {
            "name": "NVIDIA GeForce RTX 5090",
            "driver_version": "581.15",
            "memory_total_mib": 32607,
        },
        {
            "name": "NVIDIA RTX 6000 Ada",
            "driver_version": "581.15",
            "memory_total_mib": 49140,
        },
    ]


def test_probe_environment_records_real_command_results_and_missing_values(
    tmp_path, monkeypatch
):
    args_log = tmp_path / "args.jsonl"
    fake_tool = tmp_path / "fake_tool.py"
    fake_tool.write_text(
        """\
import json
import os
import sys
from pathlib import Path

log = Path(os.environ["ATLAS_FAKE_ARGS_LOG"])
with log.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")

mode = sys.argv[1]
if mode == "git":
    print("git version 2.51.0")
elif mode == "ffmpeg":
    print("ffmpeg version 8.0")
elif mode == "ffprobe":
    print("ffprobe version 8.0")
elif mode == "docker":
    print("28.4.0")
elif mode == "wsl":
    print("Default Version: 2")
elif mode == "nvidia-header":
    print("NVIDIA-SMI 581.15 Driver Version: 581.15 CUDA Version: 13.0")
elif mode == "nvidia-query":
    print("NVIDIA GeForce RTX 5090, 581.15, 32607")
else:
    raise SystemExit(9)
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("ATLAS_FAKE_ARGS_LOG", str(args_log))
    monkeypatch.setenv("ATLAS_ROOT", r"C:\3dcamera")
    monkeypatch.setenv("ATLAS_DATA_ROOT", r"C:\3dcamera\data")
    monkeypatch.setenv("ATLAS_OPENMVS_BIN", str(tmp_path / "missing-openmvs"))
    monkeypatch.delenv("ATLAS_SPLAT_BIN", raising=False)

    report = probe_environment(
        commands={
            name: (sys.executable, str(fake_tool), name)
            for name in ("git", "ffmpeg", "ffprobe", "docker", "wsl")
        }
        | {
            "nvidia_smi": (
                sys.executable,
                str(fake_tool),
                "nvidia-header",
            ),
            "nvidia_query": (
                sys.executable,
                str(fake_tool),
                "nvidia-query",
            ),
        },
        platform_description="Windows-11-test",
    )

    assert report.platform == "Windows-11-test"
    assert report.atlas_root == r"C:\3dcamera"
    assert report.atlas_data_root == r"C:\3dcamera\data"
    assert report.tools["git"].available is True
    assert report.tools["git"].version == "git version 2.51.0"
    assert report.tools["docker"].version == "28.4.0"
    assert report.gpus[0].name == "NVIDIA GeForce RTX 5090"
    assert report.cuda_version_reported_by_nvidia_smi == "13.0"
    assert report.docker_gpu_verified is None
    assert report.external_engines["openmvs"].configured_path == str(
        tmp_path / "missing-openmvs"
    )
    assert report.external_engines["openmvs"].exists is False
    assert report.external_engines["splat"].configured_path is None
    assert report.external_engines["splat"].exists is None
    assert json.loads(args_log.read_text(encoding="utf-8").splitlines()[0]) == [
        "git"
    ]


def test_probe_environment_keeps_unavailable_tool_fields_null(tmp_path):
    missing = str(tmp_path / "not-installed")
    commands = {
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
    }

    report = probe_environment(
        commands=commands,
        environ={},
        platform_description="Windows-11-test",
    )

    assert report.tools["nvidia_smi"].available is False
    assert report.tools["nvidia_smi"].version is None
    assert report.gpus == []
    assert report.cuda_version_reported_by_nvidia_smi is None
    assert report.docker_gpu_verified is None
    assert all(engine.configured_path is None for engine in report.external_engines.values())


def test_probe_environment_does_not_claim_gpu_visibility_when_query_fails(tmp_path):
    header = tmp_path / "header.py"
    header.write_text(
        'print("NVIDIA-SMI 581.15 CUDA Version: 13.0")\n', encoding="utf-8"
    )
    query = tmp_path / "query.py"
    query.write_text(
        'import sys; sys.stderr.write("query unavailable"); raise SystemExit(7)\n',
        encoding="utf-8",
    )
    missing = str(tmp_path / "missing")
    commands = {
        name: (missing,)
        for name in ("git", "ffmpeg", "ffprobe", "docker", "wsl")
    } | {
        "nvidia_smi": (sys.executable, str(header)),
        "nvidia_query": (sys.executable, str(query)),
    }

    report = probe_environment(commands=commands, environ={})

    assert report.tools["nvidia_smi"].available is False
    assert report.tools["nvidia_smi"].version is None
    assert "GPU query failed" in report.tools["nvidia_smi"].error
    assert report.gpus == []


def test_write_environment_report_replaces_destination_atomically(tmp_path):
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
        environ={},
        platform_description="Windows-11-test",
    )
    destination = tmp_path / "reports" / "environment.json"
    destination.parent.mkdir()
    destination.write_text("stale", encoding="utf-8")

    write_environment_report(report, destination)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["platform"] == "Windows-11-test"
    assert not destination.with_suffix(".json.partial").exists()
