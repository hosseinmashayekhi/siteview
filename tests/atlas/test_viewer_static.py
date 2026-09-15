import json
from pathlib import Path


VIEWER = Path(__file__).parents[2] / "atlas" / "viewer"


def test_viewer_page_exposes_free_walk_modes_evidence_and_provenance():
    html = (VIEWER / "index.html").read_text(encoding="utf-8")

    for required_id in (
        'id="viewport"',
        'id="enter-walk"',
        'id="mode-mesh"',
        'id="mode-splat"',
        'id="movement-speed"',
        'id="show-evidence"',
        'id="evidence-dialog"',
        'id="panorama-canvas"',
        'id="provenance-panel"',
    ):
        assert required_id in html
    assert "Content-Security-Policy" in html
    assert 'src="./app.js"' in html
    assert "https://" not in html


def test_app_keeps_navigation_evidence_and_renderers_on_separate_boundaries():
    app = (VIEWER / "src" / "app.js").read_text(encoding="utf-8")
    assert './navigation-state.js' in app
    assert './evidence-store.js' in app
    assert './representation-controller.js' in app
    assert './renderers/mesh-loader.js' in app
    assert './renderers/splat-loader.js' in app
    assert './panorama-viewer.js' in app

    mesh = (VIEWER / "src" / "renderers" / "mesh-loader.js").read_text(
        encoding="utf-8"
    )
    splat = (VIEWER / "src" / "renderers" / "splat-loader.js").read_text(
        encoding="utf-8"
    )
    assert "GLTFLoader" in mesh
    assert "GaussianSplatPLYLoader" in splat
    assert "GaussianSplat" in splat
    assert "navigation" not in mesh.lower()
    assert "evidence" not in splat.lower()


def test_viewer_dependencies_and_build_are_exactly_pinned():
    package = json.loads((VIEWER / "package.json").read_text(encoding="utf-8"))

    assert package["private"] is True
    assert package["type"] == "module"
    assert package["dependencies"] == {"three": "0.186.0"}
    assert package["devDependencies"] == {"esbuild": "0.28.2"}
    assert package["scripts"]["test"] == "node --test ../../tests/atlas/viewer/*.test.mjs"
    assert package["scripts"]["build"] == "node build.mjs"


def test_three_viewer_license_and_version_are_recorded():
    third_party = (
        Path(__file__).parents[2] / "docs" / "atlas" / "THIRD_PARTY.md"
    ).read_text(encoding="utf-8")

    assert "Three.js r186" in third_party
    assert "MIT" in third_party
    assert "GaussianSplatPLYLoader" in third_party


def test_python_package_keeps_viewer_source_for_server_builds():
    pyproject = (Path(__file__).parents[2] / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    assert '"atlas.viewer"' in pyproject
    assert '"src/*.js"' in pyproject
    assert '"src/renderers/*.js"' in pyproject
    assert '"package-lock.json"' in pyproject
