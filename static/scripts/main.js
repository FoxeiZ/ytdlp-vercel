let currentUrl = window.location.href;

function humanFileSize(bytes, si = false, dp = 1) {
  const thresh = si ? 1000 : 1024;

  if (Math.abs(bytes) < thresh) {
    return bytes + ' B';
  }

  const units = si
    ? ['kB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB']
    : ['KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB', 'ZiB', 'YiB'];
  let u = -1;
  const r = 10 ** dp;

  do {
    bytes /= thresh;
    ++u;
  } while (Math.round(Math.abs(bytes) * r) / r >= thresh && u < units.length - 1);


  return bytes.toFixed(dp) + ' ' + units[u];
}

function isValidHttpUrl(urlString) {
  try {
    const url = new URL(urlString);
    return url.protocol === 'http:' || url.protocol === 'https:';
  } catch (_) {
    return false;
  }
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function resetDownloadText(setOriginal = true) {
  const downloadText = document.getElementById("download-button")
  downloadText.classList.remove("red")
  downloadText.classList.remove("no-opacity")
  if (setOriginal) {
    downloadText.innerHTML = "download"
  }
}

async function animateDownloadText(afterText = "download", options = { animation: true, isError: false }) {
  const downloadText = document.getElementById("download-button");
  if (options.animation) {
    downloadText.classList.add("no-opacity");
    await sleep(200);
  }
  resetDownloadText(false);

  if (options.isError) {
    downloadText.classList.add("red");
  }
  downloadText.innerHTML = afterText;
  downloadText.classList.remove("no-opacity");
}

async function animateErrorText(afterText) {
  await animateDownloadText(afterText, { isError: true });
}

async function handleSubmit() {
  const input = document.getElementById("url-input");
  const url = input.value;
  const downloadButton = document.getElementById("download-button");

  if (downloadButton.classList.contains("disabled")) {
    return;
  }

  downloadButton.classList.add("disabled");
  try {
    await submit(url);
  } catch (error) {
    animateErrorText(error.message);
  } finally {
    await sleep(2000);
    animateDownloadText("download");
    downloadButton.classList.remove("disabled");
  }
}

async function submit(url) {
  if (!isValidHttpUrl(url)) {
    return
  }
  animateDownloadText("...")
  const response = await fetch(`${currentUrl}/check`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query: url,
      type: document.getElementsByClassName("av-wrapper")[0].getAttribute("data-value"),
      has_ffmpeg: window.WP_ffmpeg !== undefined && window.WP_ffmpeg.loaded
    }),
  });

  if (!response.ok) {
    const errorJson = await response.json();
    window.WP_notifier.warning(errorJson.error);
    return;
  }

  animateDownloadText("downloading...");
  return await response.json()
    .then(async (data) => {
      if (data.needFFmpeg == true) {
        if (!window.WP_ffmpeg.loaded) {
          return "ffmpeg not loaded";
        }
        const params = {
          filename: data.title,
        };

        for (const format of data.requestedFormats) {
          const fileData = format.isPart ? await downloadParts(format) : await window.WP_fetchFile(`${currentUrl}/download?video_id=${format.videoId}`);
          params[`${format.type}Data`] = fileData;
          params[`${format.type}Ext`] = format.ext;
          params[`${format.type}Title`] = format.formatId;
        }
        await ffmpegDownload(params);
        return;
      }

      if (data.isPart == true) {
        return await downloadParts(data)
          .then((blob) => {
            saveAs(blob, data.title + "." + data.ext);
          })
          .catch(() => {
            return "I/O error";
          });
      }
      download(data);
    })
}

function saveAs(blob, filename) {
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
  }, 100);
}

async function parts(bufferList, url, videoId, fileSizeApprox, rangeStart) {
  const postResp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      video_id: videoId,
      range_start: rangeStart,
      filesize_approx: fileSizeApprox
    }),
  })

  const postData = await postResp.json()
  if (postData.status == "finished") {
    return
  }

  const getResp = await fetch(postData.url)
  if (getResp.status == 416) {
    return
  }

  const contentLength = getResp.headers.get("Content-Length")
  const newRangeStart = Number(rangeStart) + Number(contentLength)

  animateDownloadText(`downloading... ${humanFileSize(newRangeStart)}/${humanFileSize(fileSizeApprox)}`, { animation: false })

  arrayBuffer = await getResp.arrayBuffer()
  bufferList.push(arrayBuffer)
  await parts(bufferList, url, videoId, fileSizeApprox, newRangeStart)
}

async function ffmpegDownload({ videoData, videoTitle, videoExt, audioData, audioTitle, audioExt, filename }) {
  const videoName = `${videoTitle}.${videoExt}`;
  const audioName = `${audioTitle}.${audioExt}`;
  const outputName = `${filename}.${videoExt}`;

  videoData = new Uint8Array(await (videoData instanceof Blob ? videoData.arrayBuffer() : Promise.resolve(videoData)));
  audioData = new Uint8Array(await (audioData instanceof Blob ? audioData.arrayBuffer() : Promise.resolve(audioData)));

  const ffmpeg = window.WP_ffmpeg;
  if (ffmpeg === undefined || !ffmpeg.loaded) {
    return Promise.reject(new Error("ffmpeg not loaded"));
  }

  await Promise.all([
    ffmpeg.writeFile(videoName, videoData),
    ffmpeg.writeFile(audioName, audioData),
  ]);

  await ffmpeg.exec([
    "-i",
    videoName,
    "-i",
    audioName,
    "-c:v",
    "copy",
    "-c:a",
    "copy",
    outputName,
  ]);

  const data = await ffmpeg.readFile(outputName);
  const blob = new Blob([data], { type: `video/${videoExt}` });
  saveAs(blob, outputName);

  animateDownloadText("download")
  await Promise.all([
    ffmpeg.deleteFile(videoName),
    ffmpeg.deleteFile(audioName),
    ffmpeg.deleteFile(outputName),
  ]);
}

async function downloadParts(data) {
  const { url = "/api/ytdl/part-download", videoId, fileSizeApprox } = data;
  const bufferList = [];

  await parts(bufferList, url, videoId, fileSizeApprox, 0);

  return new Blob(bufferList, { type: "application/octet-stream" });
}

function download(data) {
  const a = document.createElement("a");
  a.href = `${currentUrl}/download?video_id=${data.videoId}`;
  a.download = data.title + "." + data.ext;
  a.click();
}

function checkInput(inputElement) {
  const input = inputElement.value;
  const downloadButton = document.getElementById("download-button");

  if (input === "") {
    downloadButton.classList.remove("disabled");
    resetDownloadText();
    return;
  }

  if (isValidHttpUrl(input)) {
    downloadButton.classList.remove("disabled");
  } else {
    downloadButton.classList.add("disabled");
  }
}

function videoSwitch() {
  document.getElementsByClassName("av-wrapper")[0].setAttribute("data-value", "video")
  document.getElementById("video-switch").classList.add("selected")
  document.getElementById("audio-switch").classList.remove("selected")
}

function audioSwitch() {
  document.getElementsByClassName("av-wrapper")[0].setAttribute("data-value", "audio")
  document.getElementById("audio-switch").classList.add("selected")
  document.getElementById("video-switch").classList.remove("selected")
}

function toggleModal(name) {
  const modal = document.getElementById(`${name}-modal`)
  modal.classList.toggle("hidden")
  modal.classList.toggle("visible")
}