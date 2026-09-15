"""Atlas manifest contracts."""

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    StringConstraints,
)


Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class AtlasModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetManifest(AtlasModel):
    id: str
    source: str
    license: str
    sha256: Sha256
    projection: Literal["equirectangular"]


class VideoProbe(AtlasModel):
    width: PositiveInt
    height: PositiveInt
    fps: PositiveFloat
    duration_seconds: PositiveFloat
    codec_name: str | None = None
    frame_count: NonNegativeInt | None = None


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
