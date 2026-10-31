const AREA_SOURCES = {
  manual: "Введена сотрудником",
  project_total: "Общая площадь из проекта",
  project_footprint_times_floors: "Пятно застройки × этажность (приближение)",
};
const MISSING = {
  area_m2: "Укажите общую площадь дома.",
  material_or_unit_cost: "Нужен материал стен или своя ставка за м².",
  confirmed_readiness:
    "Подтвердите готовность в обзоре после обработки снимков.",
  "valuation.configuration": "Проверьте конфигурацию тарифов на сервере.",
};

export function constructionCostPanel(o, { esc, money, label }) {
  const v = o.valuation || {},
    b = v.breakdown || {},
    inputs = o.valuation_inputs || {};
  const amount = (value) => (value == null ? "Не рассчитано" : money(value));
  const range = (values) =>
    values
      ? `${money(values[0])} — ${money(values[1])}`
      : "Недостаточно данных";
  const cards = [
    ["Готовый контур дома", "full_cost_rub", "full_range_rub"],
    ["Условная выполненная часть", "completed_cost_rub", "completed_range_rub"],
    ["Остаток на достройку", "remaining_cost_rub", "remaining_range_rub"],
  ];
  return `<section class="panel section-block" id="construction-cost"><div class="panel-head"><h2>Стоимость постройки</h2><span>${v.is_demo ? "Демонстрационные тарифы" : "Предварительный расчёт"}</span></div><div class="panel-body">
    <p>${esc(v.completion_scope || "Наружный контур дома")}</p>
    <div class="form-grid" style="margin-top:20px">${cards.map(([title, key, rangeKey]) => `<article><h3>${title}</h3><p class="value-amount" data-cost="${key}">${amount(v[key])}</p><p class="subtle">${range(v[rangeKey])}</p></article>`).join("")}</div>
    <p style="margin-top:20px">${esc(v.explanation || "Для расчёта нужны площадь, материал и готовность.")}</p>
    ${v.range_percent != null ? `<p class="subtle">Вилка ±${esc(v.range_percent)}% — условный сценарий для демонстрации, не статистическая точность.</p>` : ""}
    <dl class="facts" style="margin-top:20px"><dt>Общая площадь</dt><dd>${b.area_m2 == null ? "Не указана" : `${esc(b.area_m2)} м² · ${esc(AREA_SOURCES[b.area_source] || "")}`}</dd><dt>Материал</dt><dd>${b.material ? `${esc(label("materials", b.material))} · ${b.material_source === "fixed" ? "закреплён на объекте" : "из проекта"}` : "Не определён"}</dd><dt>Ставка</dt><dd>${b.unit_cost_rub_m2 == null ? "Не указана" : `${money(b.unit_cost_rub_m2)} / м² · ${b.rate_source === "manual" ? "ввод сотрудника" : "конфигурация тарифов"}`}</dd><dt>Готовность</dt><dd>${b.readiness_pct == null ? "Не подтверждена" : `${esc(b.readiness_pct)}% · ${b.readiness_source === "employee" ? "проверка сотрудника" : "результат модели"}`}</dd><dt>Участок отдельно</dt><dd>${b.land_rub == null ? "Стоимость не указана" : money(b.land_rub)}</dd></dl>
    <p class="subtle" style="margin-top:16px">Не входит в стоимость контура: ${esc(v.excludes || "земля, отделка и инженерные сети")}. Участок не включён в три суммы выше.</p>
    ${(v.missing_data || []).map((key) => `<p class="note warning">${esc(MISSING[key] || key)}</p>`).join("")}
    ${(v.warnings || []).map((text) => `<p class="note warning" style="margin-top:12px">${esc(text)}</p>`).join("")}
    <form id="valuation-form" style="margin-top:25px"><div class="form-grid">
      <div class="form-group"><label for="cost-area">Общая площадь для расчёта, м²</label><input class="field" id="cost-area" name="area_m2" type="number" min="0.001" max="1000000" step="0.001" value="${esc(inputs.area_m2 ?? "")}" placeholder="Пусто — взять из проекта"></div>
      <div class="form-group"><label for="cost-rate">Своя ставка, ₽/м²</label><input class="field" id="cost-rate" name="unit_cost_rub_m2" type="number" min="0.01" max="10000000" step="0.01" value="${esc(inputs.unit_cost_rub_m2 ?? "")}" placeholder="Пусто — тариф для материала"></div>
      <div class="form-group"><label for="cost-rate-note">Источник своей ставки</label><input class="field" id="cost-rate-note" name="rate_note" maxlength="1000" value="${esc(inputs.rate_note || "")}" placeholder="Например, смета подрядчика"></div>
      <div class="form-group"><label for="cost-land">Стоимость участка отдельно, ₽</label><input class="field" id="cost-land" name="land_rub" type="number" min="0" max="1000000000000" step="0.01" value="${esc(inputs.land_rub ?? "")}"></div>
    </div><p class="subtle">Пустое поле снимает ручную настройку. Материал и готовность проверяются в своих вкладках.</p><div class="form-actions"><button type="submit" class="btn primary">Сохранить параметры и пересчитать</button></div></form>
  </div></section>`;
}
