"""Vectorized equirectangular-to-perspective projection."""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from pydantic import Field, PositiveInt

from atlas.manifest.models import AtlasModel


class ProjectionError(ValueError):
    """Raised when a virtual camera request cannot be projected safely."""


class PerspectiveViewSpec(AtlasModel):
    """One explicit virtual camera; no orientation layout is implicit."""

    yaw_degrees: float
    pitch_degrees: Annotated[float, Field(ge=-90, le=90)]
    horizontal_fov_degrees: Annotated[float, Field(gt=0, lt=180)]
    width: PositiveInt
    height: PositiveInt


class VirtualViewRecord(PerspectiveViewSpec):
    view_id: str
    physical_frame_id: str
    filename: str


class ProjectionManifest(AtlasModel):
    schema_version: Literal[1] = 1
    source_frame: str
    physical_frame_id: str
    views: list[VirtualViewRecord]


def project_virtual_views(
    source_path: Path,
    output_dir: Path,
    *,
    physical_frame_id: str,
    specs: Sequence[PerspectiveViewSpec],
) -> ProjectionManifest:
    """Project and persist configured virtual cameras for one physical frame."""
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", physical_frame_id) is None:
        raise ProjectionError("physical frame ID contains unsafe path characters")

    with Image.open(source_path) as image:
        source = np.asarray(image.convert("RGB"))

    output_dir.mkdir(parents=True, exist_ok=True)
    views: list[VirtualViewRecord] = []
    for index, spec in enumerate(specs):
        view_id = f"{physical_frame_id}__view-{index:03d}"
        filename = f"{view_id}.png"
        projected = equirectangular_to_perspective(
            source,
            yaw_degrees=spec.yaw_degrees,
            pitch_degrees=spec.pitch_degrees,
            horizontal_fov_degrees=spec.horizontal_fov_degrees,
            output_width=spec.width,
            output_height=spec.height,
        )
        Image.fromarray(projected).save(
            output_dir / filename,
            format="PNG",
            compress_level=3,
        )
        views.append(
            VirtualViewRecord(
                **spec.model_dump(),
                view_id=view_id,
                physical_frame_id=physical_frame_id,
                filename=filename,
            )
        )

    manifest = ProjectionManifest(
        source_frame=source_path.name,
        physical_frame_id=physical_frame_id,
        views=views,
    )
    sidecar = output_dir / "views.json"
    partial = sidecar.with_suffix(".json.partial")
    partial.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    partial.replace(sidecar)
    return manifest


def equirectangular_to_perspective(
    source: NDArray[np.generic],
    *,
    yaw_degrees: float,
    pitch_degrees: float,
    horizontal_fov_degrees: float,
    output_width: int,
    output_height: int,
) -> NDArray[np.generic]:
    """Render one view using +yaw to the right and +pitch toward the zenith.

    Yaw zero points at the horizontal center of the equirectangular source.
    Horizontal pixels wrap at the longitude seam; latitude is clamped at the
    poles. Square perspective pixels are assumed.
    """
    source_height, source_width = source.shape[:2]
    if not np.isclose(source_width / source_height, 2.0, rtol=0.01):
        raise ProjectionError(
            f"expected a 2:1 equirectangular source, received "
            f"{source_width}x{source_height}"
        )
    if not 0 < horizontal_fov_degrees < 180:
        raise ProjectionError("horizontal FOV must be greater than 0 and less than 180")
    if output_width <= 0 or output_height <= 0:
        raise ProjectionError("output dimensions must both be greater than zero")

    focal_length = (output_width / 2) / np.tan(
        np.deg2rad(horizontal_fov_degrees) / 2
    )

    columns = np.arange(output_width, dtype=np.float64)
    rows = np.arange(output_height, dtype=np.float64)
    camera_x, camera_y = np.meshgrid(
        (columns - (output_width - 1) / 2) / focal_length,
        -(rows - (output_height - 1) / 2) / focal_length,
    )
    camera_z = np.ones_like(camera_x)
    length = np.sqrt(camera_x**2 + camera_y**2 + camera_z**2)
    camera_x /= length
    camera_y /= length
    camera_z /= length

    pitch = np.deg2rad(pitch_degrees)
    pitch_cos = np.cos(pitch)
    pitch_sin = np.sin(pitch)
    pitched_x = camera_x
    pitched_y = pitch_cos * camera_y + pitch_sin * camera_z
    pitched_z = -pitch_sin * camera_y + pitch_cos * camera_z

    yaw = np.deg2rad(yaw_degrees)
    yaw_cos = np.cos(yaw)
    yaw_sin = np.sin(yaw)
    world_x = yaw_cos * pitched_x + yaw_sin * pitched_z
    world_y = pitched_y
    world_z = -yaw_sin * pitched_x + yaw_cos * pitched_z

    longitude = np.arctan2(world_x, world_z)
    latitude = np.arcsin(np.clip(world_y, -1.0, 1.0))
    source_x = (longitude / (2 * np.pi) + 0.5) * source_width
    source_y = (0.5 - latitude / np.pi) * source_height

    return _bilinear_sample(source, source_x, source_y)


def _bilinear_sample(
    source: NDArray[np.generic],
    source_x: NDArray[np.float64],
    source_y: NDArray[np.float64],
) -> NDArray[np.generic]:
    height, width = source.shape[:2]
    wrapped_x = np.mod(source_x, width)
    clipped_y = np.clip(source_y, 0, height - 1)

    x0 = np.floor(wrapped_x).astype(np.int64)
    y0 = np.floor(clipped_y).astype(np.int64)
    x1 = (x0 + 1) % width
    y1 = np.minimum(y0 + 1, height - 1)

    x_weight = wrapped_x - x0
    y_weight = clipped_y - y0
    if source.ndim == 3:
        x_weight = x_weight[..., None]
        y_weight = y_weight[..., None]

    top = source[y0, x0] * (1 - x_weight) + source[y0, x1] * x_weight
    bottom = source[y1, x0] * (1 - x_weight) + source[y1, x1] * x_weight
    result = top * (1 - y_weight) + bottom * y_weight

    if np.issubdtype(source.dtype, np.integer):
        limits = np.iinfo(source.dtype)
        result = np.clip(np.rint(result), limits.min, limits.max)
    return result.astype(source.dtype, copy=False)
