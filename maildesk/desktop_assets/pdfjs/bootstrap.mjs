// ==========================================
// Function: Report engine/module startup failures instead of leaving an indefinite PDF placeholder.
// Method: Load only the bundled viewer and publish fixed identity-bound metadata on import failure.
// ==========================================
try {
  await import("./viewer.mjs");
} catch {
  const error = "PDF 阅读器加载失败，请检查应用文件是否完整";
  document.getElementById("status").textContent = error;
  document.title = "TeleMailPDF:" + JSON.stringify({ token: location.pathname.split("/")[1],
    count: 0, index: 0, zoom: 1, ready: false, rendered: 0, matches: 0, searchState: 0, error });
}
