import json
import sys
from pathlib import Path

import pytest

from atlas.adapters.base import AdapterContext
from atlas.adapters.splat import (
    GsplatAdapter,
    GsplatAdapterError,
    GsplatConfig,
    GsplatExecutables,
)
from atlas.frames.project import ProjectionManifest, VirtualViewRecord


def _write_projection_frame(
    root: Path,
    physical_frame_id: str,
    *,
    fov: float = 90,
    missing_last_image: bool = False,
) -> None:
    frame_dir = root / physical_frame_id
    frame_dir.mkdir(parents=True)
    views = []
    for index, yaw in enumerate((0.0, 90.0)):
        view_id = f"{physical_frame_id}__view-{index:03d}"
        filename = f"{view_id}.png"
        if not (missing_last_image and index == 1):
            (frame_dir / filename).write_bytes(
                f"{physical_frame_id}:{index}".encode("utf-8")
            )
        views.append(
            VirtualViewRecord(
                view_id=view_id,
                physical_frame_id=physical_frame_id,
                filename=filename,
                yaw_degrees=yaw,
                pitch_degrees=0,
                horizontal_fov_degrees=fov,
                width=64,
                height=48,
            )
        )
    manifest = ProjectionManifest(
        source_frame=f"{physical_frame_id}.png",
        physical_frame_id=physical_frame_id,
        views=views,
    )
    (frame_dir / "views.json").write_text(
        manifest.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def _projection_root(tmp_path: Path) -> Path:
    root = tmp_path / "perspective-views"
    _write_projection_frame(root, "physical-000000")
    _write_projection_frame(root, "physical-000001")
    (root / "physical-000000" / "not-in-manifest.png").write_bytes(b"ignore")
    return root


def _context(tmp_path: Path, input_path: Path) -> AdapterContext:
    return AdapterContext(
        input_path=input_path,
        prepared_dir=tmp_path / "splat-prepared",
        output_dir=tmp_path / "splat-output",
        log_dir=tmp_path / "splat-logs",
    )


def _fake_tools(path: Path) -> Path:
    path.write_text(
        r'''
from pathlib import Path
import json
import sys

tool = sys.argv[1]
args = sys.argv[2:]

def option(name):
    return args[args.index(name) + 1]

def emit(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")

if tool == "versions":
    print(json.dumps({
        "gsplat": "1.6.0",
        "torch": "2.7.1",
        "torch_cuda_build": "12.8",
    }))
    raise SystemExit(0)

if tool == "colmap" and args == ["-h"]:
    print("COLMAP fake-4.3.0")
    raise SystemExit(0)

if tool == "colmap":
    command = args[0]
    args = args[1:]
    if command == "feature_extractor":
        emit(option("--database_path"), "features")
    elif command == "sequential_matcher":
        pass
    elif command == "mapper":
        model = Path(option("--output_path")) / "0"
        emit(model / "cameras.bin", "cameras")
        emit(model / "images.bin", "images")
        emit(model / "points3D.bin", "points")
    elif command == "model_converter":
        model = Path(option("--output_path"))
        emit(model / "cameras.txt", "camera intrinsics")
        emit(model / "images.txt", "camera transforms")
        emit(model / "points3D.txt", "sparse points")
    else:
        raise SystemExit(f"unknown colmap command: {command}")
elif tool == "trainer":
    result = Path(option("--result_dir"))
    final_step = int(option("--max_steps")) - 1
    emit(result / "cfg.yml", "fixed config")
    emit(result / "ckpts" / f"ckpt_{final_step}_rank0.pt", "checkpoint")
    emit(result / "stats" / f"train_step{final_step:04d}_rank0.json", "{}")
    emit(result / "stats" / f"val_step{final_step:04d}.json", '{"psnr": 31.5}')
    emit(result / "ply" / f"point_cloud_{final_step}.ply", "viewer splat")
else:
    raise SystemExit(f"unknown fake tool: {tool}")

print(json.dumps({"tool": tool, "args": args}))
'''.strip(),
        encoding="utf-8",
    )
    return path


def _executables(fake_tools: Path) -> GsplatExecutables:
    return GsplatExecutables(
        colmap=(sys.executable, str(fake_tools), "colmap"),
        trainer=(sys.executable, str(fake_tools), "trainer"),
        environment_probe=(sys.executable, str(fake_tools), "versions"),
    )


def test_prepare_stages_manifested_views_and_physical_provenance(tmp_path: Path):
    input_path = _projection_root(tmp_path)
    context = _context(tmp_path, input_path)
    adapter = GsplatAdapter()

    adapter.prepare(context)

    staged = sorted(path.name for path in (context.prepared_dir / "images").iterdir())
    assert staged == [
        "physical-000000__view-000.png",
        "physical-000000__view-001.png",
        "physical-000001__view-000.png",
        "physical-000001__view-001.png",
    ]
    provenance = json.loads(
        (context.prepared_dir / "atlas-projection-index.json").read_text(
            encoding="utf-8"
        )
    )
    assert provenance["schema_version"] == 1
    assert [record["physical_frame_id"] for record in provenance["views"]] == [
        "physical-000000",
        "physical-000000",
        "physical-000001",
        "physical-000001",
    ]
    assert provenance["views"][0]["source_manifest"] == (
        "physical-000000/views.json"
    )
    assert all(len(record["sha256"]) == 64 for record in provenance["views"])
    assert "not-in-manifest.png" not in staged


def test_prepare_rejects_missing_manifested_view_before_external_commands(
    tmp_path: Path,
):
    input_path = tmp_path / "perspective-views"
    _write_projection_frame(
        input_path,
        "physical-000000",
        missing_last_image=True,
    )
    context = _context(tmp_path, input_path)

    with pytest.raises(GsplatAdapterError, match="manifested view does not exist"):
        GsplatAdapter().run(context)

    assert not list(context.log_dir.glob("*.json"))


def test_prepare_rejects_inconsistent_virtual_camera_layout(tmp_path: Path):
    input_path = tmp_path / "perspective-views"
    _write_projection_frame(input_path, "physical-000000", fov=90)
    _write_projection_frame(input_path, "physical-000001", fov=75)
    context = _context(tmp_path, input_path)

    with pytest.raises(GsplatAdapterError, match="same virtual camera layout"):
        GsplatAdapter().prepare(context)


def test_prepare_refuses_stale_colmap_state(tmp_path: Path):
    input_path = _projection_root(tmp_path)
    context = _context(tmp_path, input_path)
    context.prepared_dir.mkdir()
    (context.prepared_dir / "database.db").write_bytes(b"stale")

    with pytest.raises(GsplatAdapterError, match="prepared directory is not empty"):
        GsplatAdapter().prepare(context)

    assert not (context.prepared_dir / "images").exists()


def test_commands_build_reproducible_colmap_and_gsplat_plan(tmp_path: Path):
    input_path = _projection_root(tmp_path)
    context = _context(tmp_path, input_path)
    fake_tools = _fake_tools(tmp_path / "fake_tools.py")
    adapter = GsplatAdapter(
        GsplatConfig(
            executables=_executables(fake_tools),
            max_steps=1234,
            sequential_overlap=32,
        )
    )
    adapter.prepare(context)

    commands = adapter.commands(context)

    assert [command.label for command in commands] == [
        "colmap-features",
        "colmap-matches",
        "colmap-map",
        "colmap-export-cameras",
        "gsplat-train",
    ]
    features = commands[0].argv
    assert features[features.index("--ImageReader.camera_model") + 1] == "PINHOLE"
    assert features[features.index("--ImageReader.single_camera") + 1] == "1"
    assert features[features.index("--ImageReader.camera_params") + 1] == (
        "32,32,31.5,23.5"
    )
    matcher = commands[1].argv
    assert matcher[3] == "sequential_matcher"
    assert matcher[matcher.index("--SequentialMatching.overlap") + 1] == "32"
    trainer = commands[-1].argv
    assert trainer[2] == "trainer"
    assert trainer[3] == "default"
    assert trainer[trainer.index("--max_steps") + 1] == "1234"
    assert "--disable_viewer" in trainer
    assert "--save_ply" in trainer
    assert trainer[trainer.index("--data_factor") + 1] == "1"


def test_fake_pipeline_collects_splat_transforms_metrics_and_logs(tmp_path: Path):
    input_path = _projection_root(tmp_path)
    context = _context(tmp_path, input_path)
    fake_tools = _fake_tools(tmp_path / "fake_tools.py")
    adapter = GsplatAdapter(
        GsplatConfig(executables=_executables(fake_tools), max_steps=20)
    )

    result = adapter.run(context)

    assert len(result.executions) == 5
    assert all(execution.return_code == 0 for execution in result.executions)
    assert [artifact.kind for artifact in result.artifacts] == [
        "splat-input-provenance",
        "camera-intrinsics",
        "camera-transforms",
        "sparse-point-cloud",
        "splat-training-config",
        "splat-checkpoint",
        "splat-training-metrics",
        "splat-training-log",
        "viewer-splat",
    ]
    for artifact in result.artifacts:
        assert Path(artifact.path).is_file()
        assert len(artifact.sha256) == 64
    assert Path(result.artifacts[-1].path).name == "point_cloud_19.ply"


def test_detect_versions_records_colmap_gsplat_torch_and_cuda_build(tmp_path: Path):
    fake_tools = _fake_tools(tmp_path / "fake_tools.py")
    adapter = GsplatAdapter(
        GsplatConfig(executables=_executables(fake_tools))
    )

    versions = adapter.detect_versions()

    assert versions == {
        "colmap": "COLMAP fake-4.3.0",
        "gsplat": "1.6.0",
        "torch": "2.7.1",
        "torch_cuda_build": "12.8",
    }


def test_external_gsplat_checkout_is_referenced_not_vendored(tmp_path: Path):
    checkout = tmp_path / "external" / "gsplat"
    tools = GsplatExecutables.from_checkout(
        checkout,
        python_command=("python.exe",),
    )

    assert tools.trainer == (
        "python.exe",
        str(checkout / "examples" / "simple_trainer.py"),
    )
    assert tools.environment_probe[0] == "python.exe"
