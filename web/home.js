import { initPage } from "/layout.js?v=27";
import { authReady, getAuthState, isUnifiedAuthMode, navigateToUnifiedLogin, syncHeaderAuthUI } from "/auth.js?v=40";

await initPage("home");
await authReady;

const $ = (id) => document.getElementById(id);

function syncHomePage(state = getAuthState()) {
  syncHeaderAuthUI(state);
  const user = state?.user;
  const usage = state?.usage;
  const btn = $("heroStartBtn");
  if (btn) {
    if (user) {
      btn.textContent = usage?.owner_vip || user.owner_vip ? "进入在线生成（无限权限）" : "进入在线生成";
      btn.classList.add("logged-in");
    } else {
      btn.textContent = "免费体验 1 张";
      btn.classList.remove("logged-in");
    }
  }
}

const GENERATE_PATH = "/generate.html";

function postLoginGenerateTarget() {
  return `${window.location.origin}${GENERATE_PATH}`;
}

function goGenerateOrRegister() {
  const user = window.__posterUser || getAuthState()?.user;
  if (!user) {
    if (isUnifiedAuthMode()) {
      sessionStorage.setItem("poster_after_login", GENERATE_PATH);
      const target = postLoginGenerateTarget();
      window.suatStoreIntendedRedirect?.(target);
      navigateToUnifiedLogin("login", target);
      return;
    }
    $("registerModal")?.showModal();
    return;
  }
  window.location.href = GENERATE_PATH;
}

document.getElementById("heroStartBtn")?.addEventListener("click", goGenerateOrRegister);
document.getElementById("heroStartBtnMirror")?.addEventListener("click", goGenerateOrRegister);

window.addEventListener("poster:auth", (e) => {
  window.__posterUser = e.detail.user;
  syncHomePage(e.detail);
});

syncHomePage();
