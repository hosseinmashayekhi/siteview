"""Download frozen Atlas datasets without publishing unverified bytes."""

import hashlib
import os
from collections.abc import Callable
from math import isclose
from pathlib import Path
from typing import BinaryIO, ContextManager
from urllib.error import URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from pydantic import ValidationError

from atlas.ingest.probe import VideoProbeError, probe_video
from atlas.manifest.models import DatasetManifest, VideoProbe


class DatasetDownloadError(RuntimeError):
    """Raised when a dataset cannot be downloaded and verified safely."""


class DatasetVerificationError(DatasetDownloadError):
    """Raised when downloaded video metadata differs from its manifest."""


OpenUrl = Callable[[str], ContextManager[BinaryIO]]
ProbeVideo = Callable[[Path], VideoProbe]
USER_AGENT = "SiteView-Atlas/0.1 (+https://github.com/hosseinmashayekhi/siteview)"
DOWNLOAD_TIMEOUT_SECONDS = 60.0


def load_dataset_manifest(path: Path) -> DatasetManifest:
    """Load one strict dataset manifest from disk."""
    try:
        return DatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as error:
        raise DatasetDownloadError(f"invalid dataset manifest {path}: {error}") from error


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Hash a file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_dataset(
    manifest: DatasetManifest,
    output_dir: Path,
    *,
    open_url: OpenUrl | None = None,
    chunk_size: int = 1024 * 1024,
) -> Path:
    """Stream, verify, and atomically publish a frozen dataset file."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    filename = manifest.filename or _source_filename(manifest.source)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / filename
    partial = target.with_name(f"{target.name}.partial")

    if target.exists():
        if _file_matches(target, manifest):
            return target
        raise DatasetDownloadError(
            f"existing file does not match manifest and was not overwritten: {target}"
        )

    partial.unlink(missing_ok=True)
    open_source = open_url or _open_dataset_url
    try:
        digest = hashlib.sha256()
        size_bytes = 0
        with open_source(manifest.source) as response, partial.open("xb") as stream:
            while chunk := response.read(chunk_size):
                stream.write(chunk)
                digest.update(chunk)
                size_bytes += len(chunk)

        _require_size(manifest, size_bytes)
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != manifest.sha256:
            raise DatasetDownloadError(
                "SHA-256 mismatch: "
                f"expected {manifest.sha256}, observed {actual_sha256}"
            )
        os.replace(partial, target)
        return target
    except DatasetDownloadError:
        partial.unlink(missing_ok=True)
        raise
    except (OSError, URLError) as error:
        partial.unlink(missing_ok=True)
        raise DatasetDownloadError(
            f"download failed for {manifest.id}: {error}"
        ) from error
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def verify_dataset_video(
    manifest: DatasetManifest,
    video_path: Path,
    *,
    probe: ProbeVideo = probe_video,
) -> VideoProbe:
    """Probe a dataset file and compare all declared expected metadata."""
    try:
        observed = probe(video_path)
    except VideoProbeError as error:
        raise DatasetVerificationError(f"video probe failed: {error}") from error

    expected = manifest.expected_probe
    if expected is None:
        return observed

    mismatches: list[str] = []
    for field in ("width", "height", "codec_name", "frame_count"):
        expected_value = getattr(expected, field)
        if expected_value is not None and getattr(observed, field) != expected_value:
            mismatches.append(
                f"{field} expected {expected_value}, observed {getattr(observed, field)}"
            )
    for field, absolute_tolerance in (("fps", 0.001), ("duration_seconds", 0.05)):
        expected_value = getattr(expected, field)
        observed_value = getattr(observed, field)
        if not isclose(
            observed_value,
            expected_value,
            rel_tol=0.0001,
            abs_tol=absolute_tolerance,
        ):
            mismatches.append(
                f"{field} expected {expected_value}, observed {observed_value}"
            )
    if mismatches:
        raise DatasetVerificationError("; ".join(mismatches))
    return observed


def _source_filename(source: str) -> str:
    parts = urlsplit(source)
    if parts.scheme not in {"http", "https"}:
        raise DatasetDownloadError("dataset source must use HTTP or HTTPS")
    filename = unquote(Path(parts.path).name)
    if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise DatasetDownloadError("dataset source does not contain a safe file name")
    return filename


def _open_dataset_url(source: str) -> ContextManager[BinaryIO]:
    request = Request(source, headers={"User-Agent": USER_AGENT})
    return urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS)


def _require_size(manifest: DatasetManifest, observed: int) -> None:
    if manifest.size_bytes is not None and observed != manifest.size_bytes:
        raise DatasetDownloadError(
            f"size mismatch: expected {manifest.size_bytes}, observed {observed}"
        )


def _file_matches(path: Path, manifest: DatasetManifest) -> bool:
    if not path.is_file():
        return False
    if manifest.size_bytes is not None and path.stat().st_size != manifest.size_bytes:
        return False
    return sha256_file(path) == manifest.sha256
