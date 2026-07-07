export const FALLBACK_PLANS = [
  { id: "trial_001", name: "免费体验", price_label: "¥0", highlight: "新用户", desc: "注册即送 1 张成品，同主题可修改 5 次", features: ["无需付款", "注册即用", "适合首次试用"] },
  { id: "single_50", name: "单张设计包", price_label: "¥50", highlight: "灵活", desc: "1 张成品，同主题可修改 5 次", features: ["单张付费即用", "适合紧急物料", "支持下载 PNG"] },
  { id: "pack_20", name: "月度套餐", price_label: "¥300/月", highlight: "热门", desc: "20 次设计额度，适合月均活动", features: ["20 次独立生成", "社群与活动传播", "企业机构首选"] },
  { id: "pack_100", name: "季度套餐", price_label: "¥1000/季度", highlight: "储备", desc: "100 次额度，须在 3 个月内用完", features: ["100 次独立生成", "适合集中投放季", "支持企业开票"] },
  { id: "consult_5000", name: "包年 · 品牌咨询", price_label: "¥5000/年", highlight: "包年", desc: "一年 500 次额度 + 品牌咨询", features: ["500 次设计生成", "须在一年内用完", "每月 1 次咨询服务"] },
  { id: "vip_10000", name: "包年 · 尊享定制", price_label: "¥10000/年", highlight: "尊享", desc: "每月 20 次额度 + 个性化定制", features: ["每月 20 次设计生成", "365 天服务期内每月刷新", "额外定制服务"] },
  { id: "bulk", name: "企业批量", price_label: "¥10/张", highlight: "¥200 起", desc: "大规模投放与定制批次", features: ["20 张以上 ¥10/张", "公司转账最低 ¥200", "支持 API 参考图"] },
];

export function renderPricingGrid(grid, plans, onRegister, onPlan) {
  if (!grid || !plans.length) return;
  grid.innerHTML = plans
    .map((plan) => {
      const features = (plan.features || []).map((f) => `<li>${f}</li>`).join("");
      let cta;
      if (plan.id === "trial_001") {
        cta = `<button class="btn primary full" type="button" data-action="register">注册免费体验</button>`;
      } else if (plan.payment_disabled === true) {
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
  grid.querySelectorAll("[data-plan]").forEach((btn) => {
    btn.addEventListener("click", () => onPlan(btn.dataset.plan));
  });
  grid.querySelectorAll("[data-action='register']").forEach((btn) => {
    btn.addEventListener("click", onRegister);
  });
}
