import assert from "node:assert/strict";
import test from "node:test";
import { constructionCostPanel } from "../js/valuation.js";

const helpers = {
  esc: (v) =>
    String(v)
      .replaceAll("&", "&amp;")
      .replaceAll('"', "&quot;")
      .replaceAll("<", "&lt;"),
  money: (v) => `${v} ₽`,
  label: (_, v) => v,
};

test("unknown cost is not displayed as zero or NaN", () => {
  const html = constructionCostPanel(
    {
      valuation: {
        is_demo: true,
        missing_data: ["area_m2", "confirmed_readiness"],
      },
    },
    helpers,
  );
  assert.equal(
    (html.match(/data-cost="[^"]+">Не рассчитано/g) || []).length,
    3,
  );
  assert.match(html, /Демонстрационные тарифы/);
  assert.match(html, /Укажите общую площадь дома/);
  assert.doesNotMatch(html, /NaN|undefined|>0 ₽</);
});

test("three construction amounts and separate land are visible", () => {
  const html = constructionCostPanel(
    {
      valuation: {
        full_cost_rub: 5000000,
        completed_cost_rub: 0,
        remaining_cost_rub: 5000000,
        breakdown: {
          area_m2: 100,
          area_source: "project_total",
          readiness_pct: 0,
          readiness_source: "employee",
          land_rub: 1000000,
        },
        explanation: "100 × 50000 = 5000000",
        range_percent: 30,
      },
      valuation_inputs: { rate_note: '<script>"x"</script>' },
    },
    helpers,
  );
  assert.match(html, /data-cost="completed_cost_rub">0 ₽/);
  assert.match(html, /Участок не включён в три суммы выше/);
  assert.match(html, /100 × 50000 = 5000000/);
  assert.match(html, /не статистическая точность/);
  assert.doesNotMatch(html, /<script>/);
});
