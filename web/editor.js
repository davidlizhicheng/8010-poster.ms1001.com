import { initPage } from "/layout.js?v=28";
import { authReady, getAuthState } from "/auth.js?v=40";

const $ = (id) => document.getElementById(id);

let current = {
  objectUrl: "",
  fileName: "poster-image.png",
  mimeType: "image/png",
  width: 0,
  height: 0,
  remoteUrl: "",
};

function revokeCurrentUrl() {
  if (current.objectUrl?.startsWith("blob:")) {
    URL.revokeObjectURL(current.objectUrl);
  }
}

function setStatus(text, isError = false) {
  const el = $("statusLine");
  if (!el) return;
  el.textContent = text;
  el.className = isError ? "hint err" : "hint";
}

function updateMeta() {
  const meta = $("imageMeta");
  if (!meta) return;
  if (!current.objectUrl && !current.remoteUrl) {
    meta.textContent = "尚未加载图片";
    return;
  }
  const sizePart = current.width && current.height ? `${current.width} × ${current.height}` : "尺寸读取中";
  meta.textContent = `${current.fileName} · ${sizePart}`;
}

function setButtonsEnabled(enabled) {
  $("downloadBtn").disabled = !enabled;
  $("replaceBtn").disabled = !enabled;
}

function showPreview(url) {
  const empty = $("emptyState");
  const wrap = $("previewWrap");
  const img = $("previewImage");
  if (!img || !wrap || !empty) return;
  img.onload = () => {
    current.width = img.naturalWidth;
    current.height = img.naturalHeight;
    updateMeta();
  };
  img.src = url;
  empty.hidden = true;
  wrap.hidden = false;
  setButtonsEnabled(true);
}

async function loadFromFile(file) {
  if (!file?.type?.startsWith("image/")) {
    setStatus("请选择图片文件（JPG / PNG / WebP / GIF）", true);
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    setStatus("单张图片建议不超过 10MB", true);
    return;
  }
  revokeCurrentUrl();
  const objectUrl = URL.createObjectURL(file);
  current = {
    objectUrl,
    fileName: file.name || "uploaded-image.png",
    mimeType: file.type || "image/png",
    width: 0,
    height: 0,
    remoteUrl: "",
  };
  showPreview(objectUrl);
  setStatus(`已加载：${current.fileName}`);
  updateMeta();
}

async function loadFromUrl(url, title = "poster-image.png") {
  if (!url) return;
  setStatus("正在加载图片…");
  try {
    const res = await fetch(url, { credentials: "include" });
    if (!res.ok) throw new Error(`加载失败 (${res.status})`);
    const blob = await res.blob();
    revokeCurrentUrl();
    const objectUrl = URL.createObjectURL(blob);
    const ext = blob.type === "image/jpeg" ? "jpg" : blob.type === "image/webp" ? "webp" : "png";
    current = {
      objectUrl,
      fileName: title.endsWith(`.${ext}`) ? title : `${title.replace(/\.[^.]+$/, "")}.${ext}`,
      mimeType: blob.type || "image/png",
      width: 0,
      height: 0,
      remoteUrl: url,
    };
    showPreview(objectUrl);
    setStatus("已从作品或链接载入，可下载或替换。");
    updateMeta();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "图片加载失败", true);
  }
}

function pickFile() {
  $("fileInput")?.click();
}

async function downloadCurrent() {
  const src = current.objectUrl || current.remoteUrl;
  if (!src) return;
  try {
    let blob;
    if (current.objectUrl.startsWith("blob:")) {
      const res = await fetch(current.objectUrl);
      blob = await res.blob();
    } else {
      const res = await fetch(src, { credentials: "include" });
      blob = await res.blob();
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = current.fileName || "poster-image.png";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    setStatus("下载已开始");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "下载失败", true);
  }
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function api(path) {
  const headers = { "Content-Type": "application/json; charset=utf-8" };
  const token = window.suatAccessToken?.() || localStorage.getItem("suat_access_token") || "";
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { credentials: "include", headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
  return data;
}

async function loadHistory() {
  const grid = $("historyGrid");
  const hint = $("historyHint");
  if (!grid) return;
  const auth = getAuthState();
  if (!auth.user) {
    if (hint) hint.textContent = "登录后可从已生成的海报中选取编辑。";
    grid.innerHTML = "";
    return;
  }
  if (hint) hint.textContent = "点击「编辑」将图片带入左侧预览区。";
  try {
    const history = await api("/api/history?jobs=80&items=120");
    const items = (history.items || []).filter((item) => item.status === "completed" && item.image_path);
    if (!items.length) {
      grid.innerHTML = `<p class="hint">暂无已生成作品，先去 <a href="/generate.html">在线生成</a> 创建海报。</p>`;
      return;
    }
    grid.innerHTML = items
      .slice(0, 24)
      .map((item) => {
        const title = String(item.title || "未命名作品");
        return `<article class="editor-history-card">
          <img src="${esc(item.image_path)}" alt="${esc(title)}" loading="lazy" />
          <div class="body">
            <strong>${esc(title)}</strong>
            <div class="actions">
              <button class="link-btn" type="button" data-edit-src="${esc(item.image_path)}" data-edit-title="${esc(title)}">编辑</button>
              <a class="link-btn" href="${esc(item.image_path)}" download target="_blank" rel="noreferrer">下载</a>
            </div>
          </div>
        </article>`;
      })
      .join("");
    grid.querySelectorAll("[data-edit-src]").forEach((btn) => {
      btn.addEventListener("click", () => {
        loadFromUrl(btn.dataset.editSrc, btn.dataset.editTitle || "poster-image.png");
      });
    });
  } catch (error) {
    if (hint) hint.textContent = error instanceof Error ? error.message : "历史作品加载失败";
    grid.innerHTML = "";
  }
}

function bindDropzone() {
  const zone = $("dropzone");
  if (!zone) return;
  ["dragenter", "dragover"].forEach((type) => {
    zone.addEventListener(type, (e) => {
      e.preventDefault();
      zone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((type) => {
    zone.addEventListener(type, (e) => {
      e.preventDefault();
      zone.classList.remove("dragover");
    });
  });
  zone.addEventListener("drop", (e) => {
    const file = e.dataTransfer?.files?.[0];
    if (file) loadFromFile(file);
  });
}

await initPage("editor");
await authReady;

bindDropzone();

$("uploadBtn")?.addEventListener("click", pickFile);
$("emptyUploadBtn")?.addEventListener("click", pickFile);
$("replaceBtn")?.addEventListener("click", pickFile);
$("downloadBtn")?.addEventListener("click", downloadCurrent);
$("refreshHistoryBtn")?.addEventListener("click", () => loadHistory());
$("fileInput")?.addEventListener("change", (e) => {
  const file = e.target.files?.[0];
  if (file) loadFromFile(file);
  e.target.value = "";
});

window.addEventListener("poster:auth", () => loadHistory());

const params = new URLSearchParams(location.search);
const src = params.get("src");
if (src) {
  loadFromUrl(src, params.get("title") || "poster-image.png");
}

await loadHistory();
