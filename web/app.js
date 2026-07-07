const SERVICES = [
  { title: "自媒体素材", desc: "短视频封面、社群配图与信息流广告图，高频刚需" },
  { title: "各类卡片", desc: "学习卡、活动卡、会员卡，日常运营必备" },
  { title: "平面印刷物料", desc: "宣传海报、折页、画册封面与促销主视觉" },
  { title: "活动线下物料", desc: "展架、邀请函、证书与活动主画面" },
  { title: "职场办公图文", desc: "汇报封面、信息长图与流程图解（竖版物料）" },
  { title: "科普教育插画", desc: "知识图解、教学示意与安全科普配图" },
  { title: "IP 文创视觉", desc: "吉祥物延展、贴纸与周边概念图（定制对接）" },
  { title: "空间虚拟效果图", desc: "直播间背景、展厅氛围图（定制对接）" },
  { title: "细分定制设计", desc: "婚礼、宠物、文创等个性场景（尊享包年）" },
];

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
];

const FALLBACK_PLANS = [
  { id: "trial", name: "免费体验", price_label: "¥0", highlight: "新用户专享", desc: "注册即享 1 张海报生成额度", features: ["竖版高清海报", "首张后可修改 5 次", "适合先验质量"] },
  { id: "single_50", name: "单张设计包", price_label: "¥50", highlight: "灵活试水", desc: "1 张成品，同主题可修改 5 次", features: ["单张付费即用", "适合紧急物料", "支持下载 PNG"] },
  { id: "pack_20", name: "20 张套餐", price_label: "¥300", highlight: "热门", desc: "月均活动与社群传播", features: ["20 次独立生成", "适合季度营销活动", "企业机构首选"] },
  { id: "pack_100", name: "100 张套餐", price_label: "¥1000", highlight: "年度储备", desc: "100 次海报额度，须在 3 个月内用完", features: ["100 次独立生成", "适合集中投放季", "支持企业开票"] },
  { id: "consult_5000", name: "包年会员 · 品牌咨询", price_label: "¥5000/年", highlight: "包年", desc: "一年 500 次额度 + 品牌咨询", features: ["500 次设计生成", "须在一年内用完", "线上每月 1 次咨询服务"] },
  { id: "vip_10000", name: "包年会员 · 尊享定制", price_label: "¥10000/年", highlight: "尊享", desc: "每月 20 次额度 + 个性化定制", features: ["每月 20 次设计生成", "365 天服务期内每月刷新", "额外个性化定制服务"] },
  { id: "bulk", name: "企业批量", price_label: "¥10/张", highlight: "¥200 起", desc: "大规模投放与定制批次", features: ["20 张以上 ¥10/张", "公司转账最低 ¥200", "支持 API 参考图"] },
];

let state = {
  config: {},
  templates: [],
  history: { items: [] },
  auth: { user: null, usage: null },
  activeSlotId: null,
  selectedPlanId: "single_50",
  referenceImages: [],
  modifyMode: false,
  slotStatus: null,
};

const THEME_FIELD_IDS = ["campaignName", "subject", "audience", "itemsInput"];

const $ = (id) => document.getElementById(id);

function scrollToSection(sectionId) {
  const el = document.getElementById(sectionId);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

function initPageNav() {
  const header = document.querySelector(".site-header");
  const scrollRoot = document.getElementById("pageScroll");
  const sectionIds = ["top", "about", "services", "pricing", "studio"];

  const onNavClick = (e) => {
    const link = e.target.closest("[data-nav], [data-scroll]");
    if (!link) return;
    e.preventDefault();
    const id = link.dataset.nav || link.dataset.scroll?.replace("#", "");
    if (!id) return;
    scrollToSection(id);
    $("navLinks")?.classList.remove("open");
  };

  document.querySelectorAll("a[href^='#']").forEach((a) => {
    const id = a.getAttribute("href").slice(1);
    if (!sectionIds.includes(id)) return;
    if (!a.dataset.nav) a.dataset.nav = id;
    a.addEventListener("click", onNavClick);
  });
  document.querySelectorAll("[data-scroll]").forEach((el) => el.addEventListener("click", onNavClick));

  if (scrollRoot) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const id = entry.target.id;
          document.querySelectorAll("[data-nav]").forEach((a) => {
            a.classList.toggle("active", a.dataset.nav === id);
          });
          header?.classList.toggle("on-hero", id === "top");
        });
      },
      { root: scrollRoot, threshold: 0.45 }
    );
    sectionIds.forEach((id) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });
  }

  header?.classList.add("on-hero");
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
  return data;
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
  const gen = state.config.generation || {};
  const mods = gen.modifications_per_theme || 5;
  return `通常 1-3 分钟出图；首张生成后同主题可继续优化 ${mods} 次；生成失败会自动退回本次额度。`;
}

function setThemeLocked(locked) {
  THEME_FIELD_IDS.forEach((id) => {
    const el = $(id);
    if (el) el.readOnly = locked;
  });
  const sel = $("templateKey");
  if (sel) sel.disabled = locked;
  $("posterForm")?.classList.toggle("theme-locked", locked);
}

function updateModifyUI(slotStatus) {
  state.slotStatus = slotStatus || state.slotStatus;
  const status = state.slotStatus;
  const mods = state.config.generation?.modifications_per_theme || 5;
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
    return;
  }

  const remaining = status.remaining_modifications ?? 0;
  const used = status.attempts_used ?? 0;
  const canModify = status.can_modify;

  const refLabel = $("referencePickBtn")?.closest("label");
  if (refLabel) refLabel.hidden = state.modifyMode;

  if (state.modifyMode) {
    if (hint) {
      hint.hidden = false;
      hint.textContent = `主题已锁定；已用 ${used}/${status.max_attempts} 次（首张后可修改 ${mods} 次）· 剩余 ${remaining} 次`;
    }
    if (notesWrap) notesWrap.hidden = false;
    if (genBtn) genBtn.hidden = true;
    if (newBtn) newBtn.hidden = false;
    if (modifyBtn) {
      modifyBtn.hidden = false;
      modifyBtn.textContent = remaining > 0 ? `提交修改（剩余 ${remaining} 次）` : "修改次数已用完";
      modifyBtn.disabled = remaining <= 0;
    }
  } else {
    if (notesWrap) notesWrap.hidden = true;
    if (genBtn) genBtn.hidden = false;
    if (newBtn) newBtn.hidden = !state.activeSlotId;
    if (modifyBtn) modifyBtn.hidden = !canModify;
    if (canModify && hint && modifyBtn) {
      hint.hidden = false;
      hint.textContent = `当前主题还可修改 ${remaining} 次`;
      modifyBtn.textContent = `继续修改（剩余 ${remaining} 次）`;
      modifyBtn.disabled = false;
    } else if (hint) {
      hint.hidden = true;
    }
  }
}

function enterModifyMode(slotStatus) {
  state.modifyMode = true;
  state.activeSlotId = slotStatus.slot_id;
  const locked = slotStatus.locked || {};
  $("campaignName").value = locked.campaign_name || $("campaignName").value;
  if (locked.template_key) $("templateKey").value = locked.template_key;
  $("subject").value = locked.subject || "";
  $("audience").value = locked.audience || "";
  $("itemsInput").value = locked.title || "";
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
  updateModifyUI(null);
}

async function startModifyFromSlot(slotId) {
  const slotStatus = await api(`/api/slots/${slotId}`);
  enterModifyMode(slotStatus);
  scrollToSection("studio");
}

function renderGenerationHint() {
  const el = $("generationHint");
  if (el) el.textContent = generationHintText();
}

function renderServices() {
  $("serviceGrid").innerHTML = SERVICES.map(
    (s) => `<article class="service-card"><strong>${s.title}</strong><p>${s.desc}</p></article>`
  ).join("");
}

function renderPricing() {
  const grid = $("pricingGrid");
  if (!grid) return;
  const plans = (state.config.plans || []).length ? state.config.plans : FALLBACK_PLANS;
  if (!plans.length) return;
  grid.innerHTML = plans
    .map((plan) => {
      const features = (plan.features || []).map((f) => `<li>${f}</li>`).join("");
      let cta;
      if (plan.id === "trial") {
        cta = `<button class="btn outline full" type="button" data-action="register">免费注册</button>`;
      } else if (plan.payment_disabled) {
        cta = `<button class="btn outline full" type="button" disabled>即将开放 API</button>
               <p class="price-soon">未来提供 API 接口，暂不能付款</p>`;
      } else {
        cta = `<button class="btn primary full" type="button" data-plan="${plan.id}">立即购买</button>`;
      }
      return `<article class="price-card ${plan.highlight === "热门" ? "featured" : ""}">
        ${plan.highlight ? `<span class="tag">${plan.highlight}</span>` : ""}
        <h3>${plan.name}</h3>
        <div class="price">${plan.price_label}</div>
        <p>${plan.desc}</p>
        <ul>${features}</ul>
        ${cta}
      </article>`;
    })
    .join("");

  bindPricingButtons();
}

function bindPricingButtons() {
  const grid = $("pricingGrid");
  if (!grid) return;
  grid.querySelectorAll("[data-plan]").forEach((btn) => {
    btn.addEventListener("click", () => openPayment(btn.dataset.plan));
  });
  grid.querySelectorAll("[data-action='register']").forEach((btn) => {
    btn.addEventListener("click", () => $("registerModal").showModal());
  });
}

function renderTemplates() {
  const el = $("templateKey");
  if (!el) return;
  const list = state.templates?.length ? state.templates : FALLBACK_TEMPLATES;
  const current = el.value;
  el.innerHTML = list.map((t) => `<option value="${t.key}">${t.name}</option>`).join("");
  if (current && list.some((t) => t.key === current)) el.value = current;
}

function bootstrapPage() {
  renderServices();
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
  renderPricing();
  renderTemplates();
  renderGenerationHint();
}

function syncAuthUI() {
  const user = state.auth.user;
  const usage = state.auth.usage;
  window.__posterUser = user;
  if ($("studioBadge")) {
    $("studioBadge").textContent = user ? user.owner_greeting || user.display_name || user.org || "已登录" : "请先登录";
    $("studioBadge").classList.toggle("ready", Boolean(user));
  }
  const support = [];
  if (state.config.support_phone) support.push(`客服 ${state.config.support_phone}`);
  if (state.config.support_wechat) support.push(`微信 ${state.config.support_wechat}`);
  $("footerSupport").textContent = support.join(" · ");
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
  const max = state.config.max_reference_images || 3;
  const name = $("referenceImagesName");
  if (!name) return;
  if (name) {
    name.textContent = state.referenceImages.length
      ? `已选 ${state.referenceImages.length} 张（最多 ${max} 张，可继续添加）`
      : `用于辅助风格与配色，最多 ${max} 张，每张最大 2MB`;
  }
}

async function pickReferenceImages(fileList) {
  const max = state.config.max_reference_images || 3;
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
  $("latestPreview").innerHTML = "登录后即可使用免费体验额度。";
  $("statusLine").textContent = "登录后即可使用免费体验额度。";
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
      img.alt = item.title;
      img.classList.add("failed-thumb");
      node.classList.add("poster-failed");
    } else {
      link.href = item.image_path;
      img.src = item.image_path;
      img.alt = item.title;
      open.href = item.image_path;
    }
    node.querySelector("h4").textContent = item.title;
    const stateEl = node.querySelector(".poster-state");
    stateEl.textContent = failed
      ? item.error ? `失败：${item.error.slice(0, 40)}` : statusText(item.status)
      : statusText(item.status);
    const modifyBtn = node.querySelector(".modify-item-btn");
    if (failed) open.hidden = true;
    if (!failed && item.can_modify && item.slot_id) {
      modifyBtn.hidden = false;
      modifyBtn.textContent = item.remaining_modifications
        ? `修改（剩 ${item.remaining_modifications}）`
        : "修改";
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

function showLatest(item, slotStatus) {
  const box = $("latestPreview");
  if (!item?.image_path) {
    box.classList.add("empty");
    box.innerHTML = item?.error
      ? `<p class="preview-error">生成失败：${item.error}</p><p class="hint">${item.credit_refunded ? "额度已自动退还。" : ""}</p>`
      : "生成完成后将在此展示";
    if (slotStatus) updateModifyUI(slotStatus);
    return;
  }
  box.classList.remove("empty");
  box.innerHTML = `<img src="${item.image_path}" alt="${item.title}" />`;
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

async function loadInitial() {
  bootstrapPage();
  bindPricingButtons();
  try {
    const [config, templates] = await Promise.all([api("/api/config"), api("/api/templates")]);
    state.config = { ...state.config, ...config };
    if (config.plans?.length) state.config.plans = config.plans;
    if (templates.templates?.length) state.templates = templates.templates;
    if (config.plans?.length) renderPricing();
    renderTemplates();
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
  const label = isModify
    ? "正在按修改要求重新生成..."
    : "正在生成海报，通常 1-3 分钟，请稍候...";
  if (isModify) modifyBtn.textContent = label;
  else button.textContent = label;
  try {
    const payload = {
      campaign_name: $("campaignName").value.trim() || "我的海报",
      template_key: $("templateKey").value,
      subject: $("subject").value.trim(),
      audience: $("audience").value.trim(),
      items: [$("itemsInput").value.trim().split(/\r?\n/)[0]].filter(Boolean),
      slot_id: isModify ? state.activeSlotId : undefined,
      modify: isModify,
      modify_notes: isModify ? $("modifyNotes").value.trim() : "",
      reference_images: isModify ? [] : state.referenceImages,
    };
    const job = await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    const item = job.items[0];
    state.activeSlotId = job.slot_id || item.slot_id;
    state.auth.usage = job.usage || state.auth.usage;
    syncAuthUI();
    const slotStatus = job.slot_status;
    if (item.error) {
      $("statusLine").textContent = `生成失败：${item.error}${item.credit_refunded ? "（额度已退还）" : ""}`;
      $("statusLine").className = "hint err";
      if (!isModify) exitModifyMode();
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
    }
    showLatest(item, slotStatus);
    await loadHistory();
    if (!isModify) {
      state.referenceImages = [];
      renderReferencePreview();
      syncReferenceName();
    }
  } catch (e) {
    $("statusLine").textContent = e.message;
    $("statusLine").className = "hint err";
  } finally {
    button.disabled = false;
    modifyBtn.disabled = false;
    button.textContent = "开始生成海报";
    if (state.slotStatus) updateModifyUI(state.slotStatus);
  }
}

function bindEvents() {
  bindPricingButtons();
  $("pricingGrid")?.addEventListener("click", (e) => {
    const planBtn = e.target.closest("[data-plan]");
    if (planBtn && !planBtn.disabled) openPayment(planBtn.dataset.plan);
    if (e.target.closest("[data-action='register']")) $("registerModal").showModal();
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
    $("statusLine").textContent = "已切换为新建海报，可修改主题后重新生成。";
    $("statusLine").className = "hint";
  });
  $("refreshBtn").addEventListener("click", loadHistory);
  $("myPaymentsBtn")?.addEventListener("click", () => loadPaymentsModal().catch((e) => {
    $("statusLine").textContent = e.message;
    $("statusLine").className = "hint err";
  }));
  $("paymentsClose")?.addEventListener("click", () => $("paymentsModal").close());
  $("referencePickBtn")?.addEventListener("click", () => $("referenceImages").click());
  $("referenceImages")?.addEventListener("change", (e) => {
    pickReferenceImages(e.target.files).catch((err) => {
      $("statusLine").textContent = err.message;
      $("statusLine").className = "hint err";
    });
    e.target.value = "";
  });
  $("navToggle")?.addEventListener("click", () => {
    $("navLinks")?.classList.toggle("open");
  });
  $("navLinks")?.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => $("navLinks")?.classList.remove("open"));
  });
  $("heroStartBtn").addEventListener("click", () => {
    if (!state.auth.user) $("registerModal").showModal();
    else scrollToSection("studio");
  });
  $("heroPricingBtn").addEventListener("click", () => scrollToSection("pricing"));
  $("aboutRegisterBtn")?.addEventListener("click", () => $("registerModal").showModal());
  $("invoiceBtn").addEventListener("click", () => {
    if (!state.auth.user) {
      $("loginModal").showModal();
      return;
    }
    $("invoiceModal").showModal();
  });
  $("invoiceAmount").addEventListener("input", () => {
    const amt = Number($("invoiceAmount").value || 0);
    const fee = state.config.invoice_service_fee || 10;
    $("invoiceTotalHint").textContent = `发票总额：¥${(amt + fee).toFixed(2)}（含人工费 ¥${fee}）`;
  });
  $("invoiceCancel")?.addEventListener("click", () => $("invoiceModal").close());
  $("invoiceSubmit")?.addEventListener("click", async () => {
    $("invoiceHint").textContent = "";
    const company = $("invoiceCompany").value.trim();
    const taxId = $("invoiceTaxId").value.trim();
    const email = $("invoiceEmail").value.trim();
    const amount = Number($("invoiceAmount").value);
    if (company.length < 4) {
      $("invoiceHint").textContent = "请填写完整企业名称";
      return;
    }
    if (taxId.length < 15) {
      $("invoiceHint").textContent = "请填写正确的纳税人识别号";
      return;
    }
    if (!email.includes("@")) {
      $("invoiceHint").textContent = "请填写有效邮箱";
      return;
    }
    if (!amount || amount <= 0) {
      $("invoiceHint").textContent = "请填写开票金额";
      return;
    }
    try {
      const res = await api("/api/invoice/request", {
        method: "POST",
        body: JSON.stringify({
          company_name: company,
          tax_id: taxId,
          contact_email: email,
          invoice_amount: amount,
          note: $("invoiceNote").value,
        }),
      });
      $("invoiceHint").textContent = res.message;
      $("invoiceHint").className = "hint ok";
      setTimeout(() => $("invoiceModal").close(), 1500);
    } catch (err) {
      $("invoiceHint").textContent = err.message;
      $("invoiceHint").className = "hint err";
    }
  });
}

window.addEventListener("poster:auth", (e) => {
  state.auth = e.detail;
  if (!e.detail.user) clearStudioState();
  syncAuthUI();
  if (e.detail.user) loadHistory();
});

export function openPayment(planId) {
  if (planId === "bulk") return;
  const plan = (state.config.plans || []).find((p) => p.id === planId);
  if (plan?.payment_disabled === true) return;
  state.selectedPlanId = planId;
  window.dispatchEvent(new CustomEvent("poster:open-payment", { detail: planId }));
}

window.openPayment = openPayment;

bindEvents();
initPageNav();
bootstrapPage();
loadInitial();

