import test from "node:test";
import assert from "node:assert/strict";
import {
  normalizeMeta,
  supports,
  selectableMaterials,
  percent,
} from "../js/capabilities.js";
import { materialPanel, readinessDetail } from "../js/inspection.js";

test("Inspection connects without bank dictionaries", () => {
  const meta = normalizeMeta({
    scope: "inspection",
    materials: [],
    views: [],
    capabilities: {
      readiness: true,
      material_review: true,
      alerts: false,
      tasks: false,
    },
  });
  assert.equal(supports(meta, "readiness"), true);
  assert.equal(supports(meta, "alerts"), false);
  assert.deepEqual(meta.steps, []);
  assert.equal(
    supports(
      normalizeMeta({ materials: [], views: [], risk_levels: [], steps: [] }),
      "conductor",
    ),
    true,
  );
});

test("Display values are excluded from editable materials and missing confidence is explicit", () => {
  assert.deepEqual(
    selectableMaterials({
      materials: [{ id: "brick" }, { id: "hidden" }, { id: "unclear" }],
    }),
    [{ id: "brick" }],
  );
  assert.equal(percent(null), "Не указана");
  assert.equal(percent(undefined), "Не указана");
  assert.equal(percent(0), "0%");
});

const ui = {
  esc: String,
  btn: (text) => text,
  label: (group, value) => value,
  date: (value) => value || "—",
};
test("Unfixed material remains visible", () => {
  const html = materialPanel(
    {
      material: null,
      last_flight: {
        status: "done",
        material_result: {
          status: "needs_review",
          material: "timber",
          material_label: "Брус",
          confidence: 0.7,
          is_demo: false,
          explanation: "Проверить дом",
          per_view: [],
        },
      },
    },
    { capabilities: { material_review: true } },
    ui,
  );
  assert.match(html, /Брус/);
  assert.match(html, /needs_review/);
  assert.match(html, /70%/);
  assert.doesNotMatch(html, /NaN/);
});
test("Manual readiness takes precedence over unavailable model", () => {
  const html = readinessDetail(
    {
      last_flight: {
        status: "done",
        readiness_review: {
          stage: "walls",
          readiness_pct: 45,
          bank_readiness: 50,
          author: "inspector",
          comment: "Проверено",
        },
        result: {
          status: "model_unavailable",
          is_demo: true,
          stage: null,
          readiness_pct: null,
        },
      },
    },
    ui,
  );
  assert.match(html, /45%/);
  assert.match(html, /Проверено сотрудником/);
});
