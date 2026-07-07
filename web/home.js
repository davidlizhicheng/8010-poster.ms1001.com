import { initPage } from "/layout.js?v=27";
import { authReady, getAuthState, isUnifiedAuthMode, navigateToUnifiedLogin, syncHeaderAuthUI } from "/auth.js?v=39";

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

function goGenerateOrRegister() {
  const user = window.__posterUser;
  if (!user) {
    if (isUnifiedAuthMode()) {
      navigateToUnifiedLogin("register");
      return;
    }
    $("registerModal")?.showModal();
    return;
  }
  window.location.href = "/generate.html";
}

document.getElementById("heroStartBtn")?.addEventListener("click", goGenerateOrRegister);
document.getElementById("heroStartBtnMirror")?.addEventListener("click", goGenerateOrRegister);

window.addEventListener("poster:auth", (e) => {
  window.__posterUser = e.detail.user;
  syncHomePage(e.detail);
});

syncHomePage();
