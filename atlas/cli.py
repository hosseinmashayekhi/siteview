"""Command-line entry point for the Atlas pipeline."""

from pathlib import Path

import typer
from pydantic import TypeAdapter, ValidationError

from atlas.environment.probe import probe_environment, write_environment_report
from atlas.environment.workspace import WorkspaceError, initialize_workspace
from atlas.ingest.probe import VideoProbeError, probe_video
from atlas.manifest.models import DatasetManifest, RunManifest


app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Inspect and run the standalone Atlas reconstruction pipeline."""


@app.command("inspect-manifest")
def inspect_manifest(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
) -> None:
    """Validate and print a normalized Atlas dataset or run manifest."""
    adapter = TypeAdapter(DatasetManifest | RunManifest)
    try:
        manifest = adapter.validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        typer.echo(f"Invalid Atlas manifest: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(manifest.model_dump_json(indent=2))


@app.command("probe")
def probe_command(
    video: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
) -> None:
    """Inspect and validate a moving 2:1 equirectangular video."""
    try:
        probe = probe_video(video)
    except VideoProbeError as error:
        typer.echo(f"Video inspection failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(probe.model_dump_json(indent=2))


@app.command("probe-environment")
def probe_environment_command(
    output: Path | None = typer.Option(
        None,
        "--output",
        dir_okay=False,
        help="Also write the report atomically to this JSON file.",
    ),
) -> None:
    """Record host, NVIDIA, Docker, and external-engine visibility."""
    report = probe_environment()
    if output is not None:
        write_environment_report(report, output)
    typer.echo(report.model_dump_json(indent=2))


@app.command("init-workspace")
def init_workspace_command(
    root: Path = typer.Option(
        Path(r"C:\3dcamera"),
        "--root",
        help="Atlas laptop root; generated data is placed under its data folder.",
    ),
    repo: Path = typer.Option(
        Path.cwd(),
        "--repo",
        exists=True,
        file_okay=False,
        readable=True,
        help="Checked-out SiteView repository root.",
    ),
) -> None:
    """Create the local data workspace without placing artifacts in Git."""
    try:
        layout = initialize_workspace(atlas_root=root, repo_root=repo)
    except WorkspaceError as error:
        typer.echo(f"Workspace setup failed: {error}", err=True)
        raise typer.Exit(code=2) from error
    typer.echo(layout.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
