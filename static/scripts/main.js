const Logger = {
  verbose: true,
  _log(level, ...args) {
    if (["log", "info"].includes(level) && !this.verbose) return;
    const timestamp = new Date().toLocaleTimeString();
    const prefix = `[${timestamp}] [YTDL-APP]`;
    console[level](prefix, ...args);
  },
  log(...args) {
    this._log("log", ...args);
  },
  info(...args) {
    this._log("info", ...args);
  },
  warn(...args) {
    this._log("warn", ...args);
  },
  error(...args) {
    this._log("error", ...args);
  },
};

function humanFileSize(bytes, si = false, dp = 1) {
  const thresh = si ? 1000 : 1024;
  if (Math.abs(bytes) < thresh) return bytes + " B";
  const units = si
    ? ["kB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"]
    : ["KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"];
  let u = -1;
  const r = 10 ** dp;
  do {
    bytes /= thresh;
    ++u;
  } while (
    Math.round(Math.abs(bytes) * r) / r >= thresh &&
    u < units.length - 1
  );
  return bytes.toFixed(dp) + " " + units[u];
}

function isValidHttpUrl(urlString) {
  try {
    const url = new URL(urlString);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch (_) {
    return false;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function saveAs(blob, filename) {
  Logger.info(
    `Triggering download for blob of size ${blob.size} as "${filename}"`
  );
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.style.display = "none";
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
    Logger.log("Cleaned up blob URL.");
  }, 100);
}

function sanitizeFilename(name) {
  const sanitized = name.replace(/[<>:"/\\|?*\x00-\x1F]/g, "");
  if (sanitized !== name)
    Logger.log(`Sanitized filename from "${name}" to "${sanitized}"`);
  return sanitized;
}

const YtdlApp = {
  config: {
    API_BASE: "/api/ytdl",
    CHUNK_SIZE: 1024 * 1024 * 3,
    verbose: true,
  },
  ui: {
    urlInput: null,
    downloadButton: null,
    avWrapper: null,
    videoSwitch: null,
    audioSwitch: null,
    useFfmpeg: null,
    ytdlFormatVideo: null,
    ytdlFormatAudio: null,
    ytdlFormatCustom: null,
    formatSelectorVideo: null,
    formatSelectorAudio: null,
    customFormatInputWrapper: null,
  },
  state: {
    isDownloading: false,
    useFfmpeg: false,
    ytdlFormatVideo: "",
    ytdlFormatAudio: "",
    ytdlFormatCustom: "",
  },

  init() {
    Logger.verbose = this.config.verbose;
    Logger.info("Application initializing...");
    Object.assign(this.ui, {
      urlInput: document.getElementById("url-input"),
      downloadButton: document.getElementById("download-button"),
      avWrapper: document.getElementsByClassName("av-wrapper")[0],
      videoSwitch: document.getElementById("video-switch"),
      audioSwitch: document.getElementById("audio-switch"),
      useFfmpeg: document.getElementById("use-ffmpeg"),
      ytdlFormatVideo: document.getElementById("ytdl-fsl-video"),
      ytdlFormatAudio: document.getElementById("ytdl-fsl-audio"),
      ytdlFormatCustom: document.getElementById("ytdl-fsl-custom"),
      formatSelectorVideo: document.getElementById("format-selector-video"),
      formatSelectorAudio: document.getElementById("format-selector-audio"),
      customFormatInputWrapper: document.getElementById(
        "custom-format-input-wrapper"
      ),
    });

    this.state.ytdlFormatVideo = this.ui.ytdlFormatVideo.value;
    this.state.ytdlFormatAudio = this.ui.ytdlFormatAudio.value;

    this.ui.downloadButton.addEventListener("click", () => this.handleSubmit());
    this.ui.urlInput.addEventListener("input", () => this.checkInput());
    this.ui.videoSwitch.addEventListener("click", () =>
      this.setDownloadType("video")
    );
    this.ui.audioSwitch.addEventListener("click", () =>
      this.setDownloadType("audio")
    );

    document
      .getElementById("open-settings-modal")
      .addEventListener("click", () => this.toggleModal("settings-modal"));
    document
      .getElementById("open-about-modal")
      .addEventListener("click", () => this.toggleModal("about-modal"));
    document
      .getElementById("open-donate-modal")
      .addEventListener("click", () => this.toggleModal("about-modal"));

    document.querySelectorAll(".js-modal-close").forEach((button) => {
      button.addEventListener("click", (event) => {
        const modal = event.target.closest(".modal");
        if (modal) this.toggleModal(modal.id);
      });
    });

    this.ui.useFfmpeg.addEventListener("change", (e) => {
      this.state.useFfmpeg = e.target.checked;
      Logger.info(`State updated: useFfmpeg is now ${this.state.useFfmpeg}`);
    });

    const setupFormatListener = (selectElement, stateKey) => {
      selectElement.addEventListener("change", (e) => {
        const selectedOption = e.target.options[e.target.selectedIndex];
        this.state[stateKey] = e.target.value;
        document.getElementById(`${e.target.id}-desc`).textContent =
          selectedOption.getAttribute("data-desc");
        this._updateCustomFormatVisibility();
        Logger.log(
          `State updated: ${stateKey} is now "${this.state[stateKey]}"`
        );
      });
    };
    setupFormatListener(this.ui.ytdlFormatVideo, "ytdlFormatVideo");
    setupFormatListener(this.ui.ytdlFormatAudio, "ytdlFormatAudio");

    this.ui.ytdlFormatCustom.addEventListener("input", (e) => {
      this.state.ytdlFormatCustom = e.target.value;
    });

    document.querySelectorAll(".tabs-container").forEach((tabsContainer) => {
      const tabButtons = tabsContainer.querySelectorAll(".tab-button");
      const tabPanes = tabsContainer.querySelectorAll(".tab-pane");
      tabButtons.forEach((button) => {
        button.addEventListener("click", () => {
          const tabIndex = button.getAttribute("data-tab");
          tabButtons.forEach((btn) => btn.classList.remove("active"));
          button.classList.add("active");
          tabPanes.forEach((pane) => pane.classList.remove("active"));
          tabPanes[tabIndex].classList.add("active");
        });
      });
    });

    Logger.info("Initialization complete.");
  },

  async updateDownloadText(
    text,
    options = { animation: true, isError: false }
  ) {
    Logger.log(`Updating download text to: "${text}"`, options);
    const { animation, isError } = options;
    if (animation) {
      this.ui.downloadButton.classList.add("no-opacity");
      await sleep(200);
    }
    this.ui.downloadButton.classList.remove("red", "no-opacity");
    if (isError) this.ui.downloadButton.classList.add("red");
    this.ui.downloadButton.innerHTML = text;
  },

  toggleModal(modalId) {
    Logger.log(`Toggling modal: ${modalId}`);
    const modal = document.getElementById(modalId);
    if (modal) {
      modal.classList.toggle("hidden");
      modal.classList.toggle("visible");
    } else {
      Logger.warn(`Modal with ID "${modalId}" not found.`);
    }
  },

  async handleSubmit() {
    if (this.state.isDownloading) {
      Logger.warn("Download already in progress. handleSubmit aborted.");
      return;
    }

    Logger.info("handleSubmit triggered.");
    this.state.isDownloading = true;
    this.ui.downloadButton.classList.add("disabled");

    try {
      await this.processUrl(this.ui.urlInput.value);
      Logger.info("Processing finished successfully.");
    } catch (error) {
      Logger.error("An unexpected error occurred in handleSubmit:", error);
      this.updateDownloadText(error.message || "Client error", {
        isError: true,
        animation: true,
      });
    } finally {
      await sleep(2000);
      this.updateDownloadText("download", { animation: true });
      this.state.isDownloading = false;
      this.checkInput();
      Logger.info("handleSubmit finished, UI reset.");
    }
  },

  async processUrl(url) {
    if (!isValidHttpUrl(url)) throw new Error("Invalid URL");
    Logger.log(`Starting to process URL: ${url}`);
    await this.updateDownloadText("checking...");

    const downloadType = this.ui.avWrapper.getAttribute("data-value");
    let formatString =
      downloadType === "video"
        ? this.state.ytdlFormatVideo
        : this.state.ytdlFormatAudio;
    if (formatString === "custom") {
      formatString = this.state.ytdlFormatCustom;
    }

    const checkPayload = {
      query: url,
      type: downloadType,
      has_ffmpeg: this.state.useFfmpeg,
      format: formatString,
    };
    Logger.log(
      "Sending request to /check endpoint with payload:",
      checkPayload
    );

    const response = await fetch(`${this.config.API_BASE}/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(checkPayload),
    });
    const data = await response.json();
    Logger.info("Received response from /check:", data);
    if (!response.ok) {
      window.WP_notifier.warning(data.error);
      throw new Error(data.error);
    }

    if (data.needFFmpeg) {
      Logger.info("Path selected: FFmpeg remuxing.");
      if (!window.WP_ffmpeg?.loaded) throw new Error("FFmpeg not loaded");
      await this.ffmpegDownload(data);
    } else if (data.needsConversion) {
      Logger.info("Path selected: Audio conversion.");
      if (!window.WP_ffmpeg?.loaded) throw new Error("FFmpeg not loaded");
      await this.convertAudio(data);
    } else {
      const sanitizedFilename = sanitizeFilename(`${data.title}.${data.ext}`);
      Logger.info("Path selected: Ranged download.");
      const blob = await this._fetchFile(data);
      saveAs(blob, sanitizedFilename);
    }
  },

  async _fetchFile(formatData) {
    const { id, fileSizeApprox, type } = formatData;
    Logger.log(
      `Fetching file for format type "${type || "N/A"}" using id: ${id}`,
      formatData
    );
    const downloadUrl = `${this.config.API_BASE}/download?id=${id}`;

    if (!fileSizeApprox || fileSizeApprox <= 0) {
      Logger.warn(
        "fileSizeApprox is unknown. Attempting a single direct fetch."
      );
      await this.updateDownloadText(`downloading ${type || ""}...`);
      const response = await fetch(downloadUrl);
      if (!response.ok)
        throw new Error(
          `Download failed: ${response.status} ${await response.text()}`
        );
      return response.blob();
    }

    Logger.log("Fetching file using ranged requests.");
    const chunks = [];
    let downloadedBytes = 0;
    while (downloadedBytes < fileSizeApprox) {
      const start = downloadedBytes;
      const end = Math.min(
        start + this.config.CHUNK_SIZE - 1,
        fileSizeApprox - 1
      );

      Logger.log(`Fetching chunk: bytes=${start}-${end}`);
      await this.updateDownloadText(
        `downloading ${type || ""}... ${humanFileSize(start)}/${humanFileSize(
          fileSizeApprox
        )}`,
        { animation: false }
      );

      const rangeResponse = await fetch(downloadUrl, {
        headers: { Range: `bytes=${start}-${end}` },
      });
      if (rangeResponse.status !== 206)
        throw new Error(
          `Server error on range request: ${rangeResponse.status}`
        );

      const chunk = await rangeResponse.arrayBuffer();
      chunks.push(chunk);
      downloadedBytes += chunk.byteLength;
      Logger.log(
        `Chunk received. Size: ${chunk.byteLength}. Total downloaded: ${downloadedBytes}`
      );
    }

    const blob = new Blob(chunks, { type: "application/octet-stream" });
    Logger.info(`All chunks received. Final blob size: ${blob.size}`);
    return blob;
  },

  async convertAudio(data) {
    Logger.info("Starting audio conversion process.");
    const ffmpeg = window.WP_ffmpeg;
    const inputFilename = `input.${data.sourceExt}`;
    const outputFilename = sanitizeFilename(`${data.title}.${data.ext}`);

    try {
      const fileBlob = await this._fetchFile(data);
      const fileBuffer = await fileBlob.arrayBuffer();

      Logger.log(`Writing source audio to virtual FS as "${inputFilename}"`);
      await ffmpeg.writeFile(inputFilename, new Uint8Array(fileBuffer));

      await this.updateDownloadText(`converting to ${data.ext}...`);
      const metadataParams = data.metadata ? data.metadata.flat() : [];
      const execParams = [
        "-i",
        inputFilename,
        ...metadataParams,
        outputFilename,
      ];
      Logger.info(
        "Executing FFmpeg command:",
        `ffmpeg ${execParams.join(" ")}`
      );
      await ffmpeg.exec(execParams);
      Logger.info("FFmpeg conversion complete.");

      const convertedData = await ffmpeg.readFile(outputFilename);
      Logger.log(
        `Reading converted file from virtual FS. Size: ${convertedData.length}`
      );
      const blob = new Blob([convertedData], { type: `audio/${data.ext}` });
      saveAs(blob, outputFilename);
    } finally {
      await this.updateDownloadText(`cleaning up...`);
      try {
        await ffmpeg.deleteFile(inputFilename);
        await ffmpeg.deleteFile(outputFilename);
        Logger.log("Cleaned up FFmpeg virtual files.");
      } catch (e) {
        Logger.warn(`Could not delete temp files`, e);
      }
    }
  },

  async ffmpegDownload(data) {
    Logger.info("Starting FFmpeg download process.");
    const ffmpeg = window.WP_ffmpeg;
    const filesToDelete = [];
    const remuxParams = {};

    try {
      Logger.info(
        `Starting concurrent download of ${data.requestedFormats.length} streams.`
      );

      await this.updateDownloadText(`downloading streams...`);
      const downloadPromises = data.requestedFormats.map(async (format) => {
        Logger.log(`[Concurrent] Preparing to download format: ${format.type}`);
        const fileBlob = await this._fetchFile(format);
        const fileBuffer = await fileBlob.arrayBuffer();
        const safeInputName = sanitizeFilename(
          `${format.formatId}.${format.ext}`
        );
        filesToDelete.push(safeInputName);
        Logger.log(
          `[Concurrent] Writing ${format.type} data to virtual FS as "${safeInputName}"`
        );

        await ffmpeg.writeFile(safeInputName, new Uint8Array(fileBuffer));
        remuxParams[`${format.type}Name`] = safeInputName;
        Logger.log(
          `[Concurrent] Finished writing "${safeInputName}" to virtual FS.`
        );
      });

      await Promise.all(downloadPromises);
      Logger.info(
        "All streams have been downloaded and written to the virtual FS."
      );
      await this.updateDownloadText("merging...");
      const outputFilename = sanitizeFilename(`${data.title}.${data.ext}`);
      filesToDelete.push(outputFilename);
      const metadataParams = data.metadata ? data.metadata.flat() : [];
      const execParams = [
        "-i",
        remuxParams.videoName,
        "-i",
        remuxParams.audioName,
        ...metadataParams,
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        outputFilename,
      ];
      Logger.info(
        "Executing FFmpeg command:",
        `ffmpeg ${execParams.join(" ")}`
      );
      await ffmpeg.exec(execParams);
      Logger.info("FFmpeg execution complete.");

      const mergedData = await ffmpeg.readFile(outputFilename);
      Logger.log(
        `Reading merged file from virtual FS. Size: ${mergedData.length}`
      );
      const blob = new Blob([mergedData], { type: `video/${data.ext}` });
      saveAs(blob, outputFilename);
    } finally {
      await this.updateDownloadText(`cleaning up...`);
      Logger.log("Cleaning up FFmpeg virtual files:", filesToDelete);
      for (const file of filesToDelete) {
        try {
          await ffmpeg.deleteFile(file);
          Logger.log(`Deleted temp file: ${file}`);
        } catch (e) {
          Logger.warn(`Could not delete temp file: ${file}`, e);
        }
      }
    }
  },

  checkInput() {
    const isValid = isValidHttpUrl(this.ui.urlInput.value);
    if (isValid && !this.state.isDownloading)
      this.ui.downloadButton.classList.remove("disabled");
    else this.ui.downloadButton.classList.add("disabled");
  },

  _updateFormatSelectorVisibility() {
    const downloadType = this.ui.avWrapper.getAttribute("data-value");
    if (downloadType === "video") {
      this.ui.formatSelectorVideo.classList.remove("hidden-by-js");
      this.ui.formatSelectorAudio.classList.add("hidden-by-js");
    } else {
      this.ui.formatSelectorVideo.classList.add("hidden-by-js");
      this.ui.formatSelectorAudio.classList.remove("hidden-by-js");
    }
    this._updateCustomFormatVisibility();
  },

  _updateCustomFormatVisibility() {
    const downloadType = this.ui.avWrapper.getAttribute("data-value");
    const currentFormat =
      downloadType === "video"
        ? this.state.ytdlFormatVideo
        : this.state.ytdlFormatAudio;
    if (currentFormat === "custom") {
      this.ui.customFormatInputWrapper.classList.remove("hidden-by-js");
    } else {
      this.ui.customFormatInputWrapper.classList.add("hidden-by-js");
    }
  },

  setDownloadType(type) {
    Logger.log(`Setting download type to: ${type}`);
    this.ui.avWrapper.setAttribute("data-value", type);
    if (type === "video") {
      this.ui.videoSwitch.classList.add("selected");
      this.ui.audioSwitch.classList.remove("selected");
    } else {
      this.ui.audioSwitch.classList.add("selected");
      this.ui.videoSwitch.classList.remove("selected");
    }
    this._updateFormatSelectorVisibility();
  },
};

document.addEventListener("DOMContentLoaded", () => YtdlApp.init());
