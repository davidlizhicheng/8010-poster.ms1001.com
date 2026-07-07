import { ensureAuthBound } from "/auth.js?v=39";

const NAV = [
  { href: "/services.html", label: "使用须知", key: "services" },
  { href: "/about.html", label: "操作说明", key: "about" },
  { href: "/pricing.html", label: "套餐说明", key: "pricing" },
  { href: "/generate.html", label: "在线生成", key: "generate" },
  { href: "/invoice.html", label: "企业开票", key: "invoice" },
];

export const BRAND_NAME = "AI品牌广告图文设计师与知识地图设计师";
export const BRAND_TAGLINE = "零基础一键生成您的海报、广告、效果图、画册、岗位学习地图、Q&A知识卡片、自媒体图片、简历等设计作品";

function headerHtml(active) {
  const links = NAV.map(
    (n) =>
      `<a href="${n.href}" class="${n.key === active ? "active" : ""}">${n.label}</a>`
  ).join("");
  return `
    <div class="header-stack">
      <div class="header-inner">
        <a class="logo" href="/">
          <span class="logo-mark">AI</span>
          <span class="logo-text">
            <span class="logo-title">${BRAND_NAME}</span>
            <span class="logo-tagline">${BRAND_TAGLINE}</span>
          </span>
        </a>
        <nav class="nav-links" id="navLinks">${links}</nav>
        <button class="nav-toggle" id="navToggle" type="button" aria-label="打开菜单">菜单</button>
        <div class="header-actions">
          <button class="btn primary" id="authEntryBtn" type="button">登录 / 注册</button>
          <a class="btn ghost auth-hidden" id="accountBtn" href="https://ai.ms1001.com/account.html">查看账号</a>
          <button class="btn ghost auth-hidden" id="logoutBtn" type="button">退出登录</button>
        </div>
      </div>
      <div class="auth-welcome-bar auth-hidden" id="authWelcomeBar" aria-live="polite">
        <div class="auth-welcome-inner">
          <span class="auth-welcome-text" id="authWelcomeText"></span>
          <span class="usage-chip auth-hidden" id="usageChip"></span>
        </div>
      </div>
    </div>`;
}

function footerHtml() {
  return `
    <div class="footer-inner footer-compact">
      <div class="footer-aside">
        <p class="footer-tip">AI 生成内容仅供设计参考，正式发布前请人工复核文案、Logo 与品牌规范。</p>
        <p class="footer-tip footer-tip-sub">仅成功生成并交付的设计图计入额度；生成失败不扣减。</p>
      </div>
      <p class="footer-meta" id="footerSupport"></p>
    </div>`;
}

async function syncFooterSupport() {
  try {
    const cfg = await fetch("/api/config").then((r) => r.json());
    const support = [];
    if (cfg.support_phone) support.push(`客服 ${cfg.support_phone}`);
    if (cfg.support_wechat) support.push(`微信 ${cfg.support_wechat}`);
    const el = document.getElementById("footerSupport");
    if (el) {
      el.textContent = support.join(" · ") || "如有疑问，请通过平台公示的联系方式与我们联系。";
    }
  } catch {
    const el = document.getElementById("footerSupport");
    if (el) el.textContent = "如有疑问，请通过平台公示的联系方式与我们联系。";
  }
}

export async function initPage(activeKey) {
  const header = document.getElementById("siteHeader");
  if (header) {
    header.className = "site-header";
    header.innerHTML = headerHtml(activeKey);
  }
  const footer = document.getElementById("siteFooter");
  if (footer) {
    footer.className = "site-footer";
    footer.innerHTML = footerHtml();
  }
  if (!document.getElementById("loginModal")) {
    const res = await fetch("/modals.html");
    if (res.ok) document.body.insertAdjacentHTML("beforeend", await res.text());
  }
  document.getElementById("navToggle")?.addEventListener("click", () => {
    document.getElementById("navLinks")?.classList.toggle("open");
  });
  document.getElementById("navLinks")?.querySelectorAll("a").forEach((a) => {
    a.addEventListener("click", () => document.getElementById("navLinks")?.classList.remove("open"));
  });
  syncFooterSupport();
  ensureAuthBound();
}
