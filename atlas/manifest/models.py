"""Atlas manifest contracts."""

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    field_validator,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    StringConstraints,
)


Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class AtlasModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VideoProbe(AtlasModel):
    width: PositiveInt
    height: PositiveInt
    fps: PositiveFloat
    duration_seconds: PositiveFloat
    codec_name: str | None = None
    frame_count: NonNegativeInt | None = None


class DatasetCharacteristics(AtlasModel):
    indoor: bool
    moving_camera: bool
    revisits: bool | None = None
    visual_overlap: bool | None = None
    parallax: bool | None = None


class DatasetManifest(AtlasModel):
    id: str
    source: str
    license: str
    sha256: Sha256
    projection: Literal["equirectangular"]
    tier: Literal["smoke", "benchmark", "x5-validation"] | None = None
    title: str | None = None
    source_page: str | None = None
    license_url: str | None = None
    attribution: str | None = None
    size_bytes: PositiveInt | None = None
    filename: str | None = None
    expected_probe: VideoProbe | None = None
    characteristics: DatasetCharacteristics | None = None
    purpose: str | None = None

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value in {"", ".", ".."} or "/" in value or "\\" in value:
            raise ValueError("filename must be a single file name")
        return value


class ArtifactRecord(AtlasModel):
    kind: str
    path: str
    sha256: Sha256


class RunManifest(AtlasModel):
    run_id: str
    input_sha256: Sha256
    commands: list[list[str]]
    tool_versions: dict[str, str]
    artifacts: list[ArtifactRecord]
    timing_seconds: dict[str, float]
    gpu: dict[str, Any] | None = None
