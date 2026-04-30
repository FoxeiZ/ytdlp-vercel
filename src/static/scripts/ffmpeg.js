import { FFmpeg } from "https://cdn.jsdelivr.net/npm/@ffmpeg/ffmpeg@0.12.15/+esm";
import {
  fetchFile,
  toBlobURL,
} from "https://cdn.jsdelivr.net/npm/@ffmpeg/util@0.12.2/+esm";

const CORE_VERSION = "0.12.10";
const CDN_BASE = "https://cdn.jsdelivr.net/npm";

const CORE_URLS = {
  single: `${CDN_BASE}/@ffmpeg/core@${CORE_VERSION}/dist/esm`,
  multi: `${CDN_BASE}/@ffmpeg/core-mt@${CORE_VERSION}/dist/esm`,
};

let ffmpeg = null;
let currentMode = null;

function createFFmpeg() {
  if (ffmpeg) {
    ffmpeg.terminate();
  }
  ffmpeg = new FFmpeg();
  return ffmpeg;
}

async function loadFFmpeg({ multiThread = false, onLog, onProgress } = {}) {
  const mode = multiThread ? "multi" : "single";

  if (ffmpeg?.loaded && currentMode === mode) {
    return ffmpeg;
  }

  createFFmpeg();

  if (onLog) ffmpeg.on("log", onLog);
  if (onProgress) ffmpeg.on("progress", onProgress);

  const baseURL = CORE_URLS[mode];

  // convert to blob to bypass cross-origin worker block
  const classWorkerBlob = new Blob(
    [`import "${CDN_BASE}/@ffmpeg/ffmpeg@0.12.15/dist/esm/worker.js";`],
    { type: "text/javascript" }
  );
  const classWorkerURL = URL.createObjectURL(classWorkerBlob);

  const loadConfig = {
    classWorkerURL,
    coreURL: await toBlobURL(`${baseURL}/ffmpeg-core.js`, "text/javascript"),
    wasmURL: await toBlobURL(
      `${baseURL}/ffmpeg-core.wasm`,
      "application/wasm"
    ),
  };

  if (multiThread) {
    loadConfig.workerURL = await toBlobURL(
      `${baseURL}/ffmpeg-core.worker.js`,
      "text/javascript"
    );
  }

  await ffmpeg.load(loadConfig);
  currentMode = mode;
  return ffmpeg;
}

function getFFmpeg() {
  return ffmpeg;
}

function isLoaded() {
  return ffmpeg?.loaded ?? false;
}

function terminate() {
  if (ffmpeg) {
    ffmpeg.terminate();
    ffmpeg = null;
    currentMode = null;
  }
}

export { loadFFmpeg, getFFmpeg, isLoaded, terminate, fetchFile };
