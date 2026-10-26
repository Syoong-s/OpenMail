/* TeleMail-owned offline PDF viewer. Only this trusted module, never PDF scripts, executes. */
import * as pdfjs from "./vendor/build/pdf.mjs";
import { EventBus, PDFViewer, PDFLinkService, PDFFindController } from "./vendor/web/pdf_viewer.mjs";

const status = document.getElementById("status");
const container = document.getElementById("viewport");
const eventBus = new EventBus();
const linkService = new PDFLinkService({ eventBus, externalLinkEnabled: false, ignoreDestinationZoom: true });
const findController = new PDFFindController({ eventBus, linkService });
const viewer = new PDFViewer({ container, viewer: document.getElementById("pages"), eventBus,
  linkService, findController, textLayerMode: 1, annotationMode: 0, maxCanvasPixels: 16777216 });
linkService.setViewer(viewer);
pdfjs.GlobalWorkerOptions.workerSrc = new URL("./vendor/build/pdf.worker.mjs", import.meta.url).href;
const state = { token: location.pathname.split("/")[1], count: 0, index: 0, zoom: 1,
  ready: false, rendered: 0, matches: 0, searchState: 0, error: "" };
let documentTask;
let disposed = false;
let previousQuery = "";

// ==========================================
// Function: Send bounded viewer metadata to the native owner without a privileged document bridge.
// Method: Publish an identity-bound JSON title; PDF content and passwords are never included.
// ==========================================
function publish() {
  if (disposed) return;
  if (viewer.pagesCount) {
    state.count = viewer.pagesCount;
    state.index = viewer.currentPageNumber - 1;
    state.zoom = viewer.currentScale || 1;
  }
  document.title = "TeleMailPDF:" + JSON.stringify(state);
}

// ==========================================
// Function: Execute a finite set of native toolbar operations on the active PDF.
// Method: Validate command types and use PDF.js page, scale and cross-page search APIs.
// ==========================================
function command(value) {
  if (disposed || !state.count || !value || typeof value !== "object") return;
  if (value.action === "page" && Number.isInteger(value.value)) {
    viewer.currentPageNumber = Math.max(1, Math.min(state.count, value.value + 1));
  } else if (value.action === "step" && Number.isInteger(value.value)) {
    viewer.currentPageNumber = Math.max(1, Math.min(state.count, viewer.currentPageNumber + value.value));
  } else if (value.action === "scale" && Number.isFinite(value.value)) {
    viewer.currentScale = Math.max(0.3, Math.min(3, viewer.currentScale * value.value));
  } else if (value.action === "fit") {
    viewer.currentScaleValue = "page-width";
  } else if (value.action === "find" && typeof value.value === "string" && value.value.length <= 2048) {
    const query = value.value;
    eventBus.dispatch("find", { source: viewer, type: query && query === previousQuery ? "again" : "",
      query, caseSensitive: false, entireWord: false, highlightAll: true, findPrevious: false,
      matchDiacritics: false });
    previousQuery = query;
  }
  publish();
}

window.maildeskPdf = Object.freeze({ command, state: () => ({ ...state }) });
eventBus.on("pagesinit", () => { viewer.currentScaleValue = "page-width"; publish(); });
eventBus.on("pagechanging", publish);
eventBus.on("scalechanging", publish);
eventBus.on("pagerendered", event => {
  if (event.error) return fail("PDF 页面渲染失败");
  state.ready = true;
  state.rendered++;
  status.hidden = true;
  publish();
});
eventBus.on("updatefindmatchescount", event => { state.matches = event.matchesCount.total; publish(); });
eventBus.on("updatefindcontrolstate", event => { state.searchState = event.state; publish(); });

// ==========================================
// Function: Show a fixed, non-sensitive error when document loading or rendering fails.
// Method: Keep the native owner informed and avoid inserting exception/PDF strings as HTML.
// ==========================================
function fail(message) {
  if (disposed) return;
  state.error = message;
  status.textContent = message;
  status.hidden = false;
  publish();
}

// ==========================================
// Function: Load PDF bytes and decoding assets exclusively from the capability's local origin.
// Method: Disable evaluation/XFA, use the real PDF.js worker and handle encrypted documents locally.
// ==========================================
async function openDocument() {
  try {
    documentTask = pdfjs.getDocument({ url: "document.pdf", cMapUrl: "vendor/cmaps/", cMapPacked: true,
      standardFontDataUrl: "vendor/standard_fonts/", wasmUrl: "vendor/wasm/", iccUrl: "vendor/iccs/",
      isEvalSupported: false, enableXfa: false, maxImageSize: 33554432, canvasMaxAreaInBytes: 67108864,
      disableRange: true, disableStream: true, useWorkerFetch: true, verbosity: 0 });
    documentTask.onPassword = (update, reason) => {
      const form = document.getElementById("passwordForm");
      const field = document.getElementById("password");
      form.hidden = false;
      document.getElementById("passwordError").textContent = reason === 2 ? "密码不正确，请重试" : "";
      field.focus();
      // ==========================================
      // Function: Provide a password only to the local worker and immediately clear its input field.
      // Method: Consume one form submission without navigation, persistence or native metadata.
      // ==========================================
      form.onsubmit = event => { event.preventDefault(); const password = field.value; field.value = "";
        form.hidden = true; update(password); };
    };
    const pdfDocument = await documentTask.promise;
    if (disposed) { await pdfDocument.destroy(); return; }
    linkService.setDocument(pdfDocument);
    viewer.setDocument(pdfDocument);
    publish();
  } catch {
    fail("PDF 无法读取，请确认文件完整且格式有效");
  }
}

// ==========================================
// Function: Stop worker and page resources when the native tab is retired.
// Method: Destroy the PDF.js loading task on page exit rather than keeping inactive documents live.
// ==========================================
window.addEventListener("pagehide", () => { disposed = true; documentTask?.destroy(); }, { once: true });
window.addEventListener("error", () => fail("PDF 阅读器加载失败"));
window.addEventListener("unhandledrejection", () => fail("PDF 阅读器加载失败"));
publish();
openDocument();
