import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request

import pytest

from atlas.datasets.download import (
    DatasetDownloadError,
    DatasetVerificationError,
    download_dataset,
    load_dataset_manifest,
    verify_dataset_video,
)
from atlas.manifest.models import DatasetManifest, VideoProbe


def _manifest(payload: bytes, **overrides) -> DatasetManifest:
    values = {
        "id": "smoke-room",
        "tier": "smoke",
        "source": "https://example.invalid/room.webm",
        "license": "CC-BY-4.0",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "filename": "smoke-room.webm",
        "projection": "equirectangular",
        "expected_probe": VideoProbe(
            width=854,
            height=428,
            fps=29.678,
            duration_seconds=12.5,
            codec_name="vp9",
            frame_count=None,
        ),
    }
    values.update(overrides)
    return DatasetManifest(**values)


def test_download_streams_to_partial_then_atomically_publishes(tmp_path: Path):
    payload = b"moving-360-video" * 4096
    opened = []

    def open_url(url: str):
        opened.append(url)
        return io.BytesIO(payload)

    target = download_dataset(
        _manifest(payload),
        tmp_path,
        open_url=open_url,
        chunk_size=257,
    )

    assert opened == ["https://example.invalid/room.webm"]
    assert target == tmp_path / "smoke-room.webm"
    assert target.read_bytes() == payload
    assert not (tmp_path / "smoke-room.webm.partial").exists()


def test_download_rejects_bad_checksum_without_publishing_file(tmp_path: Path):
    payload = b"corrupt-download"
    manifest = _manifest(payload, sha256="f" * 64)

    with pytest.raises(DatasetDownloadError, match="SHA-256 mismatch"):
        download_dataset(manifest, tmp_path, open_url=lambda _url: io.BytesIO(payload))

    assert not (tmp_path / "smoke-room.webm").exists()
    assert not (tmp_path / "smoke-room.webm.partial").exists()


def test_download_reuses_existing_verified_file_without_network(tmp_path: Path):
    payload = b"already-downloaded"
    manifest = _manifest(payload)
    target = tmp_path / manifest.filename
    target.write_bytes(payload)

    def unexpected_network(_url: str):
        raise AssertionError("verified files must not be downloaded again")

    assert download_dataset(manifest, tmp_path, open_url=unexpected_network) == target


def test_download_refuses_to_overwrite_existing_unverified_file(tmp_path: Path):
    payload = b"expected"
    manifest = _manifest(payload)
    target = tmp_path / manifest.filename
    target.write_bytes(b"user-data")

    with pytest.raises(DatasetDownloadError, match="existing file does not match"):
        download_dataset(manifest, tmp_path, open_url=lambda _url: io.BytesIO(payload))

    assert target.read_bytes() == b"user-data"


def test_default_http_client_sends_identifiable_user_agent(
    tmp_path: Path, monkeypatch
):
    payload = b"public-video"
    captured = []

    def fake_urlopen(request: Request, *, timeout: float):
        captured.append((request, timeout))
        return io.BytesIO(payload)

    monkeypatch.setattr("atlas.datasets.download.urlopen", fake_urlopen)

    download_dataset(_manifest(payload), tmp_path)

    request, timeout = captured[0]
    assert request.full_url == "https://example.invalid/room.webm"
    assert request.get_header("User-agent").startswith("SiteView-Atlas/")
    assert timeout > 0


def test_network_failure_is_reported_as_controlled_download_error(tmp_path: Path):
    payload = b"public-video"

    def offline(_url: str):
        raise OSError("network unavailable")

    with pytest.raises(DatasetDownloadError, match="download failed.*network unavailable"):
        download_dataset(_manifest(payload), tmp_path, open_url=offline)


def test_manifest_loader_rejects_non_dataset_json(tmp_path: Path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"run_id": "not-a-dataset"}), encoding="utf-8")

    with pytest.raises(DatasetDownloadError, match="invalid dataset manifest"):
        load_dataset_manifest(path)


def test_video_verification_returns_observed_metadata_when_it_matches(tmp_path: Path):
    payload = b"video"
    manifest = _manifest(payload)
    target = tmp_path / manifest.filename
    target.write_bytes(payload)
    observed = VideoProbe(
        width=854,
        height=428,
        fps=29.678,
        duration_seconds=12.51,
        codec_name="vp9",
        frame_count=None,
    )

    assert verify_dataset_video(manifest, target, probe=lambda _path: observed) == observed


def test_video_verification_reports_expected_metadata_mismatch(tmp_path: Path):
    payload = b"video"
    manifest = _manifest(payload)
    target = tmp_path / manifest.filename
    target.write_bytes(payload)
    wrong = VideoProbe(
        width=1920,
        height=960,
        fps=29.678,
        duration_seconds=12.5,
        codec_name="vp9",
        frame_count=None,
    )

    with pytest.raises(DatasetVerificationError, match="width expected 854, observed 1920"):
        verify_dataset_video(manifest, target, probe=lambda _path: wrong)


def test_checked_in_public_manifests_freeze_download_and_expected_video_metadata():
    repository = Path(__file__).resolve().parents[2]

    smoke = load_dataset_manifest(repository / "datasets/atlas/smoke.json")
    benchmark = load_dataset_manifest(repository / "datasets/atlas/benchmark.json")

    assert smoke.tier == "smoke"
    assert smoke.expected_probe.width == 854
    assert smoke.characteristics.indoor is True
    assert smoke.characteristics.moving_camera is True
    assert benchmark.tier == "benchmark"
    assert benchmark.expected_probe.width == 3840
    assert benchmark.expected_probe.height == 1920
    assert benchmark.characteristics.revisits is None
    assert smoke.source != benchmark.source
    assert smoke.sha256 != benchmark.sha256
