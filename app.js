/* ──────────────────────────────────────────────────────────────
   YouTube Downloader — App Logic
   ────────────────────────────────────────────────────────────── */

// ─── State ───────────────────────────────────────────────────────
let currentVideoInfo = null;
let currentMode = "video";        // "video" | "audio"
let activeDownloadId = null;
let activeEventSource = null;
let ffmpegAvailable = false;

// ─── Init ─────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  // Apply saved theme
  const saved = localStorage.getItem("yt_theme") || "dark";
  applyTheme(saved);
  // Check ffmpeg
  fetch("/api/system")
    .then(r => r.json())
    .then(data => {
      ffmpegAvailable = data.ffmpeg;
      updateFfmpegWarning();
    })
    .catch(() => {});
});

// ─── Theme ───────────────────────────────────────────────────────
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("yt_theme", theme);
  const icon  = document.getElementById("themeIcon");
  const label = document.getElementById("themeLabel");
  if (theme === "dark") { icon.textContent = "☀️"; label.textContent = "Light"; }
  else                  { icon.textContent = "🌙"; label.textContent = "Dark";  }
}

document.getElementById("themeToggle").addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme");
  applyTheme(current === "dark" ? "light" : "dark");
});

// ─── URL Input ───────────────────────────────────────────────────
function onUrlInput() {
  hideError();
}

// ─── Drag and Drop ───────────────────────────────────────────────
function handleDragOver(e) {
  e.preventDefault();
  document.getElementById("urlInputWrap").classList.add("drag-over");
}
function handleDragLeave() {
  document.getElementById("urlInputWrap").classList.remove("drag-over");
}
function handleDrop(e) {
  e.preventDefault();
  document.getElementById("urlInputWrap").classList.remove("drag-over");
  const text = e.dataTransfer.getData("text/plain") ||
               e.dataTransfer.getData("text/uri-list") || "";
  if (text) {
    document.getElementById("urlInput").value = text.trim();
    analyzeUrl();
  }
}

// ─── Analyze ─────────────────────────────────────────────────────
async function analyzeUrl() {
  const url = document.getElementById("urlInput").value.trim();
  if (!url) { showError("Please paste a YouTube URL first."); return; }

  setAnalyzeLoading(true);
  hideError();
  hideSection("videoInfoSection");
  hideSection("downloadSection");
  hideSection("progressSection");
  hideSection("successSection");
  hideDividers();

  try {
    const res  = await fetch("/api/info", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();

    if (!res.ok) { showError(data.error || "Failed to fetch video info."); return; }

    currentVideoInfo = data;
    renderVideoInfo(data);
    populateQualityOptions(data.formats || []);
    showSection("videoInfoSection");
    showSection("downloadSection");
    show("divider1"); show("divider2");
    updateFfmpegWarning();
    toast("✅ Video info loaded!", "success");

  } catch (err) {
    showError("Connection failed. Is the server running?");
  } finally {
    setAnalyzeLoading(false);
  }
}

function setAnalyzeLoading(loading) {
  const btn = document.getElementById("analyzeBtn");
  btn.disabled = loading;
  if (loading) {
    btn.innerHTML = '<span class="spinner"></span> Loading...';
  } else {
    btn.textContent = "Download";
  }
}

function renderVideoInfo(info) {
  document.getElementById("videoThumb").src = info.thumbnail || "";
  document.getElementById("videoTitle").textContent = info.title || "Unknown Title";
  document.getElementById("chipDuration").textContent = "⏱ " + (info.duration_str || "--:--");
  document.getElementById("chipViews").textContent   = "👁 " + (info.views_str    || "---");
  document.getElementById("chipUploader").textContent = "👤 " + (info.uploader    || "---");
}

function populateQualityOptions(formats) {
  const sel = document.getElementById("qualitySelect");
  // Keep default options, add available ones at top
  const available = formats.map(f => f.label);
  // Highlight available resolutions
  Array.from(sel.options).forEach(opt => {
    const q = opt.value;
    if (q === "best") { opt.text = "⭐ Best Available"; return; }
    const label = q + "p";
    const found = available.find(a => a === label);
    opt.text = found ? `✓ ${label}` : `${label} (may upscale)`;
  });
  // Default to 1080 if available, else best
  if (available.includes("1080p")) sel.value = "1080";
  else if (available.length) sel.value = "best";
}

// ─── Mode Selection ──────────────────────────────────────────────
function setMode(mode) {
  currentMode = mode;
  document.getElementById("tabVideo").classList.toggle("active", mode === "video");
  document.getElementById("tabAudio").classList.toggle("active", mode === "audio");
  document.getElementById("tabVideo").setAttribute("aria-selected", mode === "video");
  document.getElementById("tabAudio").setAttribute("aria-selected", mode === "audio");

  document.getElementById("videoQualityGroup").style.display = mode === "video" ? "" : "none";
  document.getElementById("audioBitrateGroup").style.display = mode === "audio" ? "" : "none";

  const fmtOpt = document.getElementById("formatOption");
  fmtOpt.textContent = mode === "video" ? "MP4 (H.264)" : "MP3 (Audio)";

  const btn  = document.getElementById("downloadBtn");
  document.getElementById("downloadBtnIcon").textContent = mode === "video" ? "⬇️" : "🎵";
  document.getElementById("downloadBtnText").textContent = mode === "video" ? "Download Video" : "Download MP3";

  updateFfmpegWarning();
}

function updateFfmpegWarning() {
  const warn = document.getElementById("ffmpegWarn");
  warn.classList.toggle("visible", currentMode === "audio" && !ffmpegAvailable);
}

// ─── Start Download ──────────────────────────────────────────────
async function startDownload() {
  if (!currentVideoInfo) { toast("⚠️ Analyze a video first!", "error"); return; }

  const url     = document.getElementById("urlInput").value.trim();
  const quality = document.getElementById("qualitySelect").value;
  const bitrate = document.getElementById("bitrateSelect").value;
  const output_dir = document.getElementById("folderInput").value.trim();

  // Disable button
  const btn = document.getElementById("downloadBtn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Starting...';

  hideSection("successSection");
  hideSection("progressSection");
  hide("divider3"); hide("divider4");

  try {
    const res  = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, quality, mode: currentMode, bitrate, output_dir }),
    });
    const data = await res.json();

    if (!res.ok) { toast("❌ " + (data.error || "Download failed"), "error"); btn.disabled = false; restoreDownloadBtn(); return; }

    activeDownloadId = data.download_id;
    showSection("progressSection");
    show("divider3");
    startProgressStream(activeDownloadId);
    toast("🚀 Download started!", "info");

  } catch (err) {
    toast("❌ Connection failed.", "error");
    btn.disabled = false;
    restoreDownloadBtn();
  }
}

function restoreDownloadBtn() {
  const btn = document.getElementById("downloadBtn");
  btn.disabled = false;
  document.getElementById("downloadBtnIcon").textContent = currentMode === "video" ? "⬇️" : "🎵";
  document.getElementById("downloadBtnText").textContent = currentMode === "video" ? "Download Video" : "Download MP3";
  btn.innerHTML = `<span>${currentMode === "video" ? "⬇️" : "🎵"}</span> <span>${currentMode === "video" ? "Download Video" : "Download MP3"}</span>`;
}

// ─── SSE Progress Stream ─────────────────────────────────────────
function startProgressStream(downloadId) {
  if (activeEventSource) activeEventSource.close();

  activeEventSource = new EventSource(`/api/progress/${downloadId}`);

  activeEventSource.onmessage = (e) => {
    const state = JSON.parse(e.data);
    updateProgress(state);
    const status = state.status;
    if (status === "done") {
      activeEventSource.close();
      activeEventSource = null;
      const id = activeDownloadId;
      activeDownloadId  = null;
      onDownloadDone(state, id);
    } else if (status === "error") {
      activeEventSource.close();
      activeEventSource = null;
      activeDownloadId  = null;
      onDownloadError(state.error || "Unknown error");
    } else if (status === "cancelled") {
      activeEventSource.close();
      activeEventSource = null;
      activeDownloadId  = null;
      onDownloadCancelled();
    } else if (status === "not_found") {
      activeEventSource.close();
      activeEventSource = null;
      activeDownloadId  = null;
      // If we reconnected and it's missing, it likely errored or finished already silently
      onDownloadError("Download session lost. It may have failed silently.");
    }
  };

  activeEventSource.onerror = () => {
    activeEventSource.close();
    activeEventSource = null;
  };
}

function updateProgress(state) {
  const pct   = state.percent  || 0;
  const speed = state.speed    || "";
  const eta   = state.eta      || "";
  const status = state.status  || "downloading";

  document.getElementById("progressBar").style.width = pct + "%";
  document.getElementById("progressPct").textContent = pct + "%";
  document.getElementById("progressSpeed").textContent = speed ? "⚡ " + speed : "";
  document.getElementById("progressEta").textContent   = eta   ? "🕒 " + eta   : "";

  if (status === "processing") {
    document.getElementById("progressLabel").innerHTML =
      '<span class="processing-label">⚙️ Processing / merging...</span>';
    document.getElementById("progressPct").textContent = "100%";
  } else if (status === "extracting") {
    document.getElementById("progressLabel").innerHTML =
      '<span class="processing-label">🔍 Getting video stream...</span>';
  } else {
    document.getElementById("progressLabel").textContent = "Downloading...";
  }
}

function onDownloadDone(state, downloadId) {
  restoreDownloadBtn();
  hideSection("progressSection");
  hide("divider3");
  showSection("successSection");
  show("divider4");
  
  const customDir = document.getElementById("folderInput").value.trim();

  if (!customDir && downloadId) {
    // Stage 2: Trigger real browser download natively
    const downloadUrl = `/api/serve_file/${downloadId}`;
    
    document.getElementById("successPath").innerHTML = 
      `<span>Your download is ready!</span><br>` +
      `<a href="${downloadUrl}" class="manual-save-link">Manual Save Fallback</a>`;
    
    document.getElementById("openFolderBtn").style.display = "none";
    
    // Auto-trigger native browser download
    setTimeout(() => {
      console.log("🚀 Triggering native browser download for ID:", downloadId);
      window.location.assign(downloadUrl);
    }, 500);
  } else {
    document.getElementById("successPath").textContent = state.filepath || customDir;
    document.getElementById("openFolderBtn").dataset.filepath = state.filepath || "";
    document.getElementById("openFolderBtn").style.display = "inline-flex";
  }

  toast("🎉 Download complete!", "success", 5000);
}

function onDownloadError(msg) {
  restoreDownloadBtn();
  hideSection("progressSection");
  hide("divider3");
  showError(msg);
  toast("❌ " + msg, "error");
}

function onDownloadCancelled() {
  restoreDownloadBtn();
  hideSection("progressSection");
  hide("divider3");
  toast("⛔ Download cancelled.", "info");
}

// ─── Cancel ──────────────────────────────────────────────────────
async function cancelDownload() {
  if (!activeDownloadId) return;
  const btn = document.getElementById("cancelBtn");
  const origText = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "Cancelling...";
  
  try {
    await fetch(`/api/cancel/${activeDownloadId}`, { method: "POST" });
    // Assume success, event stream will catch the terminated state
  } catch (_) {
    btn.disabled = false;
    btn.innerHTML = origText;
  }
}

// ─── Open Folder ─────────────────────────────────────────────────
async function openFolder() {
  const filepath = document.getElementById("openFolderBtn").dataset.filepath || "";
  try {
    await fetch("/api/open_folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filepath }),
    });
  } catch (_) {
    toast("❌ Could not open folder.", "error");
  }
}

// ─── Reset ───────────────────────────────────────────────────────
function resetApp() {
  if (activeEventSource) { activeEventSource.close(); activeEventSource = null; }
  activeDownloadId  = null;
  currentVideoInfo  = null;

  document.getElementById("urlInput").value = "";
  document.getElementById("folderInput").value = "";
  hideError();
  hideSection("videoInfoSection");
  hideSection("downloadSection");
  hideSection("progressSection");
  hideSection("successSection");
  hideDividers();
  restoreDownloadBtn();
  setMode("video");
  document.getElementById("urlInput").focus();
}

// ─── Toast ───────────────────────────────────────────────────────
function toast(message, type = "info", duration = 3500) {
  const container = document.getElementById("toastContainer");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  const icons = { success: "✅", error: "❌", info: "ℹ️" };
  el.innerHTML = `<span>${icons[type] || "ℹ️"}</span><span>${message}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add("fade-out");
    el.addEventListener("animationend", () => el.remove());
  }, duration);
}

// ─── Helpers ─────────────────────────────────────────────────────
function showSection(id) {
  const el = document.getElementById(id);
  el.style.display = "";
  requestAnimationFrame(() => el.classList.add("visible"));
}

function hideSection(id) {
  const el = document.getElementById(id);
  el.classList.remove("visible");
  el.style.display = "none";
}

function show(id) { document.getElementById(id).style.display = ""; }
function hide(id) { document.getElementById(id).style.display = "none"; }

function hideDividers() {
  ["divider1","divider2","divider3","divider4"].forEach(hide);
}

function showError(msg) {
  document.getElementById("errorMsg").textContent = msg;
  document.getElementById("errorBanner").classList.add("visible");
}

function hideError() {
  document.getElementById("errorBanner").classList.remove("visible");
}
