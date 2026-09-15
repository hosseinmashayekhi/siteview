"""Self-contained, credential-free Atlas viewer manifest."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal
from urllib.parse import unquote, urlsplit

from pydantic import Field, FiniteFloat, StringConstraints, field_validator, model_validator

from atlas.manifest.models import AtlasModel, Sha256


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Position3D = tuple[FiniteFloat, FiniteFloat, FiniteFloat]
AssetMode = Literal["mesh", "splat"]
AssetFormat = Literal["glb", "gaussian-ply", "splat", "spz"]


class ViewerAsset(AtlasModel):
    """One verified representation exposed to a renderer boundary."""

    mode: AssetMode
    format: AssetFormat
    url: str
    sha256: Sha256

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _safe_relative_url(value)

    @model_validator(mode="after")
    def validate_mode_format(self) -> "ViewerAsset":
        valid_formats = {
            "mesh": {"glb"},
            "splat": {"gaussian-ply", "splat", "spz"},
        }
        if self.format not in valid_formats[self.mode]:
            raise ValueError(f"format is not valid for {self.mode} mode")
        return self


class ViewerManifest(AtlasModel):
    """All local resources needed by the standalone Atlas viewer."""

    schema_version: Literal[1] = 1
    run_id: NonEmptyText
    input_sha256: Sha256
    coordinate_system: NonEmptyText
    initial_position: Position3D
    assets: list[ViewerAsset] = Field(min_length=1)
    evidence_index_url: str
    original_frame_base_url: str
    run_manifest_url: str
    benchmark_report_url: str

    @field_validator(
        "evidence_index_url",
        "original_frame_base_url",
        "run_manifest_url",
        "benchmark_report_url",
    )
    @classmethod
    def validate_resource_url(cls, value: str) -> str:
        return _safe_relative_url(value)

    @model_validator(mode="after")
    def validate_unique_modes(self) -> "ViewerManifest":
        modes = [asset.mode for asset in self.assets]
        if len(modes) != len(set(modes)):
            raise ValueError("duplicate viewer mode")
        return self


def write_viewer_manifest(manifest: ViewerManifest, output_dir: Path) -> Path:
    """Atomically write the manifest consumed by the static viewer."""
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "viewer-manifest.json"
    partial = destination.with_name(f"{destination.name}.partial")
    payload = json.dumps(
        manifest.model_dump(mode="json"), indent=2, sort_keys=True
    ) + "\n"
    try:
        partial.write_text(payload, encoding="utf-8")
        os.replace(partial, destination)
    finally:
        if partial.exists():
            partial.unlink()
    return destination


def _safe_relative_url(value: str) -> str:
    if not value or "\\" in value:
        raise ValueError("resource must use a safe relative URL")
    parsed = urlsplit(value)
    decoded_path = unquote(parsed.path)
    path = PurePosixPath(decoded_path)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or decoded_path.startswith("/")
        or decoded_path.startswith("//")
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("resource must use a safe relative URL")
    return value
