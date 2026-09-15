import json
import sys
from pathlib import Path

import pytest

from atlas.adapters.base import AdapterContext
from atlas.adapters.openmvs import (
    OpenMVSAdapter,
    OpenMVSAdapterError,
    OpenMVSConfig,
    OpenMVSExecutables,
)


OPENMVS_TOOL_NAMES = (
    "ExtractKeyframes",
    "CreateStructure",
    "DensifyPointCloud",
    "ReconstructMesh",
    "RefineMesh",
    "TextureMesh",
    "TransformScene",
)


def _fake_openmvs(path: Path) -> Path:
    path.write_text(
        """
from pathlib import Path
import json
import sys

tool = sys.argv[1]
args = sys.argv[2:]

if args == ["--version"]:
    print(f"OpenMVS fake-2.3.0 ({tool})")
    raise SystemExit(0)

def option(name):
    return args[args.index(name) + 1]

def emit(filename):
    target = Path(filename)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(tool, encoding="utf-8")
    return target

if tool == "ExtractKeyframes":
    emit(option("-o"))
    frame_dir = Path(option("-d"))
    frame_dir.mkdir(parents=True, exist_ok=True)
    emit(frame_dir / "frame-000001.jpg")
elif tool == "CreateStructure":
    emit(option("-o"))
    emit(option("--export-mvs"))
elif tool == "DensifyPointCloud":
    scene = emit(option("-o"))
    emit(scene.with_suffix(".ply"))
elif tool == "ReconstructMesh":
    scene = emit(option("-o"))
    emit(scene.with_suffix(".ply"))
elif tool == "RefineMesh":
    scene = emit(option("-o"))
    emit(scene.with_suffix(".ply"))
elif tool == "TextureMesh":
    scene = emit(option("-o"))
    emit(scene.with_suffix(".ply"))
    emit(scene.with_name(scene.stem + "0.png"))
elif tool == "TransformScene":
    emit(Path(args[0]).with_suffix(".glb"))
else:
    print(f"unknown fake tool: {tool}", file=sys.stderr)
    raise SystemExit(9)

print(json.dumps({"tool": tool, "args": args}))
""".strip(),
        encoding="utf-8",
    )
    return path


def _executables(fake_tool: Path) -> OpenMVSExecutables:
    def prefix(name: str) -> tuple[str, ...]:
        return (sys.executable, str(fake_tool), name)

    return OpenMVSExecutables(
        extract_keyframes=prefix("ExtractKeyframes"),
        create_structure=prefix("CreateStructure"),
        densify_point_cloud=prefix("DensifyPointCloud"),
        reconstruct_mesh=prefix("ReconstructMesh"),
        refine_mesh=prefix("RefineMesh"),
        texture_mesh=prefix("TextureMesh"),
        transform_scene=prefix("TransformScene"),
    )


def _context(tmp_path: Path) -> AdapterContext:
    video = tmp_path / "moving panorama.webm"
    video.write_bytes(b"equirectangular-video")
    return AdapterContext(
        input_path=video,
        prepared_dir=tmp_path / "prepared",
        output_dir=tmp_path / "geometry",
        log_dir=tmp_path / "logs",
    )


def test_openmvs_builds_official_native_spherical_pipeline(tmp_path: Path):
    fake_tool = _fake_openmvs(tmp_path / "fake_openmvs.py")
    adapter = OpenMVSAdapter(
        OpenMVSConfig(executables=_executables(fake_tool), cubemap_faces=12)
    )
    context = _context(tmp_path)
    adapter.prepare(context)

    commands = adapter.commands(context)

    assert [command.label for command in commands] == [
        "extract-keyframes",
        "create-structure",
        "densify-point-cloud",
        "reconstruct-mesh",
        "refine-mesh",
        "texture-mesh",
        "export-glb",
    ]
    extract = commands[0].argv
    assert extract[-2:] != ("moving", "panorama.webm")
    assert extract[extract.index("-i") + 1] == str(context.input_path.resolve())
    assert extract[extract.index("--camera-type") + 1] == "1"
    assert extract[extract.index("--cubemap-faces") + 1] == "12"
    assert extract[extract.index("--overlap-threshold") + 1] == "0.85"
    create = commands[1].argv
    assert "--export-mvs" in create
    assert create[create.index("--extract-colors") + 1] == "1"


def test_openmvs_fake_pipeline_collects_hashed_geometry_and_web_mesh(tmp_path: Path):
    fake_tool = _fake_openmvs(tmp_path / "fake_openmvs.py")
    adapter = OpenMVSAdapter(OpenMVSConfig(executables=_executables(fake_tool)))
    context = _context(tmp_path)

    result = adapter.run(context)

    assert len(result.executions) == 7
    assert all(execution.return_code == 0 for execution in result.executions)
    kinds = [artifact.kind for artifact in result.artifacts]
    assert kinds == [
        "camera-poses",
        "openmvs-scene",
        "dense-point-cloud",
        "refined-mesh",
        "textured-mesh",
        "texture",
        "viewer-mesh",
    ]
    for artifact in result.artifacts:
        assert Path(artifact.path).is_file()
        assert len(artifact.sha256) == 64
    assert Path(result.artifacts[-1].path).suffix == ".glb"
    first_command = json.loads(
        (context.log_dir / "000-extract-keyframes.json").read_text(encoding="utf-8")
    )
    assert first_command["argv"][first_command["argv"].index("--camera-type") + 1] == "1"


def test_openmvs_detects_every_external_tool_version(tmp_path: Path):
    fake_tool = _fake_openmvs(tmp_path / "fake_openmvs.py")
    adapter = OpenMVSAdapter(OpenMVSConfig(executables=_executables(fake_tool)))

    versions = adapter.detect_versions()

    assert set(versions) == {
        "openmvs.ExtractKeyframes",
        "openmvs.CreateStructure",
        "openmvs.DensifyPointCloud",
        "openmvs.ReconstructMesh",
        "openmvs.RefineMesh",
        "openmvs.TextureMesh",
        "openmvs.TransformScene",
    }
    assert versions["openmvs.ExtractKeyframes"] == (
        "OpenMVS fake-2.3.0 (ExtractKeyframes)"
    )


def test_openmvs_missing_input_stops_before_commands(tmp_path: Path):
    fake_tool = _fake_openmvs(tmp_path / "fake_openmvs.py")
    adapter = OpenMVSAdapter(OpenMVSConfig(executables=_executables(fake_tool)))
    context = AdapterContext(
        input_path=tmp_path / "missing.webm",
        prepared_dir=tmp_path / "prepared",
        output_dir=tmp_path / "geometry",
        log_dir=tmp_path / "logs",
    )

    with pytest.raises(OpenMVSAdapterError, match="input video does not exist"):
        adapter.run(context)

    assert not list(context.log_dir.glob("*.json"))


def test_openmvs_version_probe_reports_missing_executable(tmp_path: Path):
    missing = (str(tmp_path / "missing-tool"),)
    tools = OpenMVSExecutables(
        extract_keyframes=missing,
        create_structure=missing,
        densify_point_cloud=missing,
        reconstruct_mesh=missing,
        refine_mesh=missing,
        texture_mesh=missing,
        transform_scene=missing,
    )
    adapter = OpenMVSAdapter(OpenMVSConfig(executables=tools))

    with pytest.raises(OpenMVSAdapterError, match="ExtractKeyframes.*not found"):
        adapter.detect_versions()


def test_openmvs_version_probe_falls_back_to_documented_help_flag(tmp_path: Path):
    fake_tool = tmp_path / "help_only.py"
    fake_tool.write_text(
        """
import sys
if sys.argv[-1] == "--version":
    print("unsupported", file=sys.stderr)
    raise SystemExit(2)
if sys.argv[-1] == "-h":
    print(f"OpenMVS help-version ({sys.argv[1]})")
    raise SystemExit(0)
raise SystemExit(3)
""".strip(),
        encoding="utf-8",
    )
    adapter = OpenMVSAdapter(
        OpenMVSConfig(executables=_executables(fake_tool))
    )

    versions = adapter.detect_versions()

    assert versions["openmvs.TransformScene"] == "OpenMVS help-version (TransformScene)"


def test_openmvs_executable_directory_does_not_vendor_binaries(tmp_path: Path):
    tools = OpenMVSExecutables.from_bin_dir(tmp_path, executable_suffix=".exe")

    assert tools.extract_keyframes == (str(tmp_path / "ExtractKeyframes.exe"),)
    assert tools.texture_mesh == (str(tmp_path / "TextureMesh.exe"),)
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize("cubemap_faces", [0, 5, 7, 24])
def test_openmvs_rejects_unsupported_cubemap_layout(cubemap_faces: int):
    with pytest.raises(ValueError, match="cubemap_faces"):
        OpenMVSConfig(cubemap_faces=cubemap_faces)
