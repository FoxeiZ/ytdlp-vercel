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

function isValidHttpUrl(string) {
  let url;

  try {
    url = new URL(string);
  } catch (_) {
    return false;
  }

  return url.protocol === "http:" || url.protocol === "https:";
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

function submitWrapper() {
  const url = document.getElementById('url-input').value
  const downloadBtn = document.getElementById("download-button");
  if (downloadBtn.classList.contains("disabled")) {
    return;
  }
  downloadBtn.classList.add("disabled");
  submit(url)
    .then(async (errorMsg) => {
      if (errorMsg != undefined) {
        animateErrorText(errorMsg);
      }
    })
    .finally(() => {
      sleep(2000).then(() => {
        animateDownloadText("download");
        downloadBtn.classList.remove("disabled");
      });
    });
}

async function submit(url) {
  if (!isValidHttpUrl(url)) {
    return
  }
  animateDownloadText("...")
  const response = await fetch("/api/ytdl/check", {
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
      if (data.needs_ffmpeg == true) {
        if (!window.WP_ffmpeg.loaded) {
          return "ffmpeg not loaded";
        }
        const params = {
          filename: data.title,
        };

        for (const format of data.requested_formats) {
          const fileData = format.is_part ? await partsDownload(format) : await window.WP_fetchFile(`/api/ytdl/download?video_id=${format.video_id}`);
          params[`${format.type}Data`] = fileData;
          params[`${format.type}Ext`] = format.ext;
          params[`${format.type}Title`] = format.format_id;
        }
        await ffmpegDownload(params);
        return;
      }

      if (data.is_part == true) {
        return await partsDownload(data)
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

async function parts(bufferList, url, video_id, filesize_approx, range_start) {
  const postResp = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      video_id: video_id,
      range_start: range_start,
      filesize_approx: filesize_approx
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
  const new_range_start = Number(range_start) + Number(contentLength)

  animateDownloadText(`downloading... ${humanFileSize(new_range_start)}/${humanFileSize(filesize_approx)}`, { animation: false })

  arrayBuffer = await getResp.arrayBuffer()
  bufferList.push(arrayBuffer)
  await parts(bufferList, url, video_id, filesize_approx, new_range_start)
}

async function ffmpegDownload({ filename, videoData, videoTitle, videoExt, audioData, audioTitle, audioExt }) {
  const videoName = videoTitle + "." + videoExt
  const audioName = audioTitle + "." + audioExt
  const outputName = filename + "." + videoExt

  if (videoData.constructor === Blob) {
    videoData = new Uint8Array(await videoData.arrayBuffer());
  }
  if (audioData.constructor === Blob) {
    audioData = new Uint8Array(await audioData.arrayBuffer());
  }

  animateDownloadText(`ffmpeg-ing...`)

  const ffmpeg = window.WP_ffmpeg;
  if (ffmpeg === undefined || !ffmpeg.loaded) {
    animateErrorText("ffmpeg not loaded")
    return;
  }

  await Promise.all([
    ffmpeg.writeFile(
      videoName,
      videoData
    ),
    ffmpeg.writeFile(
      audioName,
      audioData
    ),
  ])

  await ffmpeg.exec(
    [
      "-i",
      videoName,
      "-i",
      audioName,
      "-c:v",
      "copy",
      "-c:a",
      "copy",
      outputName
    ],
  );
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

async function partsDownload(data) {
  const url = data.url || "/api/ytdl/part-download";
  const bufferList = [];
  const video_id = data.video_id;
  const filesize_approx = data.filesize_approx;

  await parts(bufferList, url, video_id, filesize_approx, 0);
  const blob = new Blob(bufferList, { type: "application/octet-stream" });
  return blob;
}

function download(data) {
  const a = document.createElement("a");
  a.href = `/api/ytdl/download?video_id=${data.video_id}`;
  a.download = data.title + "." + data.ext;
  a.click();
}

function checkInput(input) {
  const downloadBtn = document.getElementById("download-button")
  if (input.value == "") {
    downloadBtn.classList.remove("disabled")
    resetDownloadText()
    return
  }

  if (isValidHttpUrl(input.value)) {
    downloadBtn.classList.remove("disabled")
  } else {
    downloadBtn.classList.add("disabled")
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

function togglePopup(name) {
  const popup = document.getElementById(`${name}-popup`)
  popup.classList.toggle("hidden")
  popup.classList.toggle("visible")
}