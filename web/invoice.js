import { initPage } from "/layout.js?v=27";
import {
  authReady,
  getAuthState,
  isUnifiedAuthMode,
  navigateToUnifiedLogin,
  syncHeaderAuthUI,
} from "/auth.js?v=39";

await initPage("invoice");
await authReady;

const $ = (id) => document.getElementById(id);
let eligibleOrders = [];

function authHeaders(extra = {}) {
  const token = window.suatAccessToken?.() || localStorage.getItem("suat_access_token") || "";
  const headers = { Accept: "application/json", ...extra };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function invoiceApi(path, options = {}) {
  const res = await fetch(path, {
    credentials: "include",
    headers: authHeaders({ "Content-Type": "application/json", ...(options.headers || {}) }),
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
  return data;
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleString();
}

function updateInvoiceTotal() {
  const amt = Number($("invoiceAmount").value || 0);
  $("invoiceTotalHint").textContent = `发票总额：¥${(amt + 10).toFixed(2)}（含人工服务费 ¥10）`;
}

function onOrderChange() {
  const order = eligibleOrders.find((o) => o.id === $("invoiceOrderSelect").value);
  if (!order) {
    $("invoiceAmount").value = "";
    updateInvoiceTotal();
    return;
  }
  $("invoiceAmount").value = Number(order.amount || 0).toFixed(2);
  updateInvoiceTotal();
  $("invoiceOrderHint").textContent = `已选：${order.plan_name || order.plan_id} · ${fmtTime(order.created_at)} · ¥${order.amount}`;
}

async function loadEligibleOrders() {
  const data = await invoiceApi("/api/invoice/eligible-payments");
  eligibleOrders = data.payments || [];
  const select = $("invoiceOrderSelect");
  if (!eligibleOrders.length) {
    $("invoicePageForm").hidden = true;
    $("invoiceEmpty").hidden = false;
    return;
  }
  $("invoiceEmpty").hidden = true;
  $("invoicePageForm").hidden = false;
  select.innerHTML = `<option value="">请选择已到账订单</option>${eligibleOrders
    .map((o) => {
      const qty = o.bulk_quantity ? ` · ${o.bulk_quantity} 张` : o.credits ? ` · ${o.credits} 次` : "";
      return `<option value="${o.id}">${o.plan_name || o.plan_id} · ¥${o.amount}${qty} · ${fmtTime(o.created_at)}</option>`;
    })
    .join("")}`;
  onOrderChange();
}

function syncInvoiceView() {
  const user = window.__posterUser || getAuthState().user;
  $("invoiceGuest").hidden = Boolean(user);
  if (!user) {
    $("invoicePageForm").hidden = true;
    $("invoiceEmpty").hidden = true;
    return;
  }
  if (user.org && !$("invoiceCompany").value) {
    $("invoiceCompany").value = user.org;
  }
  loadEligibleOrders().catch((err) => {
    $("invoiceHint").textContent = err.message;
    $("invoiceHint").className = "hint err";
  });
}

window.addEventListener("poster:auth", (e) => {
  window.__posterUser = e.detail.user;
  syncHeaderAuthUI(e.detail);
  syncInvoiceView();
});

$("invoiceAuthBtn")?.addEventListener("click", () => {
  if (isUnifiedAuthMode()) {
    navigateToUnifiedLogin("login", window.location.href);
    return;
  }
  $("loginModal")?.showModal();
});

$("invoiceOrderSelect")?.addEventListener("change", onOrderChange);

$("invoicePageForm")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  $("invoiceHint").textContent = "";
  const paymentClaimId = $("invoiceOrderSelect").value;
  const company = $("invoiceCompany").value.trim();
  const taxId = $("invoiceTaxId").value.trim();
  const email = $("invoiceEmail").value.trim();
  const amount = Number($("invoiceAmount").value);
  if (!paymentClaimId) {
    $("invoiceHint").textContent = "请选择要开票的支付订单";
    $("invoiceHint").className = "hint err";
    return;
  }
  if (company.length < 4) {
    $("invoiceHint").textContent = "请填写完整企业名称";
    $("invoiceHint").className = "hint err";
    return;
  }
  if (taxId.length < 15) {
    $("invoiceHint").textContent = "请填写正确的纳税人识别号";
    $("invoiceHint").className = "hint err";
    return;
  }
  if (!email.includes("@")) {
    $("invoiceHint").textContent = "请填写有效邮箱";
    $("invoiceHint").className = "hint err";
    return;
  }
  if (!amount || amount <= 0) {
    $("invoiceHint").textContent = "请选择有效订单";
    $("invoiceHint").className = "hint err";
    return;
  }
  try {
    const res = await invoiceApi("/api/invoice/request", {
      method: "POST",
      body: JSON.stringify({
        payment_claim_id: paymentClaimId,
        company_name: company,
        tax_id: taxId,
        contact_email: email,
        invoice_amount: amount,
        note: $("invoiceNote").value,
      }),
    });
    $("invoiceHint").textContent = res.message || "申请已提交，请留意邮箱。";
    $("invoiceHint").className = "hint ok";
    await loadEligibleOrders();
  } catch (err) {
    $("invoiceHint").textContent = err.message;
    $("invoiceHint").className = "hint err";
  }
});

syncHeaderAuthUI(getAuthState());
syncInvoiceView();
