import { loadFFmpeg, getFFmpeg, isLoaded, fetchFile } from "./ffmpeg.js";
import { registerNotifyStore } from "./notify.js";

const Logger = {
  verbose: true,
  get log() {
    if (!this.verbose) return () => { };
    const timestamp = new Date().toLocaleTimeString();
    const prefix = `[${timestamp}] [YTDL-APP]`;
    return console.log.bind(console, prefix);
  },
  get info() {
    if (!this.verbose) return () => { };
    const timestamp = new Date().toLocaleTimeString();
    const prefix = `[${timestamp}] [YTDL-APP]`;
    return console.info.bind(console, prefix);
  },
  get warn() {
    const timestamp = new Date().toLocaleTimeString();
    const prefix = `[${timestamp}] [YTDL-APP]`;
    return console.warn.bind(console, prefix);
  },
  get error() {
    const timestamp = new Date().toLocaleTimeString();
    const prefix = `[${timestamp}] [YTDL-APP]`;
    return console.error.bind(console, prefix);
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

// register notify store before alpine init
document.addEventListener("alpine:init", () => {
  registerNotifyStore(Alpine);
});

function ytdlApp() {
  return {
    // -- config ---------------------------------------------------------------
    API_BASE: "/api/ytdl",
    CHUNK_SIZE: 1024 * 1024 * 3,

    // -- reactive state -------------------------------------------------------
    url: "",
    downloadType: "video",
    useFfmpeg: false,
    useMultiThread: false,
    ytdlFormatVideo: "",
    ytdlFormatAudio: "",
    ytdlFormatCustom: "",
    fetchLyrics: false,
    lyricsProvider: "auto",

    isDownloading: false,
    downloadText: "download",
    isError: false,
    noOpacity: false,

    // ffmpeg state
    ffmpegLoading: false,
    ffmpegLoaded: false,

    // modal state
    modals: {
      settings: false,
      about: false,
    },

    // tabs
    settingsTab: 0,

    // changelog
    changelogItems: null,

    // preset data
    videoPresets: [
      {
        title: "Auto (1080p + Audio)",
        value: "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080][ext=mp4]/b",
        description: "Recommended. Best video up to 1080p and best audio, requires FFmpeg.",
      },
      {
        title: "Auto (Best Combined)",
        value: "best*[vcodec!=none][acodec!=none][height<=1080]",
        description: "Best format with both video and audio. Does not require FFmpeg.",
      },
      {
        title: "MP4 (Video Only)",
        value: "bestvideo[ext=mp4]",
        description: "Highest quality MP4 video stream, likely no audio.",
      },
      {
        title: "Custom",
        value: "custom",
        description: "Use a custom format string entered below.",
      },
    ],
    audioPresets: [
      {
        title: "Best Quality (M4A)",
        value: "m4a",
        description: "Highest quality AAC audio. Great for Apple devices.",
      },
      {
        title: "High Compatibility (MP3)",
        value: "mp3",
        description: "Good quality, compatible with almost everything. Requires conversion if not available.",
      },
      {
        title: "Best Quality (Opus)",
        value: "opus",
        description: "Excellent quality in a modern format. Requires conversion if not available.",
      },
      {
        title: "Custom",
        value: "custom",
        description: "Use a custom format string entered below.",
      },
    ],
    lyricsProviders: [
      {
        title: "Auto (Best Available)",
        value: "auto",
        description: "Automatically falls back to find the best synced/unsynced lyrics across all providers.",
      },
      {
        title: "LrcLib",
        value: "lrclib",
        description: "Fetch LRC format lyrics from LrcLib.",
      },
      {
        title: "Shazam",
        value: "shazam",
        description: "Scrape from Shazam.",
      },
      {
        title: "MusixMatch",
        value: "musixmatch",
        description: "Scrape from MusixMatch.",
      },
    ],

    get isValidUrl() {
      return isValidHttpUrl(this.url);
    },

    get activeFormat() {
      return this.downloadType === "video"
        ? this.ytdlFormatVideo
        : this.ytdlFormatAudio;
    },

    get showCustomFormat() {
      return this.activeFormat === "custom";
    },

    get videoFormatDesc() {
      const preset = this.videoPresets.find(p => p.value === this.ytdlFormatVideo);
      return preset ? preset.description : "";
    },

    get audioFormatDesc() {
      const preset = this.audioPresets.find(p => p.value === this.ytdlFormatAudio);
      return preset ? preset.description : "";
    },

    get lyricsProviderDesc() {
      const preset = this.lyricsProviders.find(p => p.value === this.lyricsProvider);
      return preset ? preset.description : "";
    },

    init() {
      Logger.verbose = true;
      Logger.info("Application initializing...");

      this._loadState();

      if (!this.ytdlFormatVideo) this.ytdlFormatVideo = this.videoPresets[0].value;
      if (!this.ytdlFormatAudio) this.ytdlFormatAudio = this.audioPresets[0].value;

      const watchKeys = [
        "downloadType", "useFfmpeg", "useMultiThread",
        "ytdlFormatVideo", "ytdlFormatAudio", "ytdlFormatCustom",
        "fetchLyrics", "lyricsProvider",
      ];
      watchKeys.forEach(key => {
        this.$watch(key, () => this._saveState());
      });

      Logger.info("Initialization complete.");
      this.fetchChangelog();
    },

    _saveState() {
      const settings = {
        useFfmpeg: this.useFfmpeg,
        useMultiThread: this.useMultiThread,
        downloadType: this.downloadType,
        ytdlFormatVideo: this.ytdlFormatVideo,
        ytdlFormatAudio: this.ytdlFormatAudio,
        ytdlFormatCustom: this.ytdlFormatCustom,
        fetchLyrics: this.fetchLyrics,
        lyricsProvider: this.lyricsProvider,
      };
      localStorage.setItem("ytdlAppSettings", JSON.stringify(settings));
      Logger.log("Settings saved to localStorage.", settings);
    },

    _loadState() {
      const raw = localStorage.getItem("ytdlAppSettings");
      if (!raw) return;
      try {
        const s = JSON.parse(raw);
        if (s.useFfmpeg !== undefined) this.useFfmpeg = s.useFfmpeg;
        if (s.useMultiThread !== undefined) this.useMultiThread = s.useMultiThread;
        if (s.downloadType) this.downloadType = s.downloadType;
        if (s.ytdlFormatVideo) this.ytdlFormatVideo = s.ytdlFormatVideo;
        if (s.ytdlFormatAudio) this.ytdlFormatAudio = s.ytdlFormatAudio;
        if (s.ytdlFormatCustom !== undefined) this.ytdlFormatCustom = s.ytdlFormatCustom;
        if (s.fetchLyrics !== undefined) this.fetchLyrics = s.fetchLyrics;
        if (s.lyricsProvider) this.lyricsProvider = s.lyricsProvider;
        Logger.info("Settings loaded from localStorage.", s);
      } catch (e) {
        Logger.error("Failed to parse settings from localStorage.", e);
      }
    },

    async _ensureFFmpeg() {
      if (isLoaded()) return getFFmpeg();

      this.ffmpegLoading = true;
      const notify = Alpine.store("notify");

      try {
        Logger.info(`Loading FFmpeg (multiThread: ${this.useMultiThread})...`);
        const ffmpeg = await notify.async(
          loadFFmpeg({
            multiThread: this.useMultiThread,
            onProgress: ({ progress }) => {
              if (this.isDownloading) {
                const pct = Math.floor(progress * 100);
                this.downloadText = `ffmpeg-ing... ${pct}%`;
              }
            },
          }),
          "FFmpeg loaded",
          (err) => notify.alert(`FFmpeg failed to load: ${err.message}`),
          "FFmpeg loading..."
        );
        this.ffmpegLoaded = true;
        Logger.info("FFmpeg loaded successfully.");
        return ffmpeg;
      } catch (err) {
        Logger.error("Failed to load FFmpeg:", err);
        throw new Error("FFmpeg failed to load");
      } finally {
        this.ffmpegLoading = false;
      }
    },

    async updateDownloadText(text, { animation = true, isError = false } = {}) {
      Logger.log(`Updating download text to: "${text}"`, { animation, isError });
      if (animation) {
        this.noOpacity = true;
        await sleep(200);
      }
      this.noOpacity = false;
      this.isError = isError;
      this.downloadText = text;
    },

    async handleSubmit() {
      if (this.isDownloading) {
        Logger.warn("Download already in progress. handleSubmit aborted.");
        return;
      }

      Logger.info("handleSubmit triggered.");
      this.isDownloading = true;

      try {
        await this.processUrl(this.url);
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
        this.isDownloading = false;
        Logger.info("handleSubmit finished, UI reset.");
      }
    },

    async processUrl(url) {
      if (!isValidHttpUrl(url)) throw new Error("Invalid URL");
      Logger.log(`Starting to process URL: ${url}`);
      await this.updateDownloadText("checking...");

      let formatString = this.activeFormat;
      if (formatString === "custom") {
        formatString = this.ytdlFormatCustom;
      }

      const checkPayload = {
        query: url,
        type: this.downloadType,
        has_ffmpeg: this.useFfmpeg,
        format: formatString,
      };
      Logger.log("Sending request to /check endpoint with payload:", checkPayload);

      const response = await fetch(`${this.API_BASE}/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(checkPayload),
      });
      const data = await response.json();
      Logger.info("Received response from /check:", data);
      if (!response.ok) {
        Alpine.store("notify").warning(data.error);
        throw new Error(data.error);
      }

      if (data.needFFmpeg) {
        Logger.info("Path selected: FFmpeg remuxing.");
        await this._ensureFFmpeg();
        await this.ffmpegDownload(data);
      } else if (data.needsConversion) {
        Logger.info("Path selected: Audio conversion.");
        await this._ensureFFmpeg();
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
      const downloadUrl = `${this.API_BASE}/download?id=${id}`;

      if (!fileSizeApprox || fileSizeApprox <= 0) {
        Logger.warn("fileSizeApprox is unknown. Attempting a single direct fetch.");
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
          start + this.CHUNK_SIZE - 1,
          fileSizeApprox - 1
        );

        Logger.log(`Fetching chunk: bytes=${start}-${end}`);
        await this.updateDownloadText(
          `downloading ${type || ""}... ${humanFileSize(start)}/${humanFileSize(fileSizeApprox)}`,
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

    async fetchAndEmbedLyrics(data, metadataParams) {
      if (!this.fetchLyrics) return;

      const { title, artist, album } = data;

      if (title) {
        Logger.info(`Fetching lyrics for: ${title} - ${artist}`);
        await this.updateDownloadText(`fetching lyrics...`);
        try {
          const endpoint = this.lyricsProvider === "auto"
            ? "/api/lyrics/all"
            : `/api/lyrics/${this.lyricsProvider}`;

          const resp = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title, artist, album })
          });

          if (resp.ok) {
            const data = await resp.json();
            let lyrics = null;

            if (this.lyricsProvider === "auto") {
              if (data.success && data.results) {
                const res = data.results;
                if (res.LrcLibLyricsPlugin?.synced) lyrics = res.LrcLibLyricsPlugin.synced;
                else if (res.ShazamLyricsPlugin?.synced) lyrics = res.ShazamLyricsPlugin.synced;
                else if (res.MusixMatchLyricsPlugin?.synced) lyrics = res.MusixMatchLyricsPlugin.synced;
                else if (res.LrcLibLyricsPlugin?.unsynced) lyrics = res.LrcLibLyricsPlugin.unsynced;
                else if (res.ShazamLyricsPlugin?.unsynced) lyrics = res.ShazamLyricsPlugin.unsynced;
                else if (res.MusixMatchLyricsPlugin?.unsynced) lyrics = res.MusixMatchLyricsPlugin.unsynced;
              }
            } else {
              if (data.success) {
                lyrics = data.synced || data.unsynced;
              }
            }

            if (lyrics) {
              Logger.info("Found lyrics! Embedding into metadata.");
              metadataParams.push("-metadata", `lyrics=${lyrics}`);
            } else {
              Logger.info("No lyrics found from the selected provider(s).");
            }
          }
        } catch (e) {
          Logger.error("Failed to fetch lyrics", e);
        }
      }
    },

    async convertAudio(data) {
      Logger.info("Starting audio conversion process.");
      const ffmpeg = getFFmpeg();
      const inputFilename = `input.${data.sourceExt}`;
      const outputFilename = sanitizeFilename(`${data.title}.${data.ext}`);

      try {
        const fileBlob = await this._fetchFile(data);
        const fileBuffer = await fileBlob.arrayBuffer();

        Logger.log(`Writing source audio to virtual FS as "${inputFilename}"`);
        await ffmpeg.writeFile(inputFilename, new Uint8Array(fileBuffer));

        let metadataParams = data.metadata ? data.metadata.flat() : [];
        await this.fetchAndEmbedLyrics(data, metadataParams);

        await this.updateDownloadText(`converting to ${data.ext}...`);
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
      const ffmpeg = getFFmpeg();
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

        let metadataParams = data.metadata ? data.metadata.flat() : [];
        await this.fetchAndEmbedLyrics(data, metadataParams);

        await this.updateDownloadText("merging...");
        const outputFilename = sanitizeFilename(`${data.title}.${data.ext}`);
        filesToDelete.push(outputFilename);
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

    async fetchChangelog() {
      try {
        const response = await fetch(`${this.API_BASE}/changelog`);
        if (!response.ok) throw new Error("Network response was not ok");
        this.changelogItems = await response.json();
      } catch (error) {
        Logger.error("Failed to fetch changelog:", error);
        this.changelogItems = [];
      }
    },
  };
}

window.ytdlApp = ytdlApp;
