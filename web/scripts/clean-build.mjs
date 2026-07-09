import { rm } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const generatedDirs = [join(webDir, ".next"), join(webDir, "out")];

for (const dir of generatedDirs) {
  const resolved = resolve(dir);
  const relativePath = relative(webDir, resolved);
  if (!relativePath || relativePath.startsWith("..") || isAbsolute(relativePath)) {
    throw new Error(`Refusing to remove path outside web directory: ${resolved}`);
  }
  await rm(resolved, { force: true, recursive: true });
}

console.log("Cleaned generated frontend build directories");
