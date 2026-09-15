"""External OpenMVS native spherical-video geometry baseline."""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from atlas.adapters.base import (
    AdapterContext,
    CommandSpec,
    ExternalReconstructionAdapter,
    record_artifact,
)
from atlas.manifest.models import ArtifactRecord


class OpenMVSAdapterError(RuntimeError):
    """Raised when the external OpenMVS baseline is not usable."""


@dataclass(frozen=True)
class OpenMVSExecutables:
    """Explicit argv prefixes for every external OpenMVS application."""

    extract_keyframes: tuple[str, ...] = ("ExtractKeyframes",)
    create_structure: tuple[str, ...] = ("CreateStructure",)
    densify_point_cloud: tuple[str, ...] = ("DensifyPointCloud",)
    reconstruct_mesh: tuple[str, ...] = ("ReconstructMesh",)
    refine_mesh: tuple[str, ...] = ("RefineMesh",)
    texture_mesh: tuple[str, ...] = ("TextureMesh",)
    transform_scene: tuple[str, ...] = ("TransformScene",)

    def __post_init__(self) -> None:
        for name, prefix in self.items():
            if not prefix or not prefix[0]:
                raise ValueError(f"OpenMVS executable prefix is empty: {name}")

    @classmethod
    def from_bin_dir(
        cls,
        bin_dir: Path,
        *,
        executable_suffix: str | None = None,
    ) -> "OpenMVSExecutables":
        """Point at external binaries without copying them into Atlas."""
        suffix = (
            ".exe" if os.name == "nt" else ""
        ) if executable_suffix is None else executable_suffix

        def executable(name: str) -> tuple[str, ...]:
            return (str(bin_dir / f"{name}{suffix}"),)

        return cls(
            extract_keyframes=executable("ExtractKeyframes"),
            create_structure=executable("CreateStructure"),
            densify_point_cloud=executable("DensifyPointCloud"),
            reconstruct_mesh=executable("ReconstructMesh"),
            refine_mesh=executable("RefineMesh"),
            texture_mesh=executable("TextureMesh"),
            transform_scene=executable("TransformScene"),
        )

    def items(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return (
            ("ExtractKeyframes", self.extract_keyframes),
            ("CreateStructure", self.create_structure),
            ("DensifyPointCloud", self.densify_point_cloud),
            ("ReconstructMesh", self.reconstruct_mesh),
            ("RefineMesh", self.refine_mesh),
            ("TextureMesh", self.texture_mesh),
            ("TransformScene", self.transform_scene),
        )


@dataclass(frozen=True)
class OpenMVSConfig:
    """Frozen, inspectable choices for the geometry baseline."""

    executables: OpenMVSExecutables = field(default_factory=OpenMVSExecutables)
    cubemap_faces: int = 6
    overlap_threshold: float = 0.85
    detector_type: str = "SIFT"

    def __post_init__(self) -> None:
        if self.cubemap_faces not in {4, 6, 8, 12, 20}:
            raise ValueError("cubemap_faces must be one of 4, 6, 8, 12, or 20")
        if not 0 < self.overlap_threshold <= 1:
            raise ValueError("overlap_threshold must be greater than 0 and at most 1")
        if self.detector_type not in {"SIFT", "AKAZE", "ORB", "SIFTGPU"}:
            raise ValueError("detector_type is not supported by OpenMVS")


class OpenMVSAdapter(ExternalReconstructionAdapter):
    """Run OpenMVS's documented 360-video-to-textured-mesh pipeline."""

    name = "openmvs-native-spherical"

    def __init__(self, config: OpenMVSConfig | None = None):
        self.config = config or OpenMVSConfig()

    def prepare(self, context: AdapterContext) -> None:
        if not context.input_path.is_file():
            raise OpenMVSAdapterError(
                f"input video does not exist: {context.input_path}"
            )
        context.prepared_dir.mkdir(parents=True, exist_ok=True)
        context.output_dir.mkdir(parents=True, exist_ok=True)

    def commands(self, context: AdapterContext) -> list[CommandSpec]:
        prepared = context.prepared_dir.resolve()
        output = context.output_dir.resolve()
        video = context.input_path.resolve()
        keyframes_sfm = prepared / "scene_keyframes.sfm"
        keyframes_dir = prepared / "keyframes"
        scene_sfm = output / "scene.sfm"
        scene_mvs = output / "scene.mvs"
        dense_mvs = output / "scene_dense.mvs"
        dense_ply = output / "scene_dense.ply"
        mesh_mvs = output / "scene_dense_mesh.mvs"
        mesh_ply = output / "scene_dense_mesh.ply"
        refined_mvs = output / "scene_dense_mesh_refine.mvs"
        refined_ply = output / "scene_dense_mesh_refine.ply"
        textured_mvs = output / "scene_dense_mesh_refine_texture.mvs"
        overlap = format(self.config.overlap_threshold, ".12g")
        tools = self.config.executables

        return [
            CommandSpec(
                label="extract-keyframes",
                argv=(
                    *tools.extract_keyframes,
                    "-i",
                    str(video),
                    "-o",
                    str(keyframes_sfm),
                    "-d",
                    str(keyframes_dir),
                    "--camera-type",
                    "1",
                    "--cubemap-faces",
                    str(self.config.cubemap_faces),
                    "--overlap-threshold",
                    overlap,
                    "--detector-type",
                    self.config.detector_type,
                    "-v",
                    "3",
                ),
                cwd=output,
            ),
            CommandSpec(
                label="create-structure",
                argv=(
                    *tools.create_structure,
                    "-s",
                    str(keyframes_sfm),
                    "-o",
                    str(scene_sfm),
                    "--export-mvs",
                    str(scene_mvs),
                    "--extract-colors",
                    "1",
                    "-v",
                    "3",
                ),
                cwd=output,
            ),
            CommandSpec(
                label="densify-point-cloud",
                argv=(
                    *tools.densify_point_cloud,
                    str(scene_mvs),
                    "-o",
                    str(dense_mvs),
                    "-v",
                    "3",
                ),
                cwd=output,
            ),
            CommandSpec(
                label="reconstruct-mesh",
                argv=(
                    *tools.reconstruct_mesh,
                    str(dense_mvs),
                    "-p",
                    str(dense_ply),
                    "-o",
                    str(mesh_mvs),
                    "-v",
                    "3",
                ),
                cwd=output,
            ),
            CommandSpec(
                label="refine-mesh",
                argv=(
                    *tools.refine_mesh,
                    str(dense_mvs),
                    "-m",
                    str(mesh_ply),
                    "-o",
                    str(refined_mvs),
                    "--scales",
                    "1",
                    "--max-face-area",
                    "16",
                    "-v",
                    "3",
                ),
                cwd=output,
            ),
            CommandSpec(
                label="texture-mesh",
                argv=(
                    *tools.texture_mesh,
                    str(dense_mvs),
                    "-m",
                    str(refined_ply),
                    "-o",
                    str(textured_mvs),
                    "-v",
                    "3",
                ),
                cwd=output,
            ),
            CommandSpec(
                label="export-glb",
                argv=(
                    *tools.transform_scene,
                    str(textured_mvs),
                    "--convert",
                    "1",
                    "--export-type",
                    "glb",
                ),
                cwd=output,
            ),
        ]

    def collect(self, context: AdapterContext) -> list[ArtifactRecord]:
        output = context.output_dir.resolve()
        textured_stem = "scene_dense_mesh_refine_texture"
        artifacts = [
            record_artifact("camera-poses", output / "scene.sfm"),
            record_artifact("openmvs-scene", output / "scene.mvs"),
            record_artifact("dense-point-cloud", output / "scene_dense.ply"),
            record_artifact("refined-mesh", output / "scene_dense_mesh_refine.ply"),
            record_artifact("textured-mesh", output / f"{textured_stem}.ply"),
        ]
        textures = sorted(output.glob(f"{textured_stem}*.png"))
        if not textures:
            raise OpenMVSAdapterError("OpenMVS produced no texture image")
        artifacts.extend(record_artifact("texture", path) for path in textures)
        artifacts.append(record_artifact("viewer-mesh", output / f"{textured_stem}.glb"))
        return artifacts

    def detect_versions(self) -> dict[str, str]:
        """Read a version banner from every configured external application."""
        versions: dict[str, str] = {}
        for tool_name, executable in self.config.executables.items():
            versions[f"openmvs.{tool_name}"] = _detect_version(
                tool_name, executable
            )
        return versions


def _detect_version(tool_name: str, executable: tuple[str, ...]) -> str:
    failures: list[str] = []
    for flag in ("--version", "-h"):
        try:
            result = subprocess.run(
                [*executable, flag],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError as error:
            raise OpenMVSAdapterError(
                f"{tool_name} executable not found: {executable[0]}"
            ) from error
        output = result.stdout.strip() or result.stderr.strip()
        version = next(
            (line.strip() for line in output.splitlines() if line.strip()),
            None,
        )
        if result.returncode == 0 and version is not None:
            return version
        detail = output or "no diagnostic output"
        failures.append(f"{flag}: exit code {result.returncode}: {detail}")
    raise OpenMVSAdapterError(
        f"{tool_name} version probe failed ({'; '.join(failures)})"
    )
