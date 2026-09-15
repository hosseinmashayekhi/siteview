import hashlib
import json
import sys
from pathlib import Path

import pytest

from atlas.adapters.base import (
    AdapterContext,
    CommandSpec,
    ExternalCommandError,
    ExternalReconstructionAdapter,
    record_artifact,
)


class RecordingAdapter(ExternalReconstructionAdapter):
    name = "recording"

    def __init__(self, executable: Path, events: list[str], *, fail: bool = False):
        self.executable = executable
        self.events = events
        self.fail = fail

    def prepare(self, context: AdapterContext) -> None:
        self.events.append("prepare")
        context.prepared_dir.mkdir(parents=True, exist_ok=True)
        (context.prepared_dir / "ready.txt").write_text("ready", encoding="utf-8")

    def commands(self, context: AdapterContext) -> list[CommandSpec]:
        self.events.append("commands")
        assert (context.prepared_dir / "ready.txt").is_file()
        return [
            CommandSpec(
                label="fake-reconstruction",
                argv=(
                    sys.executable,
                    str(self.executable),
                    str(context.output_dir / "model.ply"),
                    "fail" if self.fail else "literal;not-a-shell-command",
                ),
                cwd=context.prepared_dir,
            )
        ]

    def collect(self, context: AdapterContext):
        self.events.append("collect")
        return [record_artifact("point-cloud", context.output_dir / "model.ply")]


def _fake_executable(path: Path) -> Path:
    path.write_text(
        """
import pathlib
import sys

print(f"stdout:{sys.argv[2]}")
print("stderr:evidence", file=sys.stderr)
if sys.argv[2] == "fail":
    raise SystemExit(7)
output = pathlib.Path(sys.argv[1])
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(sys.argv[2], encoding="utf-8")
""".strip(),
        encoding="utf-8",
    )
    return path


def _context(tmp_path: Path) -> AdapterContext:
    input_path = tmp_path / "capture.webm"
    input_path.write_bytes(b"360-video")
    return AdapterContext(
        input_path=input_path,
        prepared_dir=tmp_path / "prepared",
        output_dir=tmp_path / "output",
        log_dir=tmp_path / "logs",
    )


def test_adapter_runs_prepare_commands_and_collect_with_complete_logs(tmp_path: Path):
    context = _context(tmp_path)
    events: list[str] = []
    adapter = RecordingAdapter(_fake_executable(tmp_path / "fake_tool.py"), events)

    result = adapter.run(context)

    assert events == ["prepare", "commands", "collect"]
    assert result.adapter == "recording"
    assert len(result.executions) == 1
    execution = result.executions[0]
    assert execution.argv[-1] == "literal;not-a-shell-command"
    assert execution.cwd == str(context.prepared_dir.resolve())
    assert execution.return_code == 0
    assert execution.elapsed_seconds >= 0
    assert Path(execution.stdout_log).read_text(encoding="utf-8").strip() == (
        "stdout:literal;not-a-shell-command"
    )
    assert Path(execution.stderr_log).read_text(encoding="utf-8").strip() == (
        "stderr:evidence"
    )
    command_log = json.loads(
        (context.log_dir / "000-fake-reconstruction.json").read_text(encoding="utf-8")
    )
    assert command_log == execution.model_dump(mode="json")
    assert result.artifacts[0].sha256 == hashlib.sha256(
        b"literal;not-a-shell-command"
    ).hexdigest()


def test_adapter_records_nonzero_exit_before_stopping_pipeline(tmp_path: Path):
    context = _context(tmp_path)
    events: list[str] = []
    adapter = RecordingAdapter(
        _fake_executable(tmp_path / "fake_tool.py"), events, fail=True
    )

    with pytest.raises(ExternalCommandError) as captured:
        adapter.run(context)

    assert events == ["prepare", "commands"]
    assert captured.value.execution.return_code == 7
    assert Path(captured.value.execution.stderr_log).read_text(
        encoding="utf-8"
    ).strip() == "stderr:evidence"
    command_log = json.loads(
        (context.log_dir / "000-fake-reconstruction.json").read_text(encoding="utf-8")
    )
    assert command_log["return_code"] == 7
    assert not (context.output_dir / "model.ply").exists()


def test_adapter_records_missing_executable_as_launch_failure(tmp_path: Path):
    context = _context(tmp_path)

    class MissingAdapter(RecordingAdapter):
        def commands(self, context: AdapterContext) -> list[CommandSpec]:
            self.events.append("commands")
            return [
                CommandSpec(
                    label="missing",
                    argv=(str(tmp_path / "does-not-exist"),),
                    cwd=context.prepared_dir,
                )
            ]

    adapter = MissingAdapter(tmp_path / "unused", [])

    with pytest.raises(ExternalCommandError) as captured:
        adapter.run(context)

    assert captured.value.execution.return_code is None
    assert "No such file" in captured.value.execution.error
    assert (context.log_dir / "000-missing.json").is_file()


@pytest.mark.parametrize("label", ["../escape", "has/slash", r"has\slash", ""])
def test_command_label_must_be_a_safe_log_name(label: str):
    with pytest.raises(ValueError, match="label"):
        CommandSpec(label=label, argv=("tool",), cwd=Path("."))


def test_command_requires_nonempty_argv():
    with pytest.raises(ValueError, match="argv"):
        CommandSpec(label="empty", argv=(), cwd=Path("."))
