import { initPage } from "/layout.js?v=27";
import { FALLBACK_PLANS, renderPricingGrid } from "/plans.js?v=13";
import { authReady, getAuthState, isUnifiedAuthMode, navigateToUnifiedLogin, syncHeaderAuthUI } from "/auth.js?v=39";

await initPage("pricing");
await authReady;

const $ = (id) => document.getElementById(id);
let config = { plans: FALLBACK_PLANS };

function openPayment(planId) {
  const plan = (config.plans || []).find((p) => p.id === planId);
  if (plan?.payment_disabled === true) return;
  window.dispatchEvent(new CustomEvent("poster:open-payment", { detail: planId }));
}

window.openPayment = openPayment;

window.addEventListener("poster:auth", (e) => {
  window.__posterUser = e.detail.user;
  syncHeaderAuthUI(e.detail);
});

syncHeaderAuthUI(getAuthState());

try {
  const data = await fetch("/api/config").then((r) => r.json());
  if (data.plans?.length) config = data;
} catch {
  /* fallback */
}

renderPricingGrid(
  $("pricingGrid"),
  config.plans?.length ? config.plans : FALLBACK_PLANS,
  () => {
    if (isUnifiedAuthMode()) {
      navigateToUnifiedLogin("register");
      return;
    }
    $("registerModal")?.showModal();
  },
  openPayment
);
