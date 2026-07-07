import { initPage } from "/layout.js?v=27";
import { FALLBACK_PLANS } from "/plans.js?v=13";
import { authReady, getAuthState, isUnifiedAuthMode, navigateToUnifiedLogin, syncHeaderAuthUI } from "/auth.js?v=39";

let state = {
  config: {},
  templates: [],
  history: { items: [] },
  auth: { user: null, usage: null, credit_buckets: [] },
  creditBuckets: [],
  selectedCreditBucketId: "",
  activeSlotId: null,
  selectedPlanId: "single_50",
  referenceImages: [],
  batchPlanItems: [],
  modifyMode: false,
  slotStatus: null,
  openTemplateGroups: new Set(),
  templateGroupsTouched: false,
  generationMode: "single",
};

await initPage("generate");
await authReady;

state.auth = getAuthState();
window.__posterUser = state.auth.user;

window.addEventListener("poster:auth", (e) => {
  state.auth = e.detail;
  state.creditBuckets = e.detail.credit_buckets || [];
  if (!e.detail.user) clearStudioState();
  syncAuthUI();
  if (e.detail.user) loadHistory();
});

const FALLBACK_TEMPLATES = [
  { key: "study-card", name: "学习训练卡" },
  { key: "course-sale", name: "课程推广海报" },
  { key: "community", name: "社群裂变海报" },
  { key: "festival", name: "节日促销海报" },
  { key: "brand-event", name: "品牌活动海报" },
  { key: "social-cover", name: "自媒体封面配图" },
  { key: "flyer-print", name: "宣传单折页主视觉" },
  { key: "product-poster", name: "产品宣传海报" },
  { key: "recruitment", name: "招聘招募海报" },
  { key: "exhibition", name: "展会展架物料" },
  { key: "menu-price", name: "菜单价目表" },
  { key: "certificate", name: "证书奖状" },
  { key: "invitation", name: "邀请函" },
  { key: "ecommerce", name: "电商主图详情图" },
  { key: "office-infographic", name: "职场信息长图" },
  { key: "edu-illustration", name: "科普教育图解" },
  { key: "ip-creative", name: "IP 文创视觉" },
  { key: "livestream-bg", name: "直播间背景" },
  { key: "spatial-scene", name: "空间虚拟效果图" },
  { key: "custom-vertical", name: "细分定制竖版" },
  { key: "speech-outline", name: "演讲提纲" },
  { key: "business-quote-card", name: "商业金句卡片" },
];

const TEMPLATE_GROUPS = [
  {
    title: "一、海报展示类",
    keys: ["brand-event", "flyer-print", "product-poster", "exhibition", "social-cover"],
  },
  {
    title: "二、海报推介类",
    keys: ["invitation", "festival", "community", "livestream-bg", "recruitment"],
  },
  {
    title: "三、视觉推广类",
    keys: ["ip-creative", "custom-vertical", "ecommerce", "menu-price", "spatial-scene"],
  },
  {
    title: "四、应用学习类",
    keys: ["certificate", "study-card", "course-sale", "edu-illustration", "office-infographic", "speech-outline", "business-quote-card"],
  },
];

const FALLBACK_SIZE_OPTIONS = [
  { value: "1024x1536", label: "竖版海报", note: "1024 x 1536" },
  { value: "1024x1024", label: "方形海报", note: "1024 x 1024" },
  { value: "1536x1024", label: "横版封面", note: "1536 x 1024" },
  { value: "auto", label: "自动匹配", note: "由模型决定" },
  { value: "custom", label: "自定义尺寸", note: "手动输入宽高" },
];

function orderedTemplates(list) {
  const byKey = new Map(list.map((item) => [item.key, item]));
  const ordered = [];
  TEMPLATE_GROUPS.forEach((group) => {
    group.keys.forEach((key) => {
      if (byKey.has(key)) ordered.push(byKey.get(key));
    });
  });
  list.forEach((item) => {
    if (!ordered.some((orderedItem) => orderedItem.key === item.key)) ordered.push(item);
  });
  return ordered;
}

const THEME_FIELD_IDS = [
  "campaignName",
  "subject",
  "audience",
  "singleTitleInput",
  "singlePromptInput",
  "batchItemsInput",
  "batchPromptInput",
];

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function cleanTitle(value, fallback = "未命名作品") {
  const text = String(value || "").trim();
  if (!text || /^\?+$/.test(text) || (text.match(/\?/g) || []).length >= Math.max(6, text.length * 0.45)) return fallback;
  return text;
}

function autoCampaignName() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `自动项目-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
}
const PREVIEW_PLACEHOLDER = `<div class="gen-preview-placeholder"><svg width="48" height="48" viewBox="0 0 24 24" fill="none" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="3" stroke="currentColor" stroke-width="1.5"/><path d="M8 12h8M12 8v8" stroke="currentColor" stroke-width="1.5"/></svg><p>生成完成后将在此展示</p></div>`;

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json; charset=utf-8", ...(options.headers || {}) };
  const token = window.suatAccessToken?.() || localStorage.getItem("suat_access_token") || "";
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, {
    credentials: "include",
    headers,
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
  return data;
}

function promptLoginForFeature(hintEl, message = "请先登录后再使用此功能") {
  if (state.auth.user) return true;
  if (hintEl) {
    hintEl.textContent = message;
    hintEl.className = "hint err";
  }
  if (isUnifiedAuthMode()) {
    navigateToUnifiedLogin("login", window.location.href);
  }
  return false;
}

function statusText(status) {
  return (
    {
      completed: "已生成",
      failed: "生成失败",
      partial: "部分完成",
      running: "生成中",
      approved: "已到账",
      pending: "待审核",
      rejected: "已驳回",
    }[status] || status
  );
}

function generationHintText() {
  const max = state.config.max_items_per_job || 100;
  if (state.generationMode === "batch") {
    return `批量模式：最多 ${max} 张同系列，逐张独立出图；首张定风格，后续自动跟版；每张约 1–3 分钟。`;
  }
  return "单张模式：填写主题与补充说明即可生成；修改时保持主题不变。";
}

function defaultStatusLine() {
  const user = state.auth.user;
  const usage = state.auth.usage;
  if (!user) return "请先登录后再生成。";
  if (usage?.plan_label) return usage.plan_label;
  return "填写参数后点击开始生成。";
}

function isBatchMode() {
  return state.generationMode === "batch" && !state.modifyMode;
}

function setGenerationMode(mode, { force = false } = {}) {
  if (state.modifyMode && mode === "batch" && !force) return;
  state.generationMode = mode === "batch" ? "batch" : "single";
  const singlePanel = $("singleModePanel");
  const batchPanel = $("batchModePanel");
  const singleBtn = $("modeSingleBtn");
  const batchBtn = $("modeBatchBtn");
  const switchEl = $("genModeSwitch");
  if (singlePanel) singlePanel.hidden = state.generationMode === "batch";
  if (batchPanel) batchPanel.hidden = state.generationMode !== "batch";
  if (singleBtn) {
    singleBtn.classList.toggle("active", state.generationMode === "single");
    singleBtn.setAttribute("aria-selected", state.generationMode === "single" ? "true" : "false");
  }
  if (batchBtn) {
    batchBtn.classList.toggle("active", state.generationMode === "batch");
    batchBtn.setAttribute("aria-selected", state.generationMode === "batch" ? "true" : "false");
  }
  if (switchEl) switchEl.hidden = !!state.modifyMode;
  if (batchBtn) batchBtn.disabled = !!state.modifyMode;
  renderGenerationHint();
}

function updateCreditBucketHint() {
  const hint = $("creditBucketHint");
  const bucket = state.creditBuckets.find((b) => b.id === state.selectedCreditBucketId);
  if (hint) {
    hint.textContent = bucket ? `已选：${bucket.label}（${bucket.modify_rule}）` : "";
  }
}

function formatBucketCredits(bucket) {
  if (bucket?.id === "owner_vip" || (bucket?.credits_remaining ?? 0) >= 99999) return "无限";
  return `剩 ${bucket.credits_remaining} 次`;
}

function renderCreditBuckets() {
  const wrap = $("creditBucketWrap");
  const select = $("creditBucketSelect");
  if (!wrap || !select) return;

  const isOwner = Boolean(state.auth.user?.owner_vip || state.auth.usage?.owner_vip);
  let buckets = [...(state.creditBuckets || [])];
  const status = state.slotStatus;

  if (state.modifyMode && status?.allows_bundle_modify) {
    wrap.hidden = true;
    return;
  }
  if (state.modifyMode && status?.needs_credit_for_modify) {
    buckets = buckets.filter((b) => !b.allows_bundle_modify);
  }

  if (!state.auth.user || buckets.length === 0) {
    wrap.hidden = true;
    return;
  }

  wrap.hidden = buckets.length === 0 || (state.modifyMode && status?.allows_bundle_modify);
  select.innerHTML = buckets
    .map((b) => {
      const expiry = b.expires_text ? ` · 至 ${b.expires_text}` : "";
      return `<option value="${b.id}">${b.label} · ${formatBucketCredits(b)} · ${b.modify_rule}${expiry}</option>`;
    })
    .join("");

  if (state.selectedCreditBucketId && buckets.some((b) => b.id === state.selectedCreditBucketId)) {
    select.value = state.selectedCreditBucketId;
  } else {
    const preferred = isOwner
      ? buckets.find((b) => b.id === "owner_vip") || buckets[0]
      : buckets.find((b) => !b.allows_bundle_modify) || buckets[0];
    select.value = preferred?.id || "";
    state.selectedCreditBucketId = select.value;
  }
  select.disabled = isOwner;
  updateCreditBucketHint();
}

function getCreditBucketPayload(isModify) {
  if (state.auth.user?.owner_vip || state.auth.usage?.owner_vip) return undefined;
  const status = state.slotStatus;
  if (isModify && status?.allows_bundle_modify && (status.remaining_modifications ?? 0) > 0) {
    return undefined;
  }
  const buckets = state.creditBuckets || [];
  if (buckets.length <= 1) return buckets[0]?.id || undefined;
  const id = state.selectedCreditBucketId || $("creditBucketSelect")?.value;
  if (!id) throw new Error("请先在「本次使用额度」中选择要使用的套餐。");
  return id;
}

function setThemeLocked(locked) {
  THEME_FIELD_IDS.forEach((id) => {
    const el = $(id);
    if (el) el.readOnly = locked;
  });
  const sel = $("templateKey");
  if (sel) sel.disabled = locked;
  $("templateTiles")?.classList.toggle("locked", locked);
  $("posterForm")?.classList.toggle("theme-locked", locked);
}

function updateModifyUI(slotStatus) {
  state.slotStatus = slotStatus || state.slotStatus;
  const status = state.slotStatus;
  const hint = $("modifyRemainHint");
  const modifyBtn = $("modifyBtn");
  const newBtn = $("newPosterBtn");
  const genBtn = $("generateBtn");
  const notesWrap = $("modifyNotesWrap");

  if (!status) {
    if (hint) hint.hidden = true;
    if (modifyBtn) modifyBtn.hidden = true;
    if (newBtn) newBtn.hidden = true;
    if (genBtn) genBtn.hidden = false;
    if (notesWrap) notesWrap.hidden = true;
    const refLabel = $("referencePickBtn")?.closest("label");
    if (refLabel) refLabel.hidden = false;
    renderCreditBuckets();
    return;
  }

  const remaining = status.remaining_modifications ?? 0;
  const used = status.attempts_used ?? 0;
  const canModify = status.can_modify;
  const bundleModify = Boolean(status.allows_bundle_modify);
  const needsCredit = Boolean(status.needs_credit_for_modify);

  const refLabel = $("referencePickBtn")?.closest("label");
  if (refLabel) refLabel.hidden = state.modifyMode;

  if (state.modifyMode) {
    if (hint) {
      hint.hidden = false;
      if (needsCredit) {
        hint.textContent = "本主题由套餐类额度创建；继续修改将另计1次额度，请确认已选择额度批次。";
      } else if (bundleModify) {
        hint.textContent = `主题已锁定；已用 ${used}/${status.max_attempts} 次 · 剩余免费修改 ${remaining} 次`;
      } else {
        hint.textContent = `主题已锁定；已用 ${used} 次（套餐类：每次修改另计1次额度）`;
      }
    }
    if (notesWrap) notesWrap.hidden = false;
    if (genBtn) genBtn.hidden = true;
    if (newBtn) newBtn.hidden = false;
    if (modifyBtn) {
      modifyBtn.hidden = false;
      if (needsCredit) {
        modifyBtn.textContent = "提交修改（另计1次额度）";
        modifyBtn.disabled = false;
      } else {
        modifyBtn.textContent = remaining > 0 ? `提交修改（剩余 ${remaining} 次）` : "修改次数已用完";
        modifyBtn.disabled = remaining <= 0;
      }
    }
  } else {
    if (notesWrap) notesWrap.hidden = true;
    if (genBtn) genBtn.hidden = false;
    if (newBtn) newBtn.hidden = !state.activeSlotId;
    if (modifyBtn) modifyBtn.hidden = !canModify;
    if (canModify && hint && modifyBtn) {
      hint.hidden = false;
      if (needsCredit) {
        hint.textContent = "可继续修改；套餐类主题每次修改另计1次额度";
        modifyBtn.textContent = "继续修改（另计1次额度）";
      } else if (bundleModify) {
        hint.textContent = `当前主题还可免费修改 ${remaining} 次，点击「继续修改」后填写修改说明`;
        modifyBtn.textContent = `继续修改（剩余 ${remaining} 次）`;
      } else {
        hint.textContent = "可继续修改；每次修改另计1次额度";
        modifyBtn.textContent = "继续修改（另计1次额度）";
      }
      modifyBtn.disabled = false;
    } else if (hint) {
      hint.hidden = true;
    }
  }
  renderCreditBuckets();
}

function enterModifyMode(slotStatus) {
  state.modifyMode = true;
  state.activeSlotId = slotStatus.slot_id;
  const locked = slotStatus.locked || {};
  $("campaignName").value = locked.campaign_name || $("campaignName").value;
  if (locked.template_key) $("templateKey").value = locked.template_key;
  $("subject").value = locked.subject || "";
  $("audience").value = locked.audience || "";
  $("singleTitleInput").value = cleanTitle(locked.title, "") || "";
  setGenerationMode("single", { force: true });
  $("modifyNotes").value = "";
  setThemeLocked(true);
  updateModifyUI(slotStatus);
}

function exitModifyMode() {
  state.modifyMode = false;
  state.activeSlotId = null;
  state.slotStatus = null;
  setThemeLocked(false);
  $("modifyNotes").value = "";
  if ($("modifyNotesWrap")) $("modifyNotesWrap").hidden = true;
  setGenerationMode(state.generationMode || "single");
  updateModifyUI(null);
}

async function startModifyFromSlot(slotId) {
  const slotStatus = await api(`/api/slots/${slotId}`);
  enterModifyMode(slotStatus);
}

function detectCollageRisk(promptText) {
  const match = String(promptText || "").match(/(\d+)\s*张/);
  const requested = match ? Number(match[1]) : 0;
  const collageWords = /一次生成|拼图|组图|宫格|合并输出/.test(promptText || "");
  if (requested > 1 || collageWords) {
    return `提示词像在要求「一次出 ${requested || "多"} 张」，模型容易拼成大图。请切换到「批量生成」，在系列清单中每行填写一张内容。`;
  }
  return null;
}

function detectBatchCollageRisk(promptText, batchTitles) {
  const match = String(promptText || "").match(/(\d+)\s*张/);
  const requested = match ? Number(match[1]) : 0;
  if (requested > 1 && requested !== batchTitles.length) {
    return `系列风格里写了「${requested} 张」，但清单只有 ${batchTitles.length} 行。请改成与行数一致，或删除「一次生成 N 张」表述。`;
  }
  return null;
}

function syncQuoteCardDefaults() {
  const template = $("templateKey")?.value;
  const prompt = isBatchMode()
    ? $("batchPromptInput")?.value || ""
    : $("singlePromptInput")?.value || "";
  if (template === "business-quote-card" || /16\s*[：:]\s*9|16:9|商业金句/.test(prompt)) {
    const size = $("posterSize");
    if (size && size.value !== "custom" && size.querySelector('option[value="1536x1024"]')) {
      size.value = "1536x1024";
    }
  }
}

function parseBatchTitles(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function resolveSingleTitle() {
  const title = $("singleTitleInput")?.value.trim() || "";
  if (title) return [title];
  const prompt = $("singlePromptInput")?.value.trim() || "";
  return [prompt.slice(0, 28) || "未命名设计"];
}

function resolveBatchTitles() {
  const max = state.config.max_items_per_job || 100;
  return parseBatchTitles($("batchItemsInput")?.value).slice(0, max);
}

function batchPlanPayloadFor(titles) {
  const planned = state.batchPlanItems || [];
  if (!planned.length || planned.length !== titles.length) return [];
  return planned.map((item, index) => ({
    title: titles[index],
    prompt: item.prompt || "",
  })).filter((item) => item.title && item.prompt);
}

function updateModeUI() {
  const hint = $("batchItemsHint");
  const button = $("generateBtn");
  if (state.modifyMode) {
    if (button && !button.disabled) button.textContent = "开始生成设计图";
    return;
  }
  if (isBatchMode()) {
    const max = state.config.max_items_per_job || 100;
    const titles = resolveBatchTitles();
    if (hint) {
      if (titles.length < 2) {
        hint.textContent = "批量至少需要 2 行主题；每行一张独立海报，首张定风格后续跟版。";
        hint.className = "hint err";
      } else if (titles.length > max) {
        hint.textContent = `当前 ${titles.length} 行，超出上限 ${max} 张，只会生成前 ${max} 张。`;
        hint.className = "hint err";
      } else {
        hint.textContent = `将批量生成 ${titles.length} 张同系列海报，消耗 ${titles.length} 次额度，首张确定风格后后续跟版。`;
        hint.className = "hint";
      }
    }
    if (button && !button.disabled) {
      button.textContent =
        titles.length >= 2 ? `开始批量生成（${Math.min(titles.length, max)} 张）` : "开始批量生成";
    }
    return;
  }
  if (hint) hint.className = "hint";
  if (button && !button.disabled) button.textContent = "开始生成设计图";
}

function renderGenerationHint() {
  const el = $("generationHint");
  if (el) el.textContent = generationHintText();
  updateModeUI();
}

function parseSizeValue(value) {
  const match = String(value || "").trim().toLowerCase().match(/^(\d{3,4})x(\d{3,4})$/);
  return match ? { width: Number(match[1]), height: Number(match[2]) } : null;
}

function customSizeError(width, height) {
  if (!Number.isFinite(width) || !Number.isFinite(height)) return "请输入自定义宽度和高度。";
  if (width % 16 !== 0 || height % 16 !== 0) return "宽度和高度都需要是 16 的倍数。";
  if (Math.max(width, height) > 3840) return "最长边不能超过 3840。";
  if (Math.max(width, height) / Math.min(width, height) > 3) return "长短边比例不能超过 3:1。";
  const pixels = width * height;
  if (pixels < 655360 || pixels > 8294400) return "总像素需在 655360 到 8294400 之间。";
  return "";
}

function syncCustomSizeFields() {
  const select = $("posterSize");
  const fields = $("customSizeFields");
  const hint = $("customSizeHint");
  const custom = select?.value === "custom";
  if (fields) fields.hidden = !custom;
  if (hint) hint.hidden = !custom;
}

function getPosterSizePayload() {
  const select = $("posterSize");
  if (select?.value !== "custom") return select?.value || state.config.size || "1024x1536";
  const width = Number($("customWidth")?.value);
  const height = Number($("customHeight")?.value);
  const error = customSizeError(width, height);
  if (error) throw new Error(error);
  return `${width}x${height}`;
}

function renderPosterSizes() {
  const select = $("posterSize");
  if (!select) return;
  const options = Array.isArray(state.config.size_options) && state.config.size_options.length
    ? state.config.size_options
    : FALLBACK_SIZE_OPTIONS;
  const current = state.config.size || select.value || "1024x1536";
  select.innerHTML = options
    .map((item) => {
      const note = item.note ? ` · ${item.note}` : "";
      return `<option value="${esc(item.value)}">${esc(item.label || item.value)}${esc(note)}</option>`;
    })
    .join("");
  const customSize = parseSizeValue(current);
  if (options.some((item) => item.value === current)) {
    select.value = current;
  } else if (customSize) {
    select.value = "custom";
    if ($("customWidth")) $("customWidth").value = customSize.width;
    if ($("customHeight")) $("customHeight").value = customSize.height;
  } else {
    select.value = "1024x1536";
  }
  syncCustomSizeFields();
}

function renderTemplates() {
  const el = $("templateKey");
  if (!el) return;
  const list = state.templates?.length ? state.templates : FALLBACK_TEMPLATES;
  const current = el.value;
  const ordered = orderedTemplates(list);
  el.innerHTML = `<option value="">不选择模板</option>${ordered.map((t) => `<option value="${t.key}">${t.name}</option>`).join("")}`;
  if (current && ordered.some((t) => t.key === current)) el.value = current;
  else if (current === "") el.value = "";
  renderTemplateTiles();
}

function renderTemplateTiles() {
  const tiles = $("templateTiles");
  const select = $("templateKey");
  if (!tiles || !select) return;
  const list = state.templates?.length ? state.templates : FALLBACK_TEMPLATES;
  const byKey = new Map(list.map((item) => [item.key, item]));
  const selected = select.value || "";
  const selectedGroupIndex = selected
    ? TEMPLATE_GROUPS.findIndex((group) => group.keys.includes(selected))
    : -1;
  if (!state.templateGroupsTouched && selectedGroupIndex >= 0 && state.openTemplateGroups.size === 0) {
    state.openTemplateGroups.add(selectedGroupIndex);
  }
  tiles.classList.toggle("no-selection", !selected);
  let index = 0;
  tiles.innerHTML = TEMPLATE_GROUPS
    .map((group, groupIndex) => {
      const open = state.openTemplateGroups.has(groupIndex);
      const cards = group.keys
        .map((key) => byKey.get(key))
        .filter(Boolean)
        .map((t) => {
          index += 1;
          const active = t.key === selected;
          const desc = t.structure || t.style || "适合快速生成可发布的竖版海报";
          return `<button class="template-tile${active ? " active" : ""}" type="button" role="radio" aria-checked="${active}" data-template="${t.key}">
            <span class="template-tile-index">${String(index).padStart(2, "0")}</span>
            <strong>${t.name}</strong>
            <small>${desc}</small>
          </button>`;
        })
        .join("");
      return `<section class="template-group${open ? " open" : ""}">
        <button class="template-group-head" type="button" data-template-group="${groupIndex}" aria-expanded="${open}">
          <span>${group.title}</span>
          <b>${open ? "收起" : "展开"}</b>
        </button>
        <div class="template-group-grid" ${open ? "" : "hidden"}>${cards}</div>
      </section>`;
    })
    .join("");
  tiles.querySelectorAll("[data-template-group]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const groupIndex = Number(btn.dataset.templateGroup);
      state.templateGroupsTouched = true;
      if (state.openTemplateGroups.has(groupIndex)) {
        state.openTemplateGroups.delete(groupIndex);
      } else {
        state.openTemplateGroups.add(groupIndex);
      }
      renderTemplateTiles();
    });
  });
  tiles.querySelectorAll("[data-template]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (select.disabled) return;
      const key = btn.dataset.template;
      if (select.value === key) {
        select.value = "";
      } else {
        select.value = key;
        const groupIndex = TEMPLATE_GROUPS.findIndex((group) => group.keys.includes(key));
        if (groupIndex >= 0) {
          state.templateGroupsTouched = true;
          state.openTemplateGroups = new Set([groupIndex]);
        }
      }
      renderTemplateTiles();
    });
  });
}

function bootstrapPage() {
  if (!state.config.plans?.length) {
    state.config = {
      ...state.config,
      plans: FALLBACK_PLANS,
      generation: {
        typical_minutes: 3,
        failure_rate_percent: 0,
        credit_on_failure: "成功才计算额度",
        modifications_per_theme: 5,
      },
    };
  }
  if (!state.templates?.length) state.templates = FALLBACK_TEMPLATES;
  renderTemplates();
  renderGenerationHint();
}

function syncAuthUI() {
  syncHeaderAuthUI(state.auth);
  const user = state.auth.user;
  window.__posterUser = user;
  const statusLine = $("statusLine");
  if (statusLine && (statusLine.className === "hint" || !statusLine.textContent?.trim())) {
    statusLine.textContent = defaultStatusLine();
    statusLine.className = "hint";
  }
  const badge = $("studioBadge");
  if (badge) {
    badge.textContent = user ? user.owner_greeting || user.display_name || user.org || "已登录" : "请先登录";
    badge.classList.toggle("ready", Boolean(user));
  }
  const support = [];
  if (state.config.support_phone) support.push(`客服 ${state.config.support_phone}`);
  if (state.config.support_wechat) support.push(`微信 ${state.config.support_wechat}`);
  state.creditBuckets = state.auth.credit_buckets || state.creditBuckets || [];
  renderCreditBuckets();
}

function renderReferencePreview() {
  const box = $("referencePreview");
  if (!box) return;
  box.innerHTML = state.referenceImages
    .map(
      (src, i) =>
        `<figure class="ref-thumb"><img src="${src}" alt="参考图 ${i + 1}" /><button type="button" data-ref-remove="${i}" aria-label="移除">×</button></figure>`
    )
    .join("");
  box.querySelectorAll("[data-ref-remove]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.referenceImages.splice(Number(btn.dataset.refRemove), 1);
      renderReferencePreview();
      syncReferenceName();
    });
  });
}

function syncReferenceName() {
  const max = state.config.max_reference_images || 30;
  const name = $("referenceImagesName");
  if (!name) return;
  if (name) {
    name.textContent = state.referenceImages.length
      ? `已选 ${state.referenceImages.length} 张（可继续添加，当前单次安全上限 ${max} 张）`
      : `用于辅助风格与配色，支持多图上传，每张最大 2MB`;
  }
}

async function pickReferenceImages(fileList) {
  const max = state.config.max_reference_images || 30;
  const files = Array.from(fileList || []);
  const merged = [...state.referenceImages];
  for (const file of files) {
    if (merged.length >= max) break;
    if (file.size > 2 * 1024 * 1024) {
      $("statusLine").textContent = `${file.name} 超过 2MB，请压缩后上传`;
      $("statusLine").className = "hint err";
      continue;
    }
    const dataUrl = await readFileAsDataUrl(file);
    merged.push(dataUrl);
  }
  state.referenceImages = merged.slice(0, max);
  renderReferencePreview();
  syncReferenceName();
}

function clearStudioState() {
  state.history = { items: [], summary: {} };
  state.activeSlotId = null;
  state.modifyMode = false;
  state.slotStatus = null;
  state.referenceImages = [];
  exitModifyMode();
  renderGallery();
  $("latestPreview").classList.add("empty");
  $("latestPreview").innerHTML = PREVIEW_PLACEHOLDER;
  $("statusLine").textContent = defaultStatusLine();
  $("statusLine").className = "hint";
  renderReferencePreview();
  syncReferenceName();
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("读取文件失败"));
    reader.readAsDataURL(file);
  });
}

function renderGallery() {
  const gallery = $("gallery");
  const template = $("posterCardTemplate");
  gallery.innerHTML = "";
  state.history.items.forEach((item) => {
    const node = template.content.firstElementChild.cloneNode(true);
    const img = node.querySelector("img");
    const link = node.querySelector(".poster-link");
    const open = node.querySelector(".poster-actions a");
    const failed = item.status === "failed" || !item.image_path;
    if (failed) {
      link.removeAttribute("href");
      img.removeAttribute("src");
      img.alt = cleanTitle(item.title, "未命名作品");
      img.classList.add("failed-thumb");
      node.classList.add("poster-failed");
    } else {
      link.href = item.image_path;
      img.src = item.image_path;
      img.alt = cleanTitle(item.title, "未命名作品");
      open.href = item.image_path;
    }
    node.querySelector("h4").textContent = cleanTitle(item.title, "未命名作品");
    const stateEl = node.querySelector(".poster-state");
    stateEl.textContent = failed
      ? item.error ? `失败：${item.error.slice(0, 40)}` : statusText(item.status)
      : statusText(item.status);
    const modifyBtn = node.querySelector(".modify-item-btn");
    const editBtn = node.querySelector(".edit-item-btn");
    if (failed) open.hidden = true;
    if (!failed && item.image_path && editBtn) {
      editBtn.href = `/editor.html?src=${encodeURIComponent(item.image_path)}&title=${encodeURIComponent(cleanTitle(item.title, "poster"))}`;
    }
    if (!failed && item.can_modify && item.slot_id) {
      modifyBtn.hidden = false;
      modifyBtn.textContent = remaining > 0 ? `修改（剩余 ${remaining} 次）` : "修改";
      modifyBtn.addEventListener("click", () => {
        startModifyFromSlot(item.slot_id).catch((e) => {
          $("statusLine").textContent = e.message;
          $("statusLine").className = "hint err";
        });
      });
    }
    gallery.appendChild(node);
  });
  const summary = state.history.summary || {};
  const hist = state.history.generation || {};
  const summaryEl = $("historySummary");
  if (summaryEl) {
    summaryEl.textContent = `共 ${summary.poster_count || 0} 条记录（成功 ${summary.completed_count || 0}）`;
  }
}

function showBatchResults(job) {
  const items = job?.items || [];
  const box = $("latestPreview");
  const titleEl = $("previewPanelTitle");
  if (!items.length) {
    box.classList.add("empty");
    box.innerHTML = PREVIEW_PLACEHOLDER;
    if (titleEl) titleEl.textContent = "最新成品";
    return;
  }
  if (items.length === 1) {
    if (titleEl) titleEl.textContent = "最新成品";
    showLatest(items[0], job.slot_status);
    return;
  }
  const completed = items.filter((item) => item.status === "completed" && item.image_path).length;
  if (titleEl) titleEl.textContent = `批量成品（${completed}/${items.length}）`;
  box.classList.remove("empty");
  box.innerHTML = `<div class="batch-preview-grid">${items
    .map((item) => {
      const title = cleanTitle(item.title, "未命名作品");
      const failed = item.status !== "completed" || !item.image_path;
      if (failed) {
        return `<article class="batch-preview-card failed">
          <div class="batch-preview-meta">
            <strong>${esc(title)}</strong>
            <span>${esc(item.error ? `失败：${item.error.slice(0, 48)}` : statusText(item.status))}${item.credit_refunded ? " · 额度已退" : ""}</span>
          </div>
        </article>`;
      }
      return `<article class="batch-preview-card">
        <a href="${esc(item.image_path)}" target="_blank" rel="noreferrer"><img src="${esc(item.image_path)}" alt="${esc(title)}" /></a>
        <div class="batch-preview-meta">
          <strong>${esc(title)}</strong>
          <span>${statusText(item.status)}${item.batch_index ? ` · 第 ${item.batch_index}/${item.batch_total || items.length} 张` : ""}</span>
          <a href="${esc(item.image_path)}" target="_blank" rel="noreferrer">下载</a>
        </div>
      </article>`;
    })
    .join("")}</div>`;
}

function showLatest(item, slotStatus) {
  const box = $("latestPreview");
  if (!item?.image_path) {
    box.classList.add("empty");
    box.innerHTML = item?.error
      ? `<p class="preview-error">生成失败：${item.error}</p><p class="hint">${item.credit_refunded ? "额度已自动退还。" : ""}</p>`
      : PREVIEW_PLACEHOLDER;
    if (slotStatus) updateModifyUI(slotStatus);
    return;
  }
  box.classList.remove("empty");
  const title = cleanTitle(item.title, "最新成品");
  box.innerHTML = `<div class="gen-preview-frame">
    <img src="${esc(item.image_path)}" alt="${esc(title)}" />
    <div class="gen-preview-actions">
      <a class="btn ghost sm" href="${esc(item.image_path)}" download target="_blank" rel="noreferrer">下载</a>
      <a class="btn outline sm" href="/editor.html?src=${encodeURIComponent(item.image_path)}&title=${encodeURIComponent(title)}">图片编辑</a>
    </div>
  </div>`;
  state.activeSlotId = item.slot_id || state.activeSlotId;
  if (slotStatus) {
    if (!state.modifyMode && slotStatus.can_modify) {
      updateModifyUI(slotStatus);
    } else if (state.modifyMode) {
      updateModifyUI(slotStatus);
    }
  }
}

async function loadHistory() {
  if (!state.auth.user) return;
  state.history = await api("/api/history?jobs=200&items=500");
  renderGallery();
  if (state.history.items[0]) showLatest(state.history.items[0]);
}

async function loadPaymentsModal() {
  if (!state.auth.user) {
    $("loginModal").showModal();
    return;
  }
  const data = await api("/api/user/payments");
  const plans = state.config.payment_plans || {};
  const list = $("paymentsList");
  const rows = data.payments || [];
  if (!rows.length) {
    list.innerHTML = '<p class="hint">暂无支付记录</p>';
  } else {
    list.innerHTML = rows
      .map((p) => {
        const plan = plans[p.plan_id] || {};
        return `<article class="payment-row">
          <div><strong>${plan.name || p.plan_id}</strong> · ¥${p.amount}</div>
          <div class="hint">${new Date(p.created_at * 1000).toLocaleString()} · ${statusText(p.status)} · +${p.credits || 0} 次</div>
        </article>`;
      })
      .join("");
  }
  $("paymentsModal").showModal();
}

async function autoGeneratePrompt() {
  const btn = $("autoPromptBtn");
  const hint = $("autoPromptHint");
  const title = $("singleTitleInput")?.value.trim() || "";
  const existing = $("singlePromptInput")?.value.trim() || "";
  const command = [title, existing].filter(Boolean).join("\n");
  if (command.length < 2) {
    if (hint) {
      hint.textContent = "先写一句主题";
      hint.className = "hint err";
    }
    return;
  }
  if (!promptLoginForFeature(hint, "请先登录后再使用智能生成")) return;
  if (btn) btn.disabled = true;
  if (hint) {
    hint.textContent = "正在生成...";
    hint.className = "hint";
  }
  try {
    const data = await api("/api/prompts/auto", {
      method: "POST",
      body: JSON.stringify({
        command,
        campaign_name: $("campaignName")?.value.trim() || "",
        template_key: $("templateKey")?.value.trim() || "",
        subject: $("subject")?.value.trim() || "",
        audience: $("audience")?.value.trim() || "",
        size: getPosterSizePayload(),
      }),
    });
    if ($("singlePromptInput")) $("singlePromptInput").value = data.prompt || "";
    if (hint) {
      hint.textContent = "已生成";
      hint.className = "hint ok";
    }
  } catch (err) {
    if (hint) {
      hint.textContent = err.message;
      hint.className = "hint err";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function autoPlanBatchPrompt() {
  const btn = $("autoBatchPlanBtn");
  const hint = $("autoBatchPlanHint");
  const max = state.config.max_items_per_job || 100;
  const count = Math.max(2, Math.min(max, Number($("batchPlanCount")?.value || 6)));
  const style = $("batchPromptInput")?.value.trim() || "";
  const existingItems = $("batchItemsInput")?.value.trim() || "";
  const command = [
    $("campaignName")?.value.trim() || "",
    $("subject")?.value.trim() || "",
    $("audience")?.value.trim() || "",
    style,
    existingItems,
  ].filter(Boolean).join("\n");
  if (command.length < 2) {
    if (hint) {
      hint.textContent = "请先在「系列风格」或上方项目信息里写一句总体需求";
      hint.className = "hint err";
    }
    return;
  }
  if (!promptLoginForFeature(hint, "请先登录后再使用智能拆分")) return;
  if (btn) btn.disabled = true;
  if (hint) {
    hint.textContent = "正在拆分主题，请稍候…";
    hint.className = "hint";
  }
  try {
    const data = await api("/api/prompts/batch-plan", {
      method: "POST",
      body: JSON.stringify({
        command,
        count,
        campaign_name: $("campaignName")?.value.trim() || "",
        template_key: $("templateKey")?.value.trim() || "",
        subject: $("subject")?.value.trim() || "",
        audience: $("audience")?.value.trim() || "",
        size: getPosterSizePayload(),
      }),
    });
    const items = Array.isArray(data.items) ? data.items : [];
    state.batchPlanItems = items;
    if ($("batchItemsInput")) $("batchItemsInput").value = items.map((item) => item.title).join("\n");
    if ($("batchPromptInput")) $("batchPromptInput").value = data.series_style || style || command;
    updateModeUI();
    if (hint) {
      hint.textContent = `已拆分 ${items.length} 张，请核对清单后点击开始批量生成`;
      hint.className = "hint ok";
    }
  } catch (err) {
    state.batchPlanItems = [];
    if (hint) {
      hint.textContent = err.message;
      hint.className = "hint err";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function loadInitial() {
  bootstrapPage();
  try {
    const [config, templates] = await Promise.all([api("/api/config"), api("/api/templates")]);
    state.config = { ...state.config, ...config };
    if (config.plans?.length) state.config.plans = config.plans;
    if (templates.templates?.length) state.templates = templates.templates;
    renderTemplates();
    renderPosterSizes();
    setGenerationMode("single");
    renderGenerationHint();
    syncAuthUI();
    await loadHistory();
  } catch (e) {
    const line = $("statusLine");
    if (line) {
      line.textContent = `在线数据加载失败：${e.message}（已显示默认套餐与模板，生成功能可能受限）`;
      line.className = "hint err";
    }
    console.error("loadInitial", e);
  }
}

async function createJob(isModify = false) {
  const button = $("generateBtn");
  const modifyBtn = $("modifyBtn");
  button.disabled = true;
  modifyBtn.disabled = true;
  const gen = state.config.generation || {};
  const isBatch = isBatchMode() && !isModify;
  const batchTitles = isBatch ? resolveBatchTitles() : resolveSingleTitle();
  const promptText = isBatch
    ? $("batchPromptInput")?.value.trim() || ""
    : $("singlePromptInput")?.value.trim() || "";
  const label = isModify
    ? "正在按修改要求重新生成..."
    : isBatch
      ? `正在批量生成 ${batchTitles.length} 张同系列海报，约需 ${batchTitles.length * (gen.typical_minutes || 2)} 分钟，请稍候...`
      : "正在生成设计图，通常 1-3 分钟，请稍候...";
  if (isModify) modifyBtn.textContent = label;
  else button.textContent = label;
  try {
    if (isBatch) {
      if (batchTitles.length < 2) throw new Error("批量生成至少需要 2 行主题，请在系列清单中每行填写一张。");
      if (promptText.length < 4) throw new Error("请填写系列风格，说明全系列统一的配色、版式和结构。");
      const batchCollage = detectBatchCollageRisk(promptText, batchTitles);
      if (batchCollage) throw new Error(batchCollage);
    } else if (!isModify) {
      const title = batchTitles[0] || "";
      if (promptText.length < 4 && title.length < 2) {
        throw new Error("请填写设计主题，或在补充说明中描述要生成的内容。");
      }
      const collageRisk = detectCollageRisk(promptText);
      if (collageRisk) throw new Error(collageRisk);
    }
    const payload = {
      campaign_name: $("campaignName").value.trim() || autoCampaignName(),
      template_key: $("templateKey").value.trim(),
      subject: $("subject").value.trim(),
      audience: $("audience").value.trim(),
      size: getPosterSizePayload(),
      items: batchTitles,
      prompt_text: promptText,
      generation_mode: isBatch ? "batch" : "single",
      slot_id: isModify ? state.activeSlotId : undefined,
      modify: isModify,
      modify_notes: isModify ? $("modifyNotes").value.trim() : "",
      reference_images: isModify ? [] : state.referenceImages,
    };
    const plannedItems = isBatch ? batchPlanPayloadFor(batchTitles) : [];
    if (plannedItems.length === batchTitles.length) payload.planned_items = plannedItems;
    const bucketId = getCreditBucketPayload(isModify);
    if (bucketId) payload.credit_bucket_id = bucketId;
    const apiPath = isBatch ? "/api/jobs/batch" : "/api/jobs";
    const job = await api(apiPath, { method: "POST", body: JSON.stringify(payload) });
    const items = job.items || [];
    const item = items[0];
    if (!isBatch) {
      state.activeSlotId = job.slot_id || item?.slot_id;
    } else {
      state.activeSlotId = null;
      exitModifyMode();
    }
    state.auth.usage = job.usage || state.auth.usage;
    if (job.credit_buckets) {
      state.creditBuckets = job.credit_buckets;
      state.auth.credit_buckets = job.credit_buckets;
    }
    syncAuthUI();
    const slotStatus = job.slot_status;
    if (isBatch) {
      const completed = items.filter((row) => row.status === "completed").length;
      const failed = items.length - completed;
      const refunded = items.filter((row) => row.credit_refunded).length;
      if (completed === items.length) {
        $("statusLine").textContent = `批量完成：${completed} 张同系列海报已生成，视觉风格已统一。`;
        $("statusLine").className = "hint ok";
      } else if (completed > 0) {
        $("statusLine").textContent = `部分完成：成功 ${completed} 张，失败 ${failed} 张${refunded ? `，已退还 ${refunded} 次额度` : ""}。`;
        $("statusLine").className = "hint err";
      } else {
        $("statusLine").textContent = `批量生成失败${refunded ? "，额度已退还" : ""}。`;
        $("statusLine").className = "hint err";
      }
      showBatchResults(job);
    } else if (item?.error) {
      $("statusLine").textContent = `生成失败：${item.error}${item.credit_refunded ? "（额度已退还）" : ""}`;
      $("statusLine").className = "hint err";
      if (!isModify) exitModifyMode();
      showLatest(item, slotStatus);
    } else {
      const dur = item.duration_ms ? `，耗时约 ${Math.round(item.duration_ms / 1000)} 秒` : "";
      const action = isModify ? "已按修改要求更新" : "已生成";
      $("statusLine").textContent = `「${item.title}」${action}${dur}。`;
      $("statusLine").className = "hint ok";
      if (!isModify && slotStatus?.can_modify) {
        enterModifyMode(slotStatus);
      } else if (isModify && slotStatus) {
        updateModifyUI(slotStatus);
        $("modifyNotes").value = "";
      }
      showLatest(item, slotStatus);
    }
    await loadHistory();
    if (!isModify) {
      state.referenceImages = [];
      renderReferencePreview();
      syncReferenceName();
    }
  } catch (e) {
    $("statusLine").textContent = e.message;
    $("statusLine").className = "hint err";
    if (/生成会话无效|会话无效/.test(e.message)) {
      exitModifyMode();
      $("statusLine").textContent = "上一次生成会话已过期，已自动切换为新建设计图，请重新提交。";
    }
  } finally {
    button.disabled = false;
    modifyBtn.disabled = false;
    updateModeUI();
    if (state.slotStatus) updateModifyUI(state.slotStatus);
  }
}

function bindEvents() {
  $("creditBucketSelect")?.addEventListener("change", (e) => {
    state.selectedCreditBucketId = e.target.value;
    updateCreditBucketHint();
  });
  $("posterForm").addEventListener("submit", (e) => {
    e.preventDefault();
    if (!state.auth.user) {
      $("registerModal").showModal();
      return;
    }
    if (state.modifyMode) return;
    createJob(false);
  });
  $("modifyBtn").addEventListener("click", async () => {
    if (!state.auth.user) {
      $("loginModal").showModal();
      return;
    }
    if (!state.modifyMode && state.activeSlotId) {
      try {
        const slotStatus = await api(`/api/slots/${state.activeSlotId}`);
        enterModifyMode(slotStatus);
      } catch (e) {
        $("statusLine").textContent = e.message;
        $("statusLine").className = "hint err";
      }
      return;
    }
    createJob(true);
  });
  $("newPosterBtn").addEventListener("click", () => {
    exitModifyMode();
    $("statusLine").textContent = "已切换为新建设计图，可修改主题后重新生成。";
    $("statusLine").className = "hint";
  });
  $("refreshBtn").addEventListener("click", loadHistory);
  $("myPaymentsBtn")?.addEventListener("click", () => loadPaymentsModal().catch((e) => {
    $("statusLine").textContent = e.message;
    $("statusLine").className = "hint err";
  }));
  $("paymentsClose")?.addEventListener("click", () => $("paymentsModal").close());
  $("paymentsCloseX")?.addEventListener("click", () => $("paymentsModal").close());
  $("referencePickBtn")?.addEventListener("click", () => $("referenceImages").click());
  $("autoPromptBtn")?.addEventListener("click", autoGeneratePrompt);
  $("posterSize")?.addEventListener("change", () => {
    if ($("posterSize").value === "custom") {
      if (!$("customWidth")?.value) $("customWidth").value = "1600";
      if (!$("customHeight")?.value) $("customHeight").value = "2400";
    }
    syncCustomSizeFields();
  });
  $("templateKey")?.addEventListener("change", () => {
    renderTemplateTiles();
    syncQuoteCardDefaults();
  });
  $("singlePromptInput")?.addEventListener("input", () => {
    syncQuoteCardDefaults();
  });
  $("batchPromptInput")?.addEventListener("input", () => {
    syncQuoteCardDefaults();
    updateModeUI();
  });
  $("batchItemsInput")?.addEventListener("input", () => {
    state.batchPlanItems = [];
    const titles = parseBatchTitles($("batchItemsInput")?.value);
    if (titles.some((line) => line.includes("|")) && !$("templateKey")?.value) {
      $("templateKey").value = "business-quote-card";
      renderTemplateTiles();
      syncQuoteCardDefaults();
    }
    updateModeUI();
  });
  $("autoBatchPlanBtn")?.addEventListener("click", autoPlanBatchPrompt);
  $("modeSingleBtn")?.addEventListener("click", () => setGenerationMode("single"));
  $("modeBatchBtn")?.addEventListener("click", () => {
    if (state.modifyMode) return;
    setGenerationMode("batch");
  });
  $("clearTemplateBtn")?.addEventListener("click", () => {
    if ($("templateKey")?.disabled) return;
    $("templateKey").value = "";
    renderTemplateTiles();
  });
  $("expandAllTemplates")?.addEventListener("click", () => {
    state.templateGroupsTouched = true;
    state.openTemplateGroups = new Set(TEMPLATE_GROUPS.map((_, i) => i));
    renderTemplateTiles();
  });
  $("collapseAllTemplates")?.addEventListener("click", () => {
    state.templateGroupsTouched = true;
    state.openTemplateGroups = new Set();
    renderTemplateTiles();
  });
  $("referenceImages")?.addEventListener("change", (e) => {
    pickReferenceImages(e.target.files).catch((err) => {
      $("statusLine").textContent = err.message;
      $("statusLine").className = "hint err";
    });
    e.target.value = "";
  });
}

export function openPayment(planId) {
  const plan = (state.config.plans || []).find((p) => p.id === planId);
  if (plan?.payment_disabled === true) return;
  state.selectedPlanId = planId;
  window.dispatchEvent(new CustomEvent("poster:open-payment", { detail: planId }));
}

window.openPayment = openPayment;

bindEvents();
loadInitial();

