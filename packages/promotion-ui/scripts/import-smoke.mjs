const promotionUi = await import(new URL("../dist/index.js", import.meta.url));

for (const exportedName of [
  "PromotionShell",
  "createHttpPromotionDataSource",
  "applyPromotionEvent",
  "governedCopyArtifact"
]) {
  if (!(exportedName in promotionUi)) {
    throw new Error(`Built package is missing the ${exportedName} export.`);
  }
}
