// Resizes + re-compresses every raster image in public/ that exceeds a size threshold.
// Run manually (`node scripts/optimize-images.js`) or via the
// `.github/workflows/optimize-performance.yml` CI job. Idempotent: re-running on an
// already-optimized image is a harmless no-op (it'll just re-encode at the same settings).
import sharp from "sharp";
import { readdir, stat, rename } from "fs/promises";
import path from "path";

const PUBLIC_DIR = new URL("../public/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const MAX_WIDTH = 1600;
const JPEG_QUALITY = 78;
const RASTER_EXT = new Set([".png", ".jpg", ".jpeg"]);

async function main() {
  const files = await readdir(PUBLIC_DIR);
  let totalBefore = 0;
  let totalAfter = 0;

  for (const file of files) {
    const ext = path.extname(file).toLowerCase();
    if (!RASTER_EXT.has(ext)) continue;

    const fullPath = path.join(PUBLIC_DIR, file);
    const { size: before } = await stat(fullPath);
    totalBefore += before;

    const base = file.slice(0, -ext.length);
    const outPath = path.join(PUBLIC_DIR, `${base}.jpg`);

    const img = sharp(fullPath).rotate();
    const meta = await img.metadata();
    if (meta.width && meta.width > MAX_WIDTH) {
      img.resize({ width: MAX_WIDTH });
    }

    await img
      .jpeg({ quality: JPEG_QUALITY, progressive: true, mozjpeg: true })
      .toFile(outPath + ".tmp");
    await rename(outPath + ".tmp", outPath);

    if (outPath !== fullPath) {
      // Extension changed (png -> jpg): caller is responsible for updating any
      // frontmatter/markup references to the old filename, then deleting the old file.
      console.log(`renamed: ${file} -> ${path.basename(outPath)} (update references!)`);
    }

    const { size: after } = await stat(outPath);
    totalAfter += after;
    console.log(
      `${file}: ${(before / 1024).toFixed(1)}KB -> ${(after / 1024).toFixed(1)}KB ` +
        `(${((1 - after / before) * 100).toFixed(1)}% smaller)`
    );
  }

  console.log(
    `\nTOTAL: ${(totalBefore / 1024 / 1024).toFixed(1)}MB -> ${(totalAfter / 1024 / 1024).toFixed(
      1
    )}MB`
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
