import {
  Color,
  DirectionalLight,
  GridHelper,
  HemisphereLight,
  PerspectiveCamera,
  Scene,
  WebGPURenderer,
} from "three/webgpu";
import { PointerLockControls } from "three/addons/controls/PointerLockControls.js";

import {
  EvidenceStore,
  requireSafeRelativeUrl,
  resolveLocalUrl,
} from "./evidence-store.js";
import { NavigationState } from "./navigation-state.js";
import { PanoramaViewer } from "./panorama-viewer.js";
import { RepresentationController } from "./representation-controller.js";
import { MeshRepresentationLoader } from "./renderers/mesh-loader.js";
import { SplatRepresentationLoader } from "./renderers/splat-loader.js";
import { parseViewerManifest } from "./viewer-manifest.js";

const ui = {
  viewport: document.querySelector("#viewport"),
  enterWalk: document.querySelector("#enter-walk"),
  walkOverlay: document.querySelector("#walk-overlay"),
  modeMesh: document.querySelector("#mode-mesh"),
  modeSplat: document.querySelector("#mode-splat"),
  speed: document.querySelector("#movement-speed"),
  speedValue: document.querySelector("#movement-speed-value"),
  status: document.querySelector("#status"),
  position: document.querySelector("#position"),
  showEvidence: document.querySelector("#show-evidence"),
  evidenceDialog: document.querySelector("#evidence-dialog"),
  closeEvidence: document.querySelector("#close-evidence"),
  evidenceFrame: document.querySelector("#evidence-frame"),
  evidenceMeta: document.querySelector("#evidence-meta"),
  panoramaCanvas: document.querySelector("#panorama-canvas"),
  panoramaStatus: document.querySelector("#panorama-status"),
  showProvenance: document.querySelector("#show-provenance"),
  provenancePanel: document.querySelector("#provenance-panel"),
  closeProvenance: document.querySelector("#close-provenance"),
  provenanceContent: document.querySelector("#provenance-content"),
  fatalError: document.querySelector("#fatal-error"),
};

boot().catch(showFatalError);

async function boot() {
  const manifestUrl = resolveManifestUrl();
  const manifest = parseViewerManifest(await fetchJson(manifestUrl));
  const scene = createScene();
  const camera = new PerspectiveCamera(62, 1, 0.01, 10_000);
  camera.position.fromArray(manifest.initial_position);

  const renderer = new WebGPURenderer({
    canvas: ui.viewport,
    antialias: true,
    forceWebGL: !navigator.gpu,
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  await renderer.init();

  const controls = new PointerLockControls(camera, ui.viewport);
  const navigation = new NavigationState({
    speed: Number(ui.speed.value),
    maxDeltaSeconds: 0.1,
  });
  const representations = new RepresentationController({
    mesh: new MeshRepresentationLoader(scene),
    splat: new SplatRepresentationLoader(scene),
  });

  bindNavigation(controls, navigation);
  bindSpeed(navigation);
  bindResize(renderer, camera);
  bindProvenance(manifest, manifestUrl, controls);

  const evidence = await loadEvidence(manifest, manifestUrl);
  bindEvidence(evidence, manifest, manifestUrl, camera, controls);

  const selectMode = createModeSelector(
    manifest,
    manifestUrl,
    representations,
  );
  bindModeButtons(manifest, selectMode);
  const initialMode = manifest.assetsByMode.mesh ? "mesh" : "splat";
  await selectMode(initialMode);

  ui.enterWalk.disabled = false;
  setStatus(`Run ${manifest.run_id} ready · ${initialMode.toUpperCase()} mode`);
  startRenderLoop(renderer, scene, camera, controls, navigation);
}

function createScene() {
  const scene = new Scene();
  scene.background = new Color(0x071015);
  scene.add(new HemisphereLight(0xd9f4ff, 0x1a2427, 1.25));
  const keyLight = new DirectionalLight(0xffffff, 1.35);
  keyLight.position.set(5, 9, 3);
  scene.add(keyLight);
  const grid = new GridHelper(100, 100, 0x31515b, 0x183039);
  grid.material.transparent = true;
  grid.material.opacity = 0.24;
  scene.add(grid);
  return scene;
}

function bindNavigation(controls, navigation) {
  ui.enterWalk.addEventListener("click", () => controls.lock());
  ui.viewport.addEventListener("click", () => {
    if (!ui.evidenceDialog.open) controls.lock();
  });
  controls.addEventListener("lock", () => {
    ui.walkOverlay.hidden = true;
  });
  controls.addEventListener("unlock", () => {
    navigation.clear();
    if (!ui.evidenceDialog.open) ui.walkOverlay.hidden = false;
  });
  window.addEventListener("keydown", (event) => {
    if (isTypingTarget(event.target)) return;
    navigation.keyDown(event.code);
    if (["KeyW", "KeyA", "KeyS", "KeyD", "KeyQ", "KeyE"].includes(event.code)) {
      event.preventDefault();
    }
  });
  window.addEventListener("keyup", (event) => navigation.keyUp(event.code));
  window.addEventListener("blur", () => navigation.clear());
}

function bindSpeed(navigation) {
  const update = () => {
    navigation.setSpeed(ui.speed.value);
    ui.speedValue.value = `${navigation.speed.toFixed(2)} m/s`;
  };
  ui.speed.addEventListener("input", update);
  update();
}

function bindResize(renderer, camera) {
  const resize = () => {
    const width = Math.max(1, window.innerWidth);
    const height = Math.max(1, window.innerHeight);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };
  window.addEventListener("resize", resize);
  resize();
}

function startRenderLoop(renderer, scene, camera, controls, navigation) {
  let previousTime = performance.now();
  renderer.setAnimationLoop((time) => {
    const deltaSeconds = Math.max(0, (time - previousTime) / 1000);
    previousTime = time;
    if (controls.isLocked) {
      const movement = navigation.movementFor(deltaSeconds);
      camera.updateMatrix();
      controls.moveForward(movement.forward);
      controls.moveRight(movement.right);
      camera.position.y += movement.up;
    }
    ui.position.textContent = ["X", "Y", "Z"]
      .map((axis, index) => `${axis} ${camera.position.getComponent(index).toFixed(2)}`)
      .join(" · ");
    renderer.render(scene, camera);
  });
}

function createModeSelector(manifest, manifestUrl, representations) {
  let requestSerial = 0;
  return async (mode) => {
    const asset = manifest.assetsByMode[mode];
    if (!asset) return;
    const serial = ++requestSerial;
    setModeLoading(true);
    setStatus(`Loading ${mode.toUpperCase()} representation…`);
    try {
      await representations.activate({
        ...asset,
        url: new URL(asset.url, manifestUrl).href,
      });
      if (serial !== requestSerial) return;
      ui.modeMesh.setAttribute("aria-pressed", String(mode === "mesh"));
      ui.modeSplat.setAttribute("aria-pressed", String(mode === "splat"));
      setStatus(`${mode.toUpperCase()} representation ready`);
    } catch (error) {
      if (serial === requestSerial) {
        setStatus(`${mode.toUpperCase()} failed: ${errorMessage(error)}`);
      }
      throw error;
    } finally {
      if (serial === requestSerial) setModeLoading(false, manifest);
    }
  };
}

function bindModeButtons(manifest, selectMode) {
  setModeLoading(false, manifest);
  ui.modeMesh.addEventListener("click", () => selectMode("mesh").catch(() => {}));
  ui.modeSplat.addEventListener("click", () => selectMode("splat").catch(() => {}));
}

function setModeLoading(loading, manifest = null) {
  ui.modeMesh.disabled = loading || (manifest ? !manifest.assetsByMode.mesh : true);
  ui.modeSplat.disabled = loading || (manifest ? !manifest.assetsByMode.splat : true);
}

async function loadEvidence(manifest, manifestUrl) {
  try {
    const payload = await fetchJson(new URL(manifest.evidence_index_url, manifestUrl));
    const store = new EvidenceStore(payload, manifest.coordinate_system);
    ui.showEvidence.disabled = false;
    return store;
  } catch (error) {
    setStatus(`Original evidence unavailable: ${errorMessage(error)}`);
    return null;
  }
}

function bindEvidence(store, manifest, manifestUrl, camera, controls) {
  let panorama = null;
  ui.showEvidence.addEventListener("click", async () => {
    if (!store) return;
    controls.unlock();
    const match = store.nearest(camera.position.toArray());
    const imageUrl = resolveLocalUrl(
      manifest.original_frame_base_url,
      match.source_frame,
      manifestUrl,
    );
    ui.evidenceFrame.textContent = match.physical_frame_id;
    ui.evidenceMeta.textContent =
      `Timestamp ${formatTimestamp(match.timestamp_seconds)} · ` +
      `Nearest distance ${match.distance.toFixed(3)}`;
    ui.panoramaStatus.hidden = false;
    ui.panoramaStatus.textContent = "Loading original capture…";
    ui.evidenceDialog.showModal();
    try {
      panorama ??= new PanoramaViewer(ui.panoramaCanvas);
      await panorama.show(imageUrl);
      ui.panoramaStatus.hidden = true;
    } catch (error) {
      ui.panoramaStatus.hidden = false;
      ui.panoramaStatus.textContent = `Original capture failed: ${errorMessage(error)}`;
    }
  });
  ui.closeEvidence.addEventListener("click", () => ui.evidenceDialog.close());
  ui.evidenceDialog.addEventListener("close", () => {
    panorama?.clear();
    ui.walkOverlay.hidden = false;
  });
}

function bindProvenance(manifest, manifestUrl, controls) {
  let loadPromise = null;
  ui.showProvenance.addEventListener("click", () => {
    controls.unlock();
    ui.provenancePanel.hidden = false;
    loadPromise ??= Promise.all([
      fetchJson(new URL(manifest.run_manifest_url, manifestUrl)),
      fetchJson(new URL(manifest.benchmark_report_url, manifestUrl)),
    ]).then(([run, benchmark]) => {
      ui.provenanceContent.textContent = JSON.stringify(
        {
          viewer: {
            run_id: manifest.run_id,
            input_sha256: manifest.input_sha256,
            coordinate_system: manifest.coordinate_system,
            assets: Object.values(manifest.assetsByMode),
          },
          run_manifest: run,
          benchmark_report: benchmark,
        },
        null,
        2,
      );
    });
    loadPromise.catch((error) => {
      ui.provenanceContent.textContent = `Provenance failed: ${errorMessage(error)}`;
    });
  });
  ui.closeProvenance.addEventListener("click", () => {
    ui.provenancePanel.hidden = true;
  });
}

function resolveManifestUrl() {
  const requested = new URLSearchParams(window.location.search).get("manifest");
  const relativeUrl = requireSafeRelativeUrl(requested || "viewer-manifest.json");
  return new URL(relativeUrl, window.location.href);
}

async function fetchJson(url) {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} for ${url.pathname}`);
  }
  return response.json();
}

function formatTimestamp(seconds) {
  const milliseconds = Math.round(seconds * 1000);
  const hours = Math.floor(milliseconds / 3_600_000);
  const minutes = Math.floor((milliseconds % 3_600_000) / 60_000);
  const wholeSeconds = Math.floor((milliseconds % 60_000) / 1000);
  const remainder = milliseconds % 1000;
  return [hours, minutes, wholeSeconds]
    .map((value) => String(value).padStart(2, "0"))
    .join(":") + `.${String(remainder).padStart(3, "0")}`;
}

function setStatus(message) {
  ui.status.textContent = message;
}

function showFatalError(error) {
  ui.fatalError.hidden = false;
  ui.fatalError.textContent = `Atlas viewer could not start: ${errorMessage(error)}`;
  setStatus("Viewer startup failed");
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

function isTypingTarget(target) {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement;
}
