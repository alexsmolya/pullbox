import { readFileSync, appendFileSync } from "node:fs";

const [path] = process.argv.slice(2);

if (!path) {
  console.error("usage: node scripts/ensure-final-newline.mjs <path>");
  process.exit(2);
}

const buffer = readFileSync(path);
if (buffer.length > 0 && buffer[buffer.length - 1] !== 0x0a) {
  appendFileSync(path, "\n");
}
