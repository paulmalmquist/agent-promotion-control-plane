import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const sourceRoot = join(dirname(fileURLToPath(import.meta.url)), "..");

function sourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    return statSync(path).isDirectory() ? sourceFiles(path) : path;
  });
}

describe("transplantable UI contract", () => {
  it("contains no Next.js imports", () => {
    sourceFiles(sourceRoot)
      .filter((path) => /\.tsx?$/.test(path) && !path.includes("__tests__"))
      .forEach((path) => expect(readFileSync(path, "utf8")).not.toMatch(/from\s+["']next\//));
  });

  it("contains no generic icon dependency or forbidden categorical direction", () => {
    const packageJson = readFileSync(join(sourceRoot, "..", "package.json"), "utf8");
    const css = readFileSync(join(sourceRoot, "styles.css"), "utf8");
    expect(packageJson).not.toMatch(/lucide|heroicons|fontawesome|iconify/i);
    expect(css).not.toMatch(/cyan|emerald|violet|green/i);
  });

  it("scopes every component selector beneath the package boundary", () => {
    const css = readFileSync(join(sourceRoot, "styles.css"), "utf8");
    const selectorLines = css
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line.endsWith("{") && !line.startsWith("@"));
    selectorLines.forEach((selector) => {
      expect(selector).toMatch(/^\[data-promotion-control-plane\]/);
    });
  });
});
