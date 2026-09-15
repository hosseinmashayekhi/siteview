"""External COLMAP + gsplat visual-detail baseline."""

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from atlas.adapters.base import (
    AdapterContext,
    CommandSpec,
    ExternalReconstructionAdapter,
    record_artifact,
)
from atlas.frames.project import ProjectionManifest
from atlas.manifest.models import ArtifactRecord, AtlasModel, Sha256


class GsplatAdapterError(RuntimeError):
    """Raised when the external gsplat detail baseline is not usable."""


class SplatInputView(AtlasModel):
    """Portable link from a training image back to one physical 360 frame."""

    view_id: str
    physical_frame_id: str
    source_frame: str
    source_manifest: str
    staged_filename: str
    sha256: Sha256
    yaw_degrees: float
    pitch_degrees: float
    horizontal_fov_degrees: float
    width: int
    height: int


class SplatInputIndex(AtlasModel):
    """All deterministic perspective views supplied to the splat track."""

    schema_version: Literal[1] = 1
    views: list[SplatInputView]


_ENVIRONMENT_PROBE = (
    "import importlib.metadata as m, json, torch; "
    "print(json.dumps({"
    "'gsplat': m.version('gsplat'), "
    "'torch': str(torch.__version__), "
    "'torch_cuda_build': torch.version.cuda"
    "}))"
)


@dataclass(frozen=True)
class GsplatExecutables:
    """External command prefixes; Atlas never vendors gsplat or COLMAP."""

    colmap: tuple[str, ...] = ("colmap",)
    trainer: tuple[str, ...] = ("python", "-m", "examples.simple_trainer")
    environment_probe: tuple[str, ...] = (
        "python",
        "-c",
        _ENVIRONMENT_PROBE,
    )

    def __post_init__(self) -> None:
        for name, prefix in (
            ("colmap", self.colmap),
            ("trainer", self.trainer),
            ("environment_probe", self.environment_probe),
        ):
            if not prefix or not prefix[0]:
                raise ValueError(f"gsplat executable prefix is empty: {name}")

    @classmethod
    def from_checkout(
        cls,
        checkout: Path,
        *,
        python_command: tuple[str, ...] = ("python",),
        colmap_command: tuple[str, ...] = ("colmap",),
    ) -> "GsplatExecutables":
        """Reference an external gsplat checkout without copying its code."""
        if not python_command or not python_command[0]:
            raise ValueError("python command prefix is empty")
        return cls(
            colmap=colmap_command,
            trainer=(
                *python_command,
                str(checkout / "examples" / "simple_trainer.py"),
            ),
            environment_probe=(*python_command, "-c", _ENVIRONMENT_PROBE),
        )


@dataclass(frozen=True)
class GsplatConfig:
    """Inspectable parameters for the provisional visual-detail baseline."""

    executables: GsplatExecutables = field(default_factory=GsplatExecutables)
    max_steps: int = 30_000
    matching_method: Literal["sequential", "exhaustive"] = "sequential"
    sequential_overlap: int = 32
    test_every: int = 8
    random_seed: int = 0

    def __post_init__(self) -> None:
        if self.max_steps <= 0:
            raise ValueError("max_steps must be greater than zero")
        if self.matching_method not in {"sequential", "exhaustive"}:
            raise ValueError("matching_method must be sequential or exhaustive")
        if self.sequential_overlap <= 0:
            raise ValueError("sequential_overlap must be greater than zero")
        if self.test_every <= 1:
            raise ValueError("test_every must be greater than one")
        if self.random_seed < 0:
            raise ValueError("random_seed must not be negative")


class GsplatAdapter(ExternalReconstructionAdapter):
    """Estimate poses with COLMAP and train the official gsplat example."""

    name = "gsplat-colmap-perspective"

    def __init__(self, config: GsplatConfig | None = None):
        self.config = config or GsplatConfig()

    def prepare(self, context: AdapterContext) -> None:
        input_root = context.input_path.resolve()
        if not input_root.is_dir():
            raise GsplatAdapterError(
                f"projection input directory does not exist: {context.input_path}"
            )

        sidecars = sorted(input_root.rglob("views.json"))
        if not sidecars:
            raise GsplatAdapterError(
                f"projection input contains no views.json manifests: {input_root}"
            )

        context.prepared_dir.mkdir(parents=True, exist_ok=True)
        context.output_dir.mkdir(parents=True, exist_ok=True)
        if any(context.prepared_dir.iterdir()):
            raise GsplatAdapterError("splat prepared directory is not empty")
        if any(context.output_dir.iterdir()):
            raise GsplatAdapterError("splat output directory is not empty")
        images_dir = context.prepared_dir / "images"
        partial_images = context.prepared_dir / "images.partial"
        index_path = context.prepared_dir / "atlas-projection-index.json"

        manifests: list[tuple[Path, ProjectionManifest]] = []
        reference_layout: tuple[tuple[float, float, float, int, int], ...] | None = (
            None
        )
        view_ids: set[str] = set()
        filenames: set[str] = set()
        for sidecar in sidecars:
            try:
                manifest = ProjectionManifest.model_validate_json(
                    sidecar.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as error:
                raise GsplatAdapterError(
                    f"invalid projection manifest: {sidecar}: {error}"
                ) from error
            if not manifest.views:
                raise GsplatAdapterError(f"projection manifest has no views: {sidecar}")
            layout = tuple(
                (
                    view.yaw_degrees,
                    view.pitch_degrees,
                    view.horizontal_fov_degrees,
                    view.width,
                    view.height,
                )
                for view in manifest.views
            )
            if reference_layout is None:
                reference_layout = layout
            elif layout != reference_layout:
                raise GsplatAdapterError(
                    "all physical frames must use the same virtual camera layout"
                )
            for view in manifest.views:
                if view.physical_frame_id != manifest.physical_frame_id:
                    raise GsplatAdapterError(
                        f"view physical frame ID disagrees with manifest: {view.view_id}"
                    )
                if view.view_id in view_ids:
                    raise GsplatAdapterError(f"duplicate virtual view ID: {view.view_id}")
                if view.filename in filenames:
                    raise GsplatAdapterError(
                        f"duplicate virtual view filename: {view.filename}"
                    )
                if (
                    Path(view.filename).name != view.filename
                    or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", view.filename)
                    is None
                ):
                    raise GsplatAdapterError(
                        f"unsafe virtual view filename: {view.filename}"
                    )
                view_ids.add(view.view_id)
                filenames.add(view.filename)
            manifests.append((sidecar, manifest))

        partial_images.mkdir()
        records: list[SplatInputView] = []
        try:
            for sidecar, manifest in manifests:
                relative_manifest = sidecar.relative_to(input_root).as_posix()
                for view in manifest.views:
                    source = sidecar.parent / view.filename
                    try:
                        resolved_source = source.resolve(strict=True)
                    except FileNotFoundError as error:
                        raise GsplatAdapterError(
                            f"manifested view does not exist: {source}"
                        ) from error
                    if not resolved_source.is_file() or not resolved_source.is_relative_to(
                        input_root
                    ):
                        raise GsplatAdapterError(
                            f"manifested view is outside the projection input: {source}"
                        )
                    target = partial_images / view.filename
                    _link_or_copy(resolved_source, target)
                    records.append(
                        SplatInputView(
                            view_id=view.view_id,
                            physical_frame_id=view.physical_frame_id,
                            source_frame=manifest.source_frame,
                            source_manifest=relative_manifest,
                            staged_filename=view.filename,
                            sha256=_sha256(target),
                            yaw_degrees=view.yaw_degrees,
                            pitch_degrees=view.pitch_degrees,
                            horizontal_fov_degrees=view.horizontal_fov_degrees,
                            width=view.width,
                            height=view.height,
                        )
                    )
            os.replace(partial_images, images_dir)
        except Exception:
            shutil.rmtree(partial_images, ignore_errors=True)
            raise

        index = SplatInputIndex(views=records)
        partial_index = index_path.with_suffix(".json.partial")
        partial_index.write_text(
            index.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(partial_index, index_path)
        (context.prepared_dir / "sparse").mkdir()
        (context.prepared_dir / "sparse-text").mkdir()

    def commands(self, context: AdapterContext) -> list[CommandSpec]:
        prepared = context.prepared_dir.resolve()
        output = context.output_dir.resolve()
        images = prepared / "images"
        database = prepared / "database.db"
        sparse = prepared / "sparse"
        sparse_model = sparse / "0"
        sparse_text = prepared / "sparse-text"
        camera_params = _camera_params(_read_input_index(prepared))
        tools = self.config.executables
        seed = str(self.config.random_seed)

        matcher_argv = [
            *tools.colmap,
            f"{self.config.matching_method}_matcher",
            "--database_path",
            str(database),
            "--FeatureMatching.use_gpu",
            "1",
            "--default_random_seed",
            seed,
        ]
        if self.config.matching_method == "sequential":
            matcher_argv.extend(
                [
                    "--SequentialMatching.overlap",
                    str(self.config.sequential_overlap),
                ]
            )

        max_steps = str(self.config.max_steps)
        return [
            CommandSpec(
                label="colmap-features",
                argv=(
                    *tools.colmap,
                    "feature_extractor",
                    "--database_path",
                    str(database),
                    "--image_path",
                    str(images),
                    "--ImageReader.camera_model",
                    "PINHOLE",
                    "--ImageReader.single_camera",
                    "1",
                    "--ImageReader.camera_params",
                    camera_params,
                    "--FeatureExtraction.type",
                    "SIFT",
                    "--FeatureExtraction.use_gpu",
                    "1",
                    "--default_random_seed",
                    seed,
                ),
                cwd=prepared,
            ),
            CommandSpec(
                label="colmap-matches",
                argv=tuple(matcher_argv),
                cwd=prepared,
            ),
            CommandSpec(
                label="colmap-map",
                argv=(
                    *tools.colmap,
                    "mapper",
                    "--database_path",
                    str(database),
                    "--image_path",
                    str(images),
                    "--output_path",
                    str(sparse),
                    "--default_random_seed",
                    seed,
                ),
                cwd=prepared,
            ),
            CommandSpec(
                label="colmap-export-cameras",
                argv=(
                    *tools.colmap,
                    "model_converter",
                    "--input_path",
                    str(sparse_model),
                    "--output_path",
                    str(sparse_text),
                    "--output_type",
                    "TXT",
                ),
                cwd=prepared,
            ),
            CommandSpec(
                label="gsplat-train",
                argv=(
                    *tools.trainer,
                    "default",
                    "--disable_viewer",
                    "--disable_video",
                    "--data_dir",
                    str(prepared),
                    "--data_factor",
                    "1",
                    "--result_dir",
                    str(output),
                    "--test_every",
                    str(self.config.test_every),
                    "--max_steps",
                    max_steps,
                    "--eval_steps",
                    max_steps,
                    "--save_steps",
                    max_steps,
                    "--save_ply",
                    "--ply_steps",
                    max_steps,
                ),
                cwd=output,
            ),
        ]

    def collect(self, context: AdapterContext) -> list[ArtifactRecord]:
        prepared = context.prepared_dir.resolve()
        output = context.output_dir.resolve()
        final_step = self.config.max_steps - 1
        return [
            record_artifact(
                "splat-input-provenance",
                prepared / "atlas-projection-index.json",
            ),
            record_artifact("camera-intrinsics", prepared / "sparse-text/cameras.txt"),
            record_artifact("camera-transforms", prepared / "sparse-text/images.txt"),
            record_artifact("sparse-point-cloud", prepared / "sparse-text/points3D.txt"),
            record_artifact("splat-training-config", output / "cfg.yml"),
            record_artifact(
                "splat-checkpoint",
                output / "ckpts" / f"ckpt_{final_step}_rank0.pt",
            ),
            record_artifact(
                "splat-training-metrics",
                output / "stats" / f"val_step{final_step:04d}.json",
            ),
            record_artifact(
                "splat-training-log",
                context.log_dir.resolve() / "004-gsplat-train.stdout.log",
            ),
            record_artifact(
                "viewer-splat",
                output / "ply" / f"point_cloud_{final_step}.ply",
            ),
        ]

    def detect_versions(self) -> dict[str, str]:
        """Record the COLMAP, gsplat, PyTorch, and CUDA build versions."""
        versions = {"colmap": _command_banner(self.config.executables.colmap)}
        probe = _run_environment_probe(self.config.executables.environment_probe)
        versions.update(
            (str(key), str(value))
            for key, value in probe.items()
            if value is not None
        )
        return versions


def _read_input_index(prepared_dir: Path) -> SplatInputIndex:
    index_path = prepared_dir / "atlas-projection-index.json"
    try:
        return SplatInputIndex.model_validate_json(
            index_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as error:
        raise GsplatAdapterError(f"invalid staged projection index: {error}") from error


def _camera_params(index: SplatInputIndex) -> str:
    if not index.views:
        raise GsplatAdapterError("staged projection index contains no views")
    view = index.views[0]
    focal = (view.width / 2) / math.tan(
        math.radians(view.horizontal_fov_degrees) / 2
    )
    center_x = (view.width - 1) / 2
    center_y = (view.height - 1) / 2
    return ",".join(
        format(value, ".12g")
        for value in (focal, focal, center_x, center_y)
    )


def _link_or_copy(source: Path, target: Path) -> None:
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _command_banner(prefix: tuple[str, ...]) -> str:
    try:
        result = subprocess.run(
            [*prefix, "-h"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as error:
        raise GsplatAdapterError(f"COLMAP executable not found: {prefix[0]}") from error
    output = result.stdout.strip() or result.stderr.strip()
    banner = next((line.strip() for line in output.splitlines() if line.strip()), None)
    if result.returncode != 0 or banner is None:
        raise GsplatAdapterError(
            f"COLMAP version probe failed with exit code {result.returncode}: "
            f"{output or 'no diagnostic output'}"
        )
    return banner


def _run_environment_probe(prefix: tuple[str, ...]) -> dict[str, object]:
    try:
        result = subprocess.run(
            list(prefix),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as error:
        raise GsplatAdapterError(
            f"gsplat Python executable not found: {prefix[0]}"
        ) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise GsplatAdapterError(
            f"gsplat environment probe failed with exit code {result.returncode}: {detail}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise GsplatAdapterError("gsplat environment probe returned invalid JSON") from error
    if not isinstance(payload, dict) or not {"gsplat", "torch"}.issubset(payload):
        raise GsplatAdapterError("gsplat environment probe omitted required versions")
    return payload
