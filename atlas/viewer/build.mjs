import { copyFile, mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { build } from "esbuild";

const viewerRoot = path.dirname(fileURLToPath(import.meta.url));
const outputRoot = path.join(viewerRoot, "dist");

await rm(outputRoot, { recursive: true, force: true });
await mkdir(path.join(outputRoot, "licenses"), { recursive: true });
await Promise.all([
  copyFile(path.join(viewerRoot, "index.html"), path.join(outputRoot, "index.html")),
  copyFile(path.join(viewerRoot, "styles.css"), path.join(outputRoot, "styles.css")),
  copyFile(
    path.join(viewerRoot, "node_modules", "three", "LICENSE"),
    path.join(outputRoot, "licenses", "three-MIT.txt"),
  ),
]);

await build({
  entryPoints: [path.join(viewerRoot, "src", "app.js")],
  outfile: path.join(outputRoot, "app.js"),
  bundle: true,
  format: "esm",
  platform: "browser",
  target: ["es2022"],
  minify: true,
  legalComments: "linked",
  logLevel: "info",
});
