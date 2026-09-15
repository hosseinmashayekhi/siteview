"""Reproducible execution contract for external reconstruction engines."""

import hashlib
import json
import os
import re
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from pydantic import BaseModel, ConfigDict, NonNegativeFloat

from atlas.manifest.models import ArtifactRecord


@dataclass(frozen=True)
class AdapterContext:
    """Paths shared by an adapter invocation."""

    input_path: Path
    prepared_dir: Path
    output_dir: Path
    log_dir: Path


@dataclass(frozen=True)
class CommandSpec:
    """One external command represented as argv, never a shell string."""

    label: str
    argv: tuple[str, ...]
    cwd: Path

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.label):
            raise ValueError("command label must be a safe nonempty log name")
        if not self.argv or not self.argv[0]:
            raise ValueError("command argv must contain an executable")


class CommandExecution(BaseModel):
    """Durable provenance for one attempted external process."""

    model_config = ConfigDict(extra="forbid")

    label: str
    argv: list[str]
    cwd: str
    return_code: int | None
    stdout_log: str
    stderr_log: str
    elapsed_seconds: NonNegativeFloat
    error: str | None = None


class AdapterRunResult(BaseModel):
    """External command provenance and collected output artifacts."""

    model_config = ConfigDict(extra="forbid")

    adapter: str
    executions: list[CommandExecution]
    artifacts: list[ArtifactRecord]


class ExternalCommandError(RuntimeError):
    """Raised after a failed launch or nonzero process has been logged."""

    def __init__(self, execution: CommandExecution):
        self.execution = execution
        detail = execution.error or f"exit code {execution.return_code}"
        super().__init__(f"{execution.label} failed: {detail}")


class ExternalReconstructionAdapter(ABC):
    """Lifecycle implemented by each external reconstruction engine."""

    name: str

    @abstractmethod
    def prepare(self, context: AdapterContext) -> None:
        """Prepare engine-specific inputs without running reconstruction."""

    @abstractmethod
    def commands(self, context: AdapterContext) -> list[CommandSpec]:
        """Return the deterministic ordered process plan."""

    @abstractmethod
    def collect(self, context: AdapterContext) -> list[ArtifactRecord]:
        """Validate and record artifacts produced by successful commands."""

    def run(self, context: AdapterContext) -> AdapterRunResult:
        """Execute the standard lifecycle and stop at the first failed command."""
        context.log_dir.mkdir(parents=True, exist_ok=True)
        context.output_dir.mkdir(parents=True, exist_ok=True)
        self.prepare(context)
        command_plan = self.commands(context)
        executions: list[CommandExecution] = []
        for index, command in enumerate(command_plan):
            execution = _execute(command, index=index, log_dir=context.log_dir)
            executions.append(execution)
            if execution.return_code != 0:
                raise ExternalCommandError(execution)
        artifacts = self.collect(context)
        return AdapterRunResult(
            adapter=self.name,
            executions=executions,
            artifacts=artifacts,
        )


def record_artifact(kind: str, path: Path) -> ArtifactRecord:
    """Create a provenance record for an existing output file."""
    if not path.is_file():
        raise FileNotFoundError(f"artifact does not exist: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return ArtifactRecord(kind=kind, path=str(path.resolve()), sha256=digest.hexdigest())


def _execute(command: CommandSpec, *, index: int, log_dir: Path) -> CommandExecution:
    cwd = command.cwd.resolve()
    prefix = f"{index:03d}-{command.label}"
    stdout_path = (log_dir / f"{prefix}.stdout.log").resolve()
    stderr_path = (log_dir / f"{prefix}.stderr.log").resolve()
    record_path = log_dir / f"{prefix}.json"
    started = perf_counter()
    error_message: str | None = None
    try:
        completed = subprocess.run(
            list(command.argv),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except OSError as error:
        return_code = None
        stdout = ""
        stderr = ""
        error_message = str(error)
    elapsed_seconds = perf_counter() - started

    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    execution = CommandExecution(
        label=command.label,
        argv=list(command.argv),
        cwd=str(cwd),
        return_code=return_code,
        stdout_log=str(stdout_path),
        stderr_log=str(stderr_path),
        elapsed_seconds=elapsed_seconds,
        error=error_message,
    )
    _write_json_atomic(record_path, execution.model_dump(mode="json"))
    return execution


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    partial = path.with_name(f"{path.name}.partial")
    partial.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(partial, path)
