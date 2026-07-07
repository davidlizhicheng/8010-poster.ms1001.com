try {
  await new Promise((resolve, reject) => {
    if (window.suatAccessToken) return resolve();
    const script = document.createElement("script");
    script.src = "/suat_auth_redirect.js?v=2";
    script.onload = resolve;
    script.onerror = reject;
    document.head.appendChild(script);
  });
} catch {
  /* auth.js must still load if suat helper is unavailable */
}

if (!window.suatAccessToken) {
  window.suatAccessToken = () => localStorage.getItem("suat_access_token") || "";
}
if (!window.suatAppendTokenToUrl) {
  window.suatAppendTokenToUrl = (url, token) => {
    if (!token || !url) return url || "/";
    const base = String(url).split("#")[0];
    return `${base}#access_token=${encodeURIComponent(token)}`;
  };
}

function captureUnifiedTokenFromUrl() {
  if (typeof window.suatCaptureTokenFromUrl === "function") {
    return window.suatCaptureTokenFromUrl();
  }
  const tokenParams = ["access_token", "token", "accessToken"];
  const readToken = (params) => {
    for (const key of tokenParams) {
      const value = params.get(key);
      if (value) return value;
    }
    return "";
  };
  const hash = location.hash.replace(/^#/, "");
  if (hash) {
    const token = readToken(new URLSearchParams(hash));
    if (token) {
      localStorage.setItem("suat_access_token", token);
      history.replaceState(null, "", location.pathname + location.search);
      return token;
    }
  }
  const queryToken = readToken(new URLSearchParams(location.search));
  if (queryToken) {
    localStorage.setItem("suat_access_token", queryToken);
    history.replaceState(null, "", location.pathname);
    return queryToken;
  }
  return localStorage.getItem("suat_access_token") || "";
}

let authState = { user: null, usage: null };
let paymentScreenshotData = "";
let selectedPlanId = "single_50";
let paymentMode = "qr_screenshot";
let wechatPayReady = false;
let centralBillingUrl = "";
let unifiedAuthUrl = "";
let useUnifiedAuth = false;
let activeWechatClaimId = "";
let wechatPollTimer = null;

const $ = (id) => document.getElementById(id);

function isLoopbackUrl(url) {
  try {
    const h = new URL(url).hostname;
    return h === "localhost" || h === "127.0.0.1";
  } catch {
    return false;
  }
}

function sanitizePublicUrl(url, fallback) {
  const cleaned = String(url || "").replace(/\/$/, "");
  const host = window.location.hostname;
  const onLocal = host === "localhost" || host === "127.0.0.1";
  if (cleaned && !(isLoopbackUrl(cleaned) && !onLocal)) return cleaned;
  return fallback;
}

function resolveUnifiedAuthBase() {
  const host = window.location.hostname;
  const fallback =
    host === "localhost" || host === "127.0.0.1" ? "http://127.0.0.1:3000" : "https://ai.ms1001.com";
  return sanitizePublicUrl(unifiedAuthUrl, fallback);
}

function isUnifiedAuthMode() {
  if (useUnifiedAuth) return true;
  const host = window.location.hostname;
  return host === "localhost" || host === "127.0.0.1" || host.endsWith(".ms1001.com") || host === "ms1001.com";
}

function unifiedLoginUrl(tab = "login", redirectUrl = "") {
  const base = resolveUnifiedAuthBase();
  const redirect = encodeURIComponent(redirectUrl || window.location.href);
  const tabParam = tab === "register" ? "&tab=register" : "";
  return `${base}/login?redirect=${redirect}${tabParam}`;
}

function navigateToUnifiedLogin(tab = "login", redirectUrl = "") {
  window.location.href = unifiedLoginUrl(tab, redirectUrl);
}

export { navigateToUnifiedLogin, isUnifiedAuthMode };

let authBound = false;
let headerAuthDelegationBound = false;

function bindHeaderAuthDelegation() {
  if (headerAuthDelegationBound) return;
  headerAuthDelegationBound = true;
  document.addEventListener("click", (e) => {
    if (e.target.closest("#authEntryBtn")) {
      if (isUnifiedAuthMode()) {
        navigateToUnifiedLogin("login");
      } else {
        $("loginHint").textContent = "";
        $("loginModal")?.showModal();
      }
      return;
    }
    if (e.target.closest("#accountBtn")) {
      e.preventDefault();
      window.location.href = accountCenterUrl();
      return;
    }
    if (e.target.closest("#logoutBtn")) {
      logoutSession().catch(() => applyAuthState({ user: null, usage: null, credit_buckets: [] }));
    }
  });
}

export function ensureAuthBound() {
  bindHeaderAuthDelegation();
  if (authBound) return;
  if (!document.getElementById("loginModal") && !document.getElementById("paymentModal")) return;
  bindAuth();
  authBound = true;
}

bindHeaderAuthDelegation();

async function logoutSession() {
  localStorage.removeItem("suat_access_token");
  await api("/api/auth/logout", { method: "POST" }).catch(() => {});
  if (isUnifiedAuthMode()) {
    const base = resolveUnifiedAuthBase();
    try {
      await fetch(`${base}/api/auth/logout`, {
        method: "POST",
        credentials: "include",
        headers: { Accept: "application/json" },
      });
    } catch {
      /* ignore cross-origin errors */
    }
    const host = window.location.hostname;
    if (host.endsWith("ms1001.com") || host === "ms1001.com") {
      const secure = window.location.protocol === "https:" ? "; Secure" : "";
      document.cookie = `suat_auth=; Path=/; Domain=.ms1001.com; Max-Age=0; SameSite=Lax${secure}`;
    }
  }
  applyAuthState({ user: null, usage: null, credit_buckets: [] });
}

function accountCenterUrl() {
  const base = resolveUnifiedAuthBase();
  const token = getStoredUnifiedToken();
  const url = `${base}/account.html`;
  if (token && window.suatAppendTokenToUrl) return window.suatAppendTokenToUrl(url, token);
  return url;
}

function setAuthElVisible(id, visible) {
  const el = $(id);
  if (!el) return;
  el.classList.toggle("auth-hidden", !visible);
}

function usageChipLabel(user, usage) {
  if (usage?.owner_vip || user?.owner_vip) return "老板 VIP · 无限权限";
  if (usage?.credits != null && !usage?.owner_vip) return `剩余 ${usage.credits} 次`;
  if (usage?.plan_label) {
    const first = String(usage.plan_label).split(" · ")[0];
    if (first.includes("剩余") || first.includes("无限")) return first;
  }
  return user ? "已登录" : "";
}

function getStoredUnifiedToken() {
  return window.suatAccessToken?.() || localStorage.getItem("suat_access_token") || "";
}

function storeUnifiedToken(token) {
  if (!token) return;
  localStorage.setItem("suat_access_token", token);
}

async function ensureUnifiedToken() {
  const existing = getStoredUnifiedToken();
  if (existing) return existing;
  if (!authState.user) return "";
  try {
    const data = await api("/api/auth/unified/refresh-token", { method: "POST" });
    if (data.token) {
      storeUnifiedToken(data.token);
      return data.token;
    }
  } catch {
    /* ignore */
  }
  return "";
}

function buildBillingUrl(planId) {
  if (!centralBillingUrl || planId === "trial_001") return "";
  const url = new URL(centralBillingUrl, window.location.origin);
  url.searchParams.set("platform", "poster.ms1001.com");
  url.searchParams.set("plan", planId);
  if (planId === "bulk") {
    url.searchParams.set("quantity", String(Math.max(20, Number($("bulkQuantity")?.value || 20))));
  }
  url.searchParams.set("return", window.location.href);
  return url.toString();
}

async function centralBillingTarget(planId) {
  const baseUrl = buildBillingUrl(planId);
  if (!baseUrl) return "";
  const token = await ensureUnifiedToken();
  if (token) return window.suatAppendTokenToUrl?.(baseUrl, token) || baseUrl;
  return baseUrl;
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const token = window.suatAccessToken?.() || localStorage.getItem("suat_access_token") || "";
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, {
    credentials: "include",
    headers,
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data.error || (res.status === 404 ? "接口未找到，请重启 Poster 服务后再试" : `请求失败 (${res.status})`);
    throw new Error(msg);
  }
  return data;
}

function applyAuthState(data) {
  authState = {
    user: data.user,
    usage: data.usage,
    credit_buckets: data.credit_buckets || [],
  };
  window.__posterUser = data.user;
  syncHeaderAuthUI(authState);
  window.dispatchEvent(new CustomEvent("poster:auth", { detail: authState }));
}

export function getAuthState() {
  return authState;
}

export function syncHeaderAuthUI(state = authState) {
  const user = state?.user;
  const usage = state?.usage;
  const loggedIn = Boolean(user);

  setAuthElVisible("authEntryBtn", !loggedIn);
  setAuthElVisible("accountBtn", loggedIn);
  setAuthElVisible("logoutBtn", loggedIn);

  const accountBtn = $("accountBtn");
  if (accountBtn) accountBtn.href = accountCenterUrl();

  const welcomeBar = $("authWelcomeBar");
  const welcomeText = $("authWelcomeText");
  const chip = $("usageChip");

  if (loggedIn && welcomeBar && welcomeText) {
    welcomeBar.classList.remove("auth-hidden");
    welcomeText.textContent =
      user.owner_greeting || user.display_name || user.org || (user.phone ? `欢迎，${user.phone}` : "已登录");
    welcomeText.classList.toggle("owner-vip", Boolean(user.owner_vip || usage?.owner_vip));

    const chipLabel = usageChipLabel(user, usage);
    if (chip && chipLabel) {
      chip.classList.remove("auth-hidden");
      chip.textContent = chipLabel;
      chip.classList.toggle("owner-vip", Boolean(usage?.owner_vip || user?.owner_vip));
    } else {
      chip?.classList.add("auth-hidden");
    }
  } else {
    welcomeBar?.classList.add("auth-hidden");
    chip?.classList.add("auth-hidden");
    if (welcomeText) welcomeText.textContent = "";
  }

  document.body.classList.toggle("poster-logged-in", loggedIn);
  document.body.classList.toggle("poster-owner-vip", Boolean(user?.owner_vip || usage?.owner_vip));
}

export async function refreshAuth() {
  const data = await api("/api/auth/me");
  applyAuthState(data);
  if (data.user) await ensureUnifiedToken();
  return authState;
}

async function loadPaymentConfig() {
  try {
    const cfg = await api("/api/config");
    paymentMode = cfg.payment_mode || "qr_screenshot";
    wechatPayReady = Boolean(cfg.wechat_pay_ready);
    const host = window.location.hostname;
    const authFallback =
      host === "localhost" || host === "127.0.0.1" ? "http://127.0.0.1:3000" : "https://ai.ms1001.com";
    unifiedAuthUrl = sanitizePublicUrl(cfg.unified_auth_url, authFallback);
    centralBillingUrl = sanitizePublicUrl(cfg.central_billing_url, `${unifiedAuthUrl}/billing`);
    useUnifiedAuth = Boolean(cfg.use_unified_auth);
    window.__posterPaymentMode = paymentMode;
    window.__posterWechatPayReady = wechatPayReady;
    window.__posterUnifiedAuthUrl = unifiedAuthUrl;
  } catch {
    paymentMode = "qr_screenshot";
    wechatPayReady = false;
    centralBillingUrl = "";
    unifiedAuthUrl = "";
    useUnifiedAuth = false;
  }
}

function planAmount(planId, bulkQty) {
  if (planId === "bulk") return Math.max(20, Number(bulkQty || 20)) * 10;
  const map = {
    trial_001: 0,
    single_50: 50,
    pack_20: 300,
    pack_100: 1000,
    consult_5000: 5000,
    vip_10000: 10000,
  };
  return map[planId] || 50;
}

function stopWechatPolling() {
  if (wechatPollTimer) {
    clearInterval(wechatPollTimer);
    wechatPollTimer = null;
  }
}

function setPaymentModeUi() {
  const native = wechatPayReady;
  const manualDisabled = !native;
  const hint = $("paymentModeHint");
  const screenshotBlock = $("paymentScreenshotBlock");
  const phoneBlock = $("paymentPhoneBlock");
  const submitBtn = $("paymentSubmit");
  if (hint) {
    hint.textContent = native
      ? "请使用微信「扫一扫」扫描左侧官方支付码（不支持长按识别或相册识别）。支付成功后额度将自动到账。"
      : "手工付款截图已关闭。请返回套餐页，通过 ai.ms1001.com 统一收银台发起微信 Native 支付。";
  }
  if (screenshotBlock) screenshotBlock.hidden = native || manualDisabled;
  if (phoneBlock) phoneBlock.hidden = native || manualDisabled;
  if (submitBtn) submitBtn.textContent = native ? "刷新支付状态" : "统一收银台支付";
}

async function syncPaymentUi() {
  const bulk = selectedPlanId === "bulk";
  $("bulkFields").hidden = !bulk;
  const qty = Number($("bulkQuantity")?.value || 20);
  const amount = planAmount(selectedPlanId, qty);
  $("paymentAmountText").textContent = `应付 ¥${amount}`;
  if ($("bulkAmountHint")) $("bulkAmountHint").textContent = `应付 ¥${amount}（${qty} 张）`;
  setPaymentModeUi();
  if (wechatPayReady) {
    await createWechatNativeOrder();
  } else {
    try {
      const { qr_url } = await api(`/api/payment/qr?plan=${selectedPlanId}`);
      $("paymentQrImage").src = qr_url;
    } catch {
      $("paymentQrImage").src = "/assets/qr-pay.svg";
    }
  }
  syncPaymentSubmit();
}

async function createWechatNativeOrder() {
  stopWechatPolling();
  $("paymentHint").textContent = "正在创建微信官方订单…";
  $("paymentHint").className = "hint";
  $("paymentSubmit").disabled = true;
  try {
    const order = await api("/api/payment/wechat/native/create", {
      method: "POST",
      body: JSON.stringify({
        plan_id: selectedPlanId,
        contract_accepted: true,
        bulk_quantity: selectedPlanId === "bulk" ? Math.max(20, Number($("bulkQuantity")?.value || 20)) : undefined,
      }),
    });
    activeWechatClaimId = order.id;
    $("paymentQrImage").src = order.qr_image_url || "/assets/qr-pay.svg";
    $("paymentHint").textContent = order.message || "请使用微信扫一扫完成支付。";
    $("paymentHint").className = "hint";
    wechatPollTimer = setInterval(() => {
      pollWechatPaymentStatus().catch(() => {});
    }, 2500);
    syncPaymentSubmit();
  } catch (err) {
    $("paymentHint").textContent = err.message;
    $("paymentHint").className = "hint err";
    $("paymentQrImage").src = "/assets/qr-pay.svg";
    syncPaymentSubmit();
  }
}

async function pollWechatPaymentStatus() {
  if (!activeWechatClaimId) return;
  const data = await api(`/api/payment/wechat/status/${activeWechatClaimId}`);
  const claim = data.claim || {};
  if (claim.status === "approved") {
    stopWechatPolling();
    $("paymentHint").textContent = claim.message || "支付成功，额度已到账。";
    $("paymentHint").className = "hint ok";
    if (data.usage) {
      authState.usage = data.usage;
      window.dispatchEvent(new CustomEvent("poster:auth", { detail: authState }));
    }
    setTimeout(() => $("paymentModal").close(), 1200);
    return;
  }
  if (claim.status === "failed") {
    stopWechatPolling();
    $("paymentHint").textContent = claim.message || "订单已关闭，请关闭弹窗后重新购买。";
    $("paymentHint").className = "hint err";
  }
}

function syncPaymentSubmit() {
  const bulkOk = selectedPlanId !== "bulk" || Number($("bulkQuantity")?.value || 0) >= 20;
  if (wechatPayReady) {
    $("paymentSubmit").disabled = !activeWechatClaimId;
    return;
  }
  $("paymentSubmit").disabled = true;
}

function paymentPhoneOk() {
  return /^1\d{10}$/.test(String($("paymentPhone")?.value || "").replace(/\D/g, ""));
}

function readScreenshotFile(file) {
  return new Promise((resolve, reject) => {
    if (!file) return reject(new Error("请选择支付截图"));
    if (!/^image\/(jpeg|png|webp)$/i.test(file.type)) return reject(new Error("请上传 JPG、PNG 或 WebP"));
    if (file.size > 4 * 1024 * 1024) return reject(new Error("截图不能超过 4MB"));
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("读取截图失败"));
    reader.readAsDataURL(file);
  });
}

function syncRegisterSubmit() {
  $("registerSubmit").disabled = !$("registerAgree")?.checked;
}

function bindAuth() {
  $("loginCancel")?.addEventListener("click", () => $("loginModal").close());
  $("loginClose")?.addEventListener("click", () => $("loginModal").close());
  $("registerCancel")?.addEventListener("click", () => $("registerModal").close());
  $("registerClose")?.addEventListener("click", () => $("registerModal").close());
  $("registerAgree")?.addEventListener("change", syncRegisterSubmit);

  $("loginSubmit")?.addEventListener("click", async () => {
    $("loginHint").textContent = "";
    const phone = $("loginPhone").value.trim();
    const password = $("loginPassword").value.trim();
    if (!/^1\d{10}$/.test(phone.replace(/\D/g, ""))) {
      $("loginHint").textContent = "请填写正确的 11 位手机号";
      return;
    }
    if (!password) {
      $("loginHint").textContent = "请填写密码";
      return;
    }
    try {
      const data = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ phone, password }),
      });
      applyAuthState(data);
      $("loginModal").close();
    } catch (err) {
      $("loginHint").textContent = err.message;
    }
  });

  $("registerSubmit")?.addEventListener("click", async () => {
    $("registerHint").textContent = "";
    const phone = $("regPhone").value.trim();
    const wechat = $("regWechat").value.trim();
    const org = $("regOrg").value.trim();
    const password = $("regPassword").value.trim();
    if (!/^1\d{10}$/.test(phone.replace(/\D/g, ""))) {
      $("registerHint").textContent = "请填写正确的 11 位手机号";
      return;
    }
    if (wechat.length < 2) {
      $("registerHint").textContent = "请填写微信号";
      return;
    }
    if (org.length < 2) {
      $("registerHint").textContent = "请填写单位/机构名称";
      return;
    }
    if (password.length < 6) {
      $("registerHint").textContent = "密码至少 6 位";
      return;
    }
    if (!$("registerAgree")?.checked) {
      $("registerHint").textContent = "请先阅读并同意《用户使用须知》";
      return;
    }
    try {
      const data = await api("/api/auth/register", {
        method: "POST",
        body: JSON.stringify({
          phone,
          wechat,
          org,
          password,
          contract_accepted: true,
        }),
      });
      applyAuthState(data);
      $("registerModal").close();
      window.location.href = "/generate.html";
    } catch (err) {
      $("registerHint").textContent = err.message;
    }
  });

  $("paymentCancel")?.addEventListener("click", () => {
    stopWechatPolling();
    $("paymentModal").close();
  });
  $("paymentClose")?.addEventListener("click", () => {
    stopWechatPolling();
    $("paymentModal").close();
  });
  $("paymentAgree")?.addEventListener("change", syncPaymentSubmit);
  $("paymentPhone")?.addEventListener("input", syncPaymentSubmit);
  $("bulkQuantity")?.addEventListener("input", syncPaymentUi);
  $("paymentScreenshotPick")?.addEventListener("click", () => $("paymentScreenshot").click());
  $("paymentScreenshot")?.addEventListener("change", async () => {
    try {
      paymentScreenshotData = await readScreenshotFile($("paymentScreenshot").files?.[0]);
      $("paymentScreenshotPreview").src = paymentScreenshotData;
      $("paymentScreenshotPreview").hidden = false;
      $("paymentScreenshotName").textContent = "已选择截图";
      syncPaymentSubmit();
    } catch (err) {
      paymentScreenshotData = "";
      $("paymentHint").textContent = err.message;
    }
  });

  $("paymentSubmit")?.addEventListener("click", async () => {
    $("paymentHint").textContent = "";
    if (wechatPayReady) {
      try {
        await pollWechatPaymentStatus();
        if ($("paymentHint").className !== "hint ok") {
          $("paymentHint").textContent = "尚未检测到支付成功，请完成扫码后稍候或点击刷新。";
          $("paymentHint").className = "hint";
        }
      } catch (err) {
        $("paymentHint").textContent = err.message;
        $("paymentHint").className = "hint err";
      }
      return;
    }
    try {
      const res = await api("/api/payment/claim", {
        method: "POST",
        body: JSON.stringify({
          plan_id: selectedPlanId,
          screenshot_image: paymentScreenshotData,
          phone: $("paymentPhone").value,
          contract_accepted: $("paymentAgree").checked,
          bulk_quantity: selectedPlanId === "bulk" ? Math.max(20, Number($("bulkQuantity")?.value || 20)) : undefined,
        }),
      });
      $("paymentHint").textContent = res.claim?.message || "提交成功";
      $("paymentHint").className = res.claim?.status === "pending" ? "hint" : "hint ok";
      authState.usage = res.usage;
      window.dispatchEvent(new CustomEvent("poster:auth", { detail: authState }));
      setTimeout(() => $("paymentModal").close(), 1200);
    } catch (err) {
      $("paymentHint").textContent = err.message;
      $("paymentHint").className = "hint err";
    }
  });

  window.addEventListener("poster:open-payment", async (e) => {
    selectedPlanId = e.detail || "single_50";
    const billingBase = buildBillingUrl(selectedPlanId);

    if (!authState.user) {
      if (isUnifiedAuthMode()) {
        sessionStorage.setItem("poster_pending_plan", selectedPlanId);
        const redirectTarget = billingBase || window.location.href;
        navigateToUnifiedLogin("login", redirectTarget);
        return;
      }
      $("loginModal")?.showModal();
      return;
    }

    if (billingBase) {
      const token = await ensureUnifiedToken();
      if (!token) {
        sessionStorage.setItem("poster_pending_plan", selectedPlanId);
        navigateToUnifiedLogin("login", billingBase);
        return;
      }
      window.location.href = window.suatAppendTokenToUrl?.(billingBase, token) || billingBase;
      return;
    }

    paymentScreenshotData = "";
    activeWechatClaimId = "";
    stopWechatPolling();
    $("paymentScreenshot").value = "";
    $("paymentScreenshotPreview").hidden = true;
    $("paymentScreenshotName").textContent = "JPG / PNG / WebP，最大 4MB，提交后默认自动开通";
    $("paymentAgree").checked = wechatPayReady;
    if (selectedPlanId === "bulk" && $("bulkQuantity") && !$("bulkQuantity").value) {
      $("bulkQuantity").value = "20";
    }
    if (authState.user?.phone) $("paymentPhone").value = authState.user.phone;
    syncPaymentUi();
    $("paymentModal").showModal();
  });
}

async function initAuthModule() {
  ensureAuthBound();
  captureUnifiedTokenFromUrl();
  await loadPaymentConfig();
  try {
    await refreshAuth();
    const pending = sessionStorage.getItem("poster_pending_plan");
    if (pending && authState.user) {
      sessionStorage.removeItem("poster_pending_plan");
      window.dispatchEvent(new CustomEvent("poster:open-payment", { detail: pending }));
    }
  } catch {
    syncHeaderAuthUI();
  }
}

export const authReady = initAuthModule();
