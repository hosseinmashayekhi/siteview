"""Record the Windows/NVIDIA execution environment without inferred values."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EnvironmentModel(BaseModel):
    """Strict base model for machine-readable environment reports."""

    model_config = ConfigDict(extra="forbid")


class ToolProbe(EnvironmentModel):
    command: list[str]
    available: bool
    version: str | None = None
    error: str | None = None


class GpuInfo(EnvironmentModel):
    name: str
    driver_version: str
    memory_total_mib: int = Field(ge=0)


class ExternalEngineProbe(EnvironmentModel):
    environment_variable: str
    configured_path: str | None = None
    exists: bool | None = None


class EnvironmentReport(EnvironmentModel):
    schema_version: Literal["1.0"] = "1.0"
    generated_at: datetime
    platform: str
    python_version: str
    python_executable: str
    atlas_root: str | None = None
    atlas_data_root: str | None = None
    tools: dict[str, ToolProbe]
    gpus: list[GpuInfo]
    cuda_version_reported_by_nvidia_smi: str | None = None
    docker_gpu_verified: bool | None = None
    external_engines: dict[str, ExternalEngineProbe]


DEFAULT_COMMANDS: dict[str, tuple[str, ...]] = {
    "git": ("git", "--version"),
    "ffmpeg": ("ffmpeg", "-version"),
    "ffprobe": ("ffprobe", "-version"),
    "docker": ("docker", "version", "--format", "{{.Server.Version}}"),
    "wsl": ("wsl.exe", "--status"),
    "nvidia_smi": ("nvidia-smi",),
    "nvidia_query": (
        "nvidia-smi",
        "--query-gpu=name,driver_version,memory.total",
        "--format=csv,noheader,nounits",
    ),
}

_CUDA_VERSION = re.compile(r"\bCUDA Version:\s*([0-9]+(?:\.[0-9]+)*)")


def parse_nvidia_smi_csv(output: str) -> list[GpuInfo]:
    """Parse the explicit three-column query used by :func:`probe_environment`."""
    gpus: list[GpuInfo] = []
    for line_number, line in enumerate(output.splitlines(), start=1):
        if not line.strip():
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 3:
            raise ValueError(
                f"invalid nvidia-smi CSV on line {line_number}: expected 3 columns"
            )
        name, driver_version, memory_total_mib = fields
        try:
            memory = int(memory_total_mib)
        except ValueError as error:
            raise ValueError(
                f"invalid nvidia-smi memory on line {line_number}: "
                f"{memory_total_mib!r}"
            ) from error
        gpus.append(
            GpuInfo(
                name=name,
                driver_version=driver_version,
                memory_total_mib=memory,
            )
        )
    return gpus


def _run_tool(command: Sequence[str]) -> tuple[ToolProbe, str]:
    argv = [str(part) for part in command]
    try:
        result = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return (
            ToolProbe(
                command=argv,
                available=False,
                error=f"executable not found: {argv[0]}",
            ),
            "",
        )

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    combined = stdout or stderr
    if result.returncode != 0:
        detail = combined or "no diagnostic output"
        return (
            ToolProbe(
                command=argv,
                available=False,
                error=f"exit code {result.returncode}: {detail}",
            ),
            combined,
        )
    version = next((line.strip() for line in combined.splitlines() if line.strip()), None)
    return ToolProbe(command=argv, available=True, version=version), combined


def _external_engine(
    environ: Mapping[str, str], environment_variable: str
) -> ExternalEngineProbe:
    value = environ.get(environment_variable)
    if not value:
        return ExternalEngineProbe(environment_variable=environment_variable)
    return ExternalEngineProbe(
        environment_variable=environment_variable,
        configured_path=value,
        exists=Path(value).exists(),
    )


def probe_environment(
    *,
    commands: Mapping[str, Sequence[str]] | None = None,
    environ: Mapping[str, str] | None = None,
    platform_description: str | None = None,
) -> EnvironmentReport:
    """Probe host tools and GPU metadata, leaving unverified facts as null."""
    selected = dict(DEFAULT_COMMANDS)
    if commands is not None:
        selected.update(commands)
    environment = os.environ if environ is None else environ

    tools: dict[str, ToolProbe] = {}
    outputs: dict[str, str] = {}
    for name in ("git", "ffmpeg", "ffprobe", "docker", "wsl", "nvidia_smi"):
        tools[name], outputs[name] = _run_tool(selected[name])

    gpus: list[GpuInfo] = []
    query_probe, query_output = _run_tool(selected["nvidia_query"])
    if query_probe.available:
        try:
            gpus = parse_nvidia_smi_csv(query_output)
        except ValueError as error:
            tools["nvidia_smi"] = ToolProbe(
                command=tools["nvidia_smi"].command,
                available=False,
                error=str(error),
            )
    elif tools["nvidia_smi"].available:
        tools["nvidia_smi"] = ToolProbe(
            command=query_probe.command,
            available=False,
            error=f"GPU query failed: {query_probe.error}",
        )

    cuda_version = None
    cuda_match = _CUDA_VERSION.search(outputs["nvidia_smi"])
    if cuda_match:
        cuda_version = cuda_match.group(1)

    return EnvironmentReport(
        generated_at=datetime.now(timezone.utc),
        platform=platform_description or platform.platform(),
        python_version=platform.python_version(),
        python_executable=sys.executable,
        atlas_root=environment.get("ATLAS_ROOT"),
        atlas_data_root=environment.get("ATLAS_DATA_ROOT"),
        tools=tools,
        gpus=gpus,
        cuda_version_reported_by_nvidia_smi=cuda_version,
        docker_gpu_verified=None,
        external_engines={
            "openmvs": _external_engine(environment, "ATLAS_OPENMVS_BIN"),
            "splat": _external_engine(environment, "ATLAS_SPLAT_BIN"),
        },
    )


def write_environment_report(report: EnvironmentReport, destination: Path) -> None:
    """Atomically write an environment report as UTF-8 JSON."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    partial.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    partial.replace(destination)
