import numpy as np
import pytest
from PIL import Image

from atlas.frames.project import (
    PerspectiveViewSpec,
    ProjectionError,
    equirectangular_to_perspective,
    project_virtual_views,
)


def coordinate_equirectangular_grid() -> np.ndarray:
    longitudes = np.arange(360, dtype=np.float32) - 180
    latitudes = 90 - np.arange(180, dtype=np.float32)
    longitude_grid, latitude_grid = np.meshgrid(longitudes, latitudes)
    return np.stack((longitude_grid, latitude_grid), axis=-1)


@pytest.mark.parametrize(
    ("yaw", "pitch", "expected_longitude", "expected_latitude"),
    [
        (0, 0, 0, 0),
        (90, 0, 90, 0),
        (180, 0, -180, 0),
        (-90, 0, -90, 0),
        (0, 45, 0, 45),
        (0, -45, 0, -45),
    ],
)
def test_projection_center_ray_maps_to_requested_spherical_direction(
    yaw: float,
    pitch: float,
    expected_longitude: float,
    expected_latitude: float,
):
    source = coordinate_equirectangular_grid()

    projected = equirectangular_to_perspective(
        source,
        yaw_degrees=yaw,
        pitch_degrees=pitch,
        horizontal_fov_degrees=90,
        output_width=3,
        output_height=3,
    )

    center = projected[1, 1]
    assert center[0] == pytest.approx(expected_longitude, abs=1e-4)
    assert center[1] == pytest.approx(expected_latitude, abs=1e-4)


def test_projection_rejects_non_equirectangular_source():
    source = np.zeros((100, 100, 3), dtype=np.uint8)

    with pytest.raises(ProjectionError, match="2:1"):
        equirectangular_to_perspective(
            source,
            yaw_degrees=0,
            pitch_degrees=0,
            horizontal_fov_degrees=90,
            output_width=64,
            output_height=64,
        )


@pytest.mark.parametrize("horizontal_fov_degrees", [0, 180])
def test_projection_rejects_invalid_horizontal_fov(horizontal_fov_degrees: float):
    source = np.zeros((180, 360, 3), dtype=np.uint8)

    with pytest.raises(ProjectionError, match="horizontal FOV"):
        equirectangular_to_perspective(
            source,
            yaw_degrees=0,
            pitch_degrees=0,
            horizontal_fov_degrees=horizontal_fov_degrees,
            output_width=64,
            output_height=64,
        )


@pytest.mark.parametrize(("output_width", "output_height"), [(0, 64), (64, 0)])
def test_projection_rejects_empty_output_dimensions(
    output_width: int, output_height: int
):
    source = np.zeros((180, 360, 3), dtype=np.uint8)

    with pytest.raises(ProjectionError, match="output dimensions"):
        equirectangular_to_perspective(
            source,
            yaw_degrees=0,
            pitch_degrees=0,
            horizontal_fov_degrees=90,
            output_width=output_width,
            output_height=output_height,
        )


def test_project_virtual_views_persists_physical_frame_provenance(tmp_path):
    source_path = tmp_path / "physical_000007.png"
    source = np.zeros((180, 360, 3), dtype=np.uint8)
    source[:, :, 0] = np.arange(360, dtype=np.uint16) % 256
    Image.fromarray(source).save(source_path)
    output_dir = tmp_path / "views"
    specs = [
        PerspectiveViewSpec(
            yaw_degrees=0,
            pitch_degrees=0,
            horizontal_fov_degrees=90,
            width=64,
            height=48,
        ),
        PerspectiveViewSpec(
            yaw_degrees=90,
            pitch_degrees=45,
            horizontal_fov_degrees=75,
            width=64,
            height=48,
        ),
    ]

    manifest = project_virtual_views(
        source_path,
        output_dir,
        physical_frame_id="physical-000007",
        specs=specs,
    )

    assert [view.filename for view in manifest.views] == [
        "physical-000007__view-000.png",
        "physical-000007__view-001.png",
    ]
    assert all((output_dir / view.filename).is_file() for view in manifest.views)
    persisted = (output_dir / "views.json").read_text(encoding="utf-8")
    assert persisted == manifest.model_dump_json(indent=2) + "\n"
    assert manifest.views[1].physical_frame_id == "physical-000007"
    assert manifest.views[1].yaw_degrees == 90
    assert manifest.views[1].pitch_degrees == 45
    assert manifest.views[1].horizontal_fov_degrees == 75


def test_project_virtual_views_rejects_path_traversal_in_physical_frame_id(
    tmp_path,
):
    source_path = tmp_path / "source.png"
    Image.fromarray(np.zeros((180, 360, 3), dtype=np.uint8)).save(source_path)
    output_dir = tmp_path / "views"
    spec = PerspectiveViewSpec(
        yaw_degrees=0,
        pitch_degrees=0,
        horizontal_fov_degrees=90,
        width=16,
        height=16,
    )

    with pytest.raises(ProjectionError, match="physical frame ID"):
        project_virtual_views(
            source_path,
            output_dir,
            physical_frame_id="../escape",
            specs=[spec],
        )

    assert not (tmp_path / "escape__view-000.png").exists()
