import { cp, rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = dirname(fileURLToPath(import.meta.url)).replace(/[\\/]scripts$/, "");
const projectRoot = dirname(webDir);
const sourceDir = join(webDir, "out");
const targetDir = join(projectRoot, "web_dist");

await rm(targetDir, { force: true, recursive: true });
await cp(sourceDir, targetDir, { recursive: true });

console.log(`Synced ${sourceDir} -> ${targetDir}`);
