/* hotel_eval 可视化界面 —— 前端逻辑 */
"use strict";

const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

// ---- API 辅助 ----
async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `请求失败 ${res.status}`);
  return data;
}

// ---- 全局状态 ----
const state = { cases: [], sets: [], records: [], config: {} };

// ---- toast ----
let toastTimer;
function toast(msg, type = "") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast " + type;
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), 2600);
}

// ---- 工具 ----
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}
function fmtJson(o) { return JSON.stringify(o, null, 2); }
function layerBadge(layer, passed) {
  if (!passed) return `<span class="badge ${layer}">${layer}</span>`;
  return `<span class="badge muted">${layer}</span>`;
}
function gateBadge(gate) {
  return gate === "PASS" ? `<span class="badge pass">PASS</span>` : `<span class="badge fail">FAIL</span>`;
}

// =====================================================================
// 导航
// =====================================================================
function switchView(view) {
  $$(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  $$(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + view));
  if (view === "cases") loadCases();
  if (view === "sets") loadSets();
  if (view === "run") loadRunOptions();
  if (view === "records") loadRecords();
  if (view === "config") loadConfig();
}

// =====================================================================
// 单case 管理
// =====================================================================
async function loadCases() {
  state.cases = await api("/api/cases");
  renderCaseList();
}

function renderCaseList() {
  const box = $("#case-list");
  if (!state.cases.length) { box.innerHTML = `<div class="empty">还没有 case，点右上角「新建 case」开始。</div>`; return; }
  const rows = state.cases.map(c => `
    <tr>
      <td><b>${esc(c.case_id)}</b></td>
      <td>${esc((c.hotels || []).join("<br>"))}</td>
      <td>${c.nights}晚 ${c.date || "-"} ${c.guests ? c.guests + "人" : ""}</td>
      <td>${c.fact_count} 家</td>
      <td>${c.profile && c.profile.length ? esc(c.profile.join(", ")) : "-"}</td>
      <td>${c.output_count}</td>
      <td>
        <button class="btn sm" data-act="view" data-id="${esc(c.case_id)}">查看</button>
        <button class="btn sm" data-act="edit" data-id="${esc(c.case_id)}">编辑</button>
        <button class="btn sm danger" data-act="del" data-id="${esc(c.case_id)}">删除</button>
      </td>
    </tr>`).join("");
  box.innerHTML = `
    <table><thead><tr><th>case_id</th><th>选择酒店</th><th>入住条件</th><th>事实库</th><th>画像</th><th>输出数</th><th>操作</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
  $$("#case-list [data-act]").forEach(b => b.addEventListener("click", () => {
    const id = b.dataset.id;
    if (b.dataset.act === "view") openCaseDrawer(id, "view");
    if (b.dataset.act === "edit") openCaseDrawer(id, "edit");
    if (b.dataset.act === "del") delCase(id);
  }));
}

async function delCase(id) {
  if (!confirm(`确定删除 case「${id}」及其所有输出？`)) return;
  await api(`/api/cases/${encodeURIComponent(id)}`, { method: "DELETE" });
  toast("已删除 case", "ok");
  loadCases();
}

// ---- case 抽屉（详情 + 编辑） ----
let drawerCaseId = null;
let drawerMode = "edit";

async function openCaseDrawer(caseId, mode) {
  drawerCaseId = caseId;
  drawerMode = mode;
  const data = await api(`/api/cases/${encodeURIComponent(caseId)}`);
  renderCaseDrawer(data.case, data.outputs, mode);
  $("#drawer-title").textContent = mode === "view" ? "case 详情" : `编辑 case · ${caseId}`;
  openDrawer("#case-drawer");
}

function renderCaseDrawer(caseObj, outputs, mode) {
  const inp = caseObj.input || {};
  const ref = caseObj.reference || {};
  const profile = ref.user_profile || {};
  const factDb = ref.fact_db || {};
  const body = $("#drawer-body");
  const ro = mode === "view" ? "disabled" : "";

  body.innerHTML = `
    <div class="card">
      <div class="section-title">基本信息</div>
      <div class="form-grid">
        <label>case_id <input id="cf-caseid" value="${esc(caseObj.case_id)}" ${ro}></label>
        <label>入住晚数 <input id="cf-nights" type="number" min="1" value="${esc(inp.nights ?? 1)}" ${ro}></label>
        <label>日期 <input id="cf-date" value="${esc(inp.date || "")}" ${ro}></label>
        <label>人数 <input id="cf-guests" type="number" value="${esc(inp.guests ?? "")}" ${ro}></label>
        <label>区域偏好 <input id="cf-region" value="${esc(inp.region || "")}" ${ro}></label>
        <label>预算 <input id="cf-budget" type="number" value="${esc(inp.budget ?? "")}" ${ro}></label>
      </div>
      <label>选择酒店（每行一家）
        <textarea id="cf-hotels" ${ro}>${esc((inp.hotels || []).join("\n"))}</textarea>
      </label>
    </div>

    <div class="card">
      <div class="section-title">用户画像（参考信息）</div>
      <div class="form-grid">
        <label>画像标签（逗号分隔）<input id="cf-tags" value="${esc((profile.tags || []).join(", "))}" ${ro}></label>
      </div>
      <label>画像描述
        <textarea id="cf-desc" ${ro}>${esc(profile.description || "")}</textarea>
      </label>
    </div>

    <div class="card">
      <div class="section-title">酒店事实库（fact_db）</div>
      <div id="fact-rows"></div>
      <button class="btn sm" id="btn-add-fact" ${ro}>+ 添加酒店事实</button>
    </div>

    <div class="card">
      <div class="section-title">LLM 输出（评测对象）</div>
      <div id="output-list"></div>
      <div id="output-editor" class="${mode === "view" ? "hidden" : ""}">
        <hr>
        <div class="section-title">添加/编辑输出</div>
        <div class="form-grid">
          <label>来源 <input id="op-source" value=""></label>
          <label>备注 <input id="op-note" value=""></label>
        </div>
        <label>原始输出
          <textarea id="op-raw"></textarea>
        </label>
        <label>手工声称（JSON 数组，可选）
          <textarea id="op-claims" class="mono"></textarea>
        </label>
        <div class="actions"><button class="btn primary" id="btn-save-output">保存输出</button><span class="status" id="op-status"></span></div>
      </div>
    </div>

    ${mode !== "view" ? `<div class="actions"><button class="btn primary" id="btn-save-case">保存 case</button></div>` : ""}
  `;

  renderFactRows(factDb);
  renderOutputList(outputs || [], mode);

  if (mode !== "view") {
    $("#btn-add-fact").addEventListener("click", () => addFactRow({}));
    $("#btn-save-case").addEventListener("click", saveCaseForm);
    $("#btn-save-output").addEventListener("click", saveOutput);
  }
  // 输出列表里的"编辑/查看/删除"
  $$("#output-list [data-act]").forEach(b => b.addEventListener("click", () => {
    const oid = b.dataset.id;
    const out = (outputs || []).find(o => o.output_id === oid);
    if (b.dataset.act === "edit" && out) fillOutputEditor(out);
    if (b.dataset.act === "del") delOutput(oid);
  }));
}

// ---- fact_db 动态行 ----
function addFactRow(fact) {
  const rows = $("#fact-rows");
  const editable = drawerMode !== "view";
  const div = document.createElement("div");
  div.className = "fact-row";
  div.innerHTML = `
    <div class="fact-row-inner">
      <input class="fr-name" placeholder="酒店名" value="${esc(fact.name || "")}" ${editable ? "" : "disabled"}>
      <input class="fr-region" placeholder="区域" value="${esc(fact.region || "")}" ${editable ? "" : "disabled"}>
      <input class="fr-star" placeholder="档次" value="${esc(fact.star || "")}" ${editable ? "" : "disabled"}>
      <input class="fr-price" type="number" placeholder="价格" value="${esc(fact.price ?? "")}" ${editable ? "" : "disabled"}>
      <input class="fr-score" type="number" step="0.1" placeholder="评分" value="${esc(fact.score ?? "")}" ${editable ? "" : "disabled"}>
      <input class="fr-facil" placeholder="设施(逗号分隔)" value="${esc((fact.facilities || []).join(", "))}" ${editable ? "" : "disabled"}>
      ${editable ? `<button class="btn sm danger fr-del">✕</button>` : ""}
    </div>`;
  const del = div.querySelector(".fr-del");
  if (del) del.addEventListener("click", () => div.remove());
  rows.appendChild(div);
}
function renderFactRows(factDb) {
  $("#fact-rows").innerHTML = "";
  Object.entries(factDb).forEach(([name, f]) => addFactRow({ name, ...f }));
}

function collectFactRows() {
  const factDb = {};
  $$("#fact-rows .fact-row").forEach(row => {
    const name = row.querySelector(".fr-name").value.trim();
    if (!name) return;
    factDb[name] = {
      region: row.querySelector(".fr-region").value.trim(),
      star: row.querySelector(".fr-star").value.trim(),
      price: Number(row.querySelector(".fr-price").value) || 0,
      score: Number(row.querySelector(".fr-score").value) || 0,
      facilities: row.querySelector(".fr-facil").value.split(/[,，]/).map(s => s.trim()).filter(Boolean),
    };
  });
  return factDb;
}

async function saveCaseForm() {
  const caseId = $("#cf-caseid").value.trim();
  if (!caseId) { toast("case_id 不能为空", "error"); return; }
  const body = {
    case_id: caseId,
    input: {
      hotels: $("#cf-hotels").value.split("\n").map(s => s.trim()).filter(Boolean),
      date: $("#cf-date").value.trim(),
      guests: $("#cf-guests").value ? Number($("#cf-guests").value) : null,
      nights: Number($("#cf-nights").value) || 1,
      region: $("#cf-region").value.trim() || null,
      budget: $("#cf-budget").value ? Number($("#cf-budget").value) : null,
    },
    reference: {
      fact_db: collectFactRows(),
      user_profile: {
        tags: $("#cf-tags").value.split(/[,，]/).map(s => s.trim()).filter(Boolean),
        description: $("#cf-desc").value.trim(),
      },
    },
  };
  try {
    if (drawerCaseId) await api(`/api/cases/${encodeURIComponent(drawerCaseId)}`, { method: "PUT", body: JSON.stringify(body) });
    else await api("/api/cases", { method: "POST", body: JSON.stringify(body) });
    toast("case 已保存", "ok");
    closeDrawer("#case-drawer");
    loadCases();
  } catch (e) { toast(e.message, "error"); }
}

// ---- 输出管理 ----
let editingOutputId = null;
function renderOutputList(outputs, mode) {
  const box = $("#output-list");
  if (!outputs.length) { box.innerHTML = `<div class="muted">该 case 暂无输出。</div>`; return; }
  box.innerHTML = outputs.map(o => `
    <div class="issue" style="border-left-color:var(--primary)">
      <div class="flex">
        <span class="i-check">${esc(o.source || "未标注来源")}</span>
        <span class="muted">${esc(o.output_id || "")}</span>
        <span style="margin-left:auto">
          ${mode !== "view" ? `<button class="btn sm" data-act="edit" data-id="${esc(o.output_id)}">编辑</button>` : ""}
          ${mode !== "view" ? `<button class="btn sm danger" data-act="del" data-id="${esc(o.output_id)}">删除</button>` : ""}
        </span>
      </div>
      <div class="i-detail muted">${esc(o.note || "")}</div>
      <details class="mt"><summary>查看原文（${(o.raw || "").length} 字符）</summary>
        <pre class="mono">${esc(o.raw)}</pre>
      </details>
    </div>`).join("");
}

function fillOutputEditor(out) {
  editingOutputId = out.output_id;
  $("#op-source").value = out.source || "";
  $("#op-note").value = out.note || "";
  $("#op-raw").value = out.raw || "";
  $("#op-claims").value = fmtJson(out.claims || []);
  $("#op-status").textContent = "正在编辑：" + out.output_id;
}

async function saveOutput() {
  if (!drawerCaseId) return;
  let claims;
  try { claims = JSON.parse($("#op-claims").value || "[]"); }
  catch { toast("手工声称不是合法 JSON", "error"); return; }
  const body = {
    case_id: drawerCaseId,
    raw: $("#op-raw").value,
    source: $("#op-source").value,
    note: $("#op-note").value,
    claims,
    output_id: editingOutputId || "",
  };
  try {
    if (editingOutputId) await api(`/api/outputs/${encodeURIComponent(editingOutputId)}`, { method: "PUT", body: JSON.stringify(body) });
    else await api(`/api/cases/${encodeURIComponent(drawerCaseId)}/outputs`, { method: "POST", body: JSON.stringify(body) });
    toast("输出已保存", "ok");
    editingOutputId = null;
    const data = await api(`/api/cases/${encodeURIComponent(drawerCaseId)}`);
    renderCaseDrawer(data.case, data.outputs, drawerMode);
  } catch (e) { toast(e.message, "error"); }
}

async function delOutput(oid) {
  if (!confirm("确定删除这份输出？")) return;
  await api(`/api/outputs/${encodeURIComponent(oid)}`, { method: "DELETE" });
  toast("已删除输出", "ok");
  const data = await api(`/api/cases/${encodeURIComponent(drawerCaseId)}`);
  renderCaseDrawer(data.case, data.outputs, drawerMode);
}

// ---- 抽屉开关 ----
function openDrawer(sel) {
  $(sel).classList.add("open");
  $(sel).classList.remove("hidden");
  $("#drawer-backdrop").classList.remove("hidden");
}
function closeDrawer(sel) {
  $(sel).classList.remove("open");
  setTimeout(() => $(sel).classList.add("hidden"), 250);
  if (sel === "#case-drawer" && !$("#report-drawer").classList.contains("open")) {
    $("#drawer-backdrop").classList.add("hidden");
  }
  if (sel === "#report-drawer" && !$("#case-drawer").classList.contains("open")) {
    $("#drawer-backdrop").classList.add("hidden");
  }
}

// =====================================================================
// 评测集管理
// =====================================================================
async function loadSets() {
  state.sets = await api("/api/eval-sets");
  renderSetList();
}
function renderSetList() {
  const box = $("#set-list");
  if (!state.sets.length) { box.innerHTML = `<div class="empty">还没有评测集。</div>`; return; }
  box.innerHTML = `<table><thead><tr><th>名称</th><th>set_id</th><th>case 数</th><th>描述</th><th>操作</th></tr></thead><tbody>` +
    state.sets.map(s => `
      <tr>
        <td><b>${esc(s.name || s.set_id)}</b></td>
        <td>${esc(s.set_id)}</td>
        <td>${s.case_count}</td>
        <td class="muted">${esc(s.description || "")}</td>
        <td>
          <button class="btn sm" data-act="edit" data-id="${esc(s.set_id)}">编辑</button>
          <button class="btn sm danger" data-act="del" data-id="${esc(s.set_id)}">删除</button>
        </td>
      </tr>`).join("") + `</tbody></table>`;
  $$("#set-list [data-act]").forEach(b => b.addEventListener("click", () => {
    const id = b.dataset.id;
    if (b.dataset.act === "edit") openSetDrawer(id);
    if (b.dataset.act === "del") delSet(id);
  }));
}
async function delSet(id) {
  if (!confirm(`确定删除评测集「${id}」？`)) return;
  await api(`/api/eval-sets/${encodeURIComponent(id)}`, { method: "DELETE" });
  toast("已删除评测集", "ok"); loadSets();
}
async function openSetDrawer(setId) {
  let setObj = { set_id: "", name: "", description: "", case_ids: [] };
  if (setId) setObj = await api(`/api/eval-sets/${encodeURIComponent(setId)}`);
  const cases = await api("/api/cases");
  const body = $("#drawer-body");
  body.innerHTML = `
    <div class="card">
      <div class="form-grid">
        <label>名称 <input id="set-name" value="${esc(setObj.name || "")}"></label>
        <label>set_id <input id="set-id" value="${esc(setObj.set_id || "")}" ${setId ? "disabled" : ""}></label>
      </div>
      <label>描述 <textarea id="set-desc">${esc(setObj.description || "")}</textarea></label>
      <div class="section-title">选择 case</div>
      <div class="checkbox-list" id="set-cases">
        ${cases.map(c => `<label><input type="checkbox" class="set-case" value="${esc(c.case_id)}" ${setObj.case_ids.includes(c.case_id) ? "checked" : ""}> ${esc(c.case_id)}</label>`).join("")}
      </div>
      <div class="actions"><button class="btn primary" id="btn-save-set">保存评测集</button></div>
    </div>`;
  $("#btn-save-set").addEventListener("click", () => {
    const set_id = $("#set-id").value.trim();
    if (!set_id) { toast("set_id 不能为空", "error"); return; }
    const body = {
      set_id,
      name: $("#set-name").value.trim(),
      description: $("#set-desc").value.trim(),
      case_ids: $$(".set-case:checked").map(c => c.value),
    };
    (setId ? api(`/api/eval-sets/${encodeURIComponent(setId)}`, { method: "PUT", body: JSON.stringify(body) })
           : api("/api/eval-sets", { method: "POST", body: JSON.stringify(body) }))
      .then(() => { toast("评测集已保存", "ok"); closeDrawer("#case-drawer"); loadSets(); })
      .catch(e => toast(e.message, "error"));
  });
  $("#drawer-title").textContent = setId ? `编辑评测集 · ${setId}` : "新建评测集";
  openDrawer("#case-drawer");
}

// =====================================================================
// 触发评测
// =====================================================================
async function loadRunOptions() {
  const cases = await api("/api/cases");
  state.cases = cases;
  // 单次：case select
  const cs = $("#run-single-case");
  cs.innerHTML = cases.map(c => `<option value="${esc(c.case_id)}">${esc(c.case_id)}</option>`).join("");
  if (cases.length) await loadRunOutputs(cases[0].case_id);
  cs.onchange = () => loadRunOutputs(cs.value);
  // 批量：set select / case checkboxes
  const sets = await api("/api/eval-sets");
  state.sets = sets;
  const ss = $("#run-batch-set");
  ss.innerHTML = sets.map(s => `<option value="${esc(s.set_id)}">${esc(s.name || s.set_id)}（${s.case_count}）</option>`).join("") || `<option value="">无评测集</option>`;
  $("#run-batch-cases").innerHTML = cases.map(c => `<label><input type="checkbox" class="batch-case" value="${esc(c.case_id)}"> ${esc(c.case_id)}</label>`).join("") || `<div class="muted">无 case</div>`;
  $("#run-batch-set").onchange = onBatchSourceChange;
  $("#run-batch-source").onchange = onBatchSourceChange;
  onBatchSourceChange();
}
async function loadRunOutputs(caseId) {
  const outs = await api(`/api/cases/${encodeURIComponent(caseId)}/outputs`);
  const sel = $("#run-single-output");
  sel.innerHTML = outs.length ? outs.map(o => `<option value="${esc(o.output_id)}">${esc(o.source || "未标注来源")} · ${(o.raw || "").length}字符</option>`).join("")
                              : `<option value="">该 case 无输出</option>`;
}
function onBatchSourceChange() {
  const mode = $("#run-batch-source").value;
  $("#run-batch-set-wrap").classList.toggle("hidden", mode !== "set");
  $("#run-batch-cases-wrap").classList.toggle("hidden", mode !== "cases");
}

async function runSingle() {
  const caseId = $("#run-single-case").value;
  const outputId = $("#run-single-output").value;
  if (!caseId) { toast("请选择 case", "error"); return; }
  const box = $("#run-single-result");
  box.innerHTML = `<div class="card">运行中…</div>`;
  try {
    const rec = await api("/api/eval/run", { method: "POST", body: JSON.stringify({ case_id: caseId, output_id: outputId || null }) });
    // 拉取完整报告
    const full = await api(`/api/records/${rec.record_id}`);
    box.innerHTML = `<div class="card">${renderReport(full.report, { headerOnly: false })}</div>`;
  } catch (e) {
    box.innerHTML = `<div class="card issue fail">${esc(e.message)}</div>`;
  }
}

async function runBatch() {
  const mode = $("#run-batch-source").value;
  let body = { first_output_only: $("#run-batch-first-only").checked };
  if (mode === "set") body.set_id = $("#run-batch-set").value;
  else body.case_ids = $$(".batch-case:checked").map(c => c.value);
  const box = $("#run-batch-result");
  box.innerHTML = `<div class="card">运行中…</div>`;
  try {
    const res = await api("/api/eval/run-batch", { method: "POST", body: JSON.stringify(body) });
    const rows = res.results.map(r => `
      <tr>
        <td>${esc(r.case_id)}</td>
        <td>${esc(r.output_id || "")}</td>
        <td>${r.status === "done" ? gateBadge(r.gate) : `<span class="badge muted">${esc(r.reason || r.status)}</span>`}</td>
        <td>${r.issue_count ?? "-"}</td>
        <td>${r.record_id ? `<button class="btn sm" data-rec="${esc(r.record_id)}">查看报告</button>` : ""}</td>
      </tr>`).join("");
    box.innerHTML = `
      <div class="card">
        <div class="batch-summary">
          <div class="stat"><div class="s-num">${res.total}</div><div class="s-label">总</div></div>
          <div class="stat"><div class="s-num">${res.done}</div><div class="s-label">已运行</div></div>
          <div class="stat"><div class="s-num">${res.passed}</div><div class="s-label">PASS</div></div>
          <div class="stat"><div class="s-num">${res.done - res.passed}</div><div class="s-label">FAIL</div></div>
        </div>
        <table><thead><tr><th>case</th><th>输出</th><th>结论</th><th>问题数</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table>
      </div>`;
    $$("#run-batch-result [data-rec]").forEach(b => b.addEventListener("click", () => openReport(b.dataset.rec)));
  } catch (e) {
    box.innerHTML = `<div class="card issue fail">${esc(e.message)}</div>`;
  }
}

// =====================================================================
// 评测记录 + 报告详情
// =====================================================================
async function loadRecords() {
  state.records = await api("/api/records");
  renderRecordList();
}
function renderRecordList() {
  const box = $("#record-list");
  if (!state.records.length) { box.innerHTML = `<div class="empty">还没有评测记录，去「触发评测」跑一次。</div>`; return; }
  box.innerHTML = `<table><thead><tr><th>时间</th><th>case</th><th>来源</th><th>结论</th><th>问题</th><th>gate/safety/quality</th><th>judge</th><th>操作</th></tr></thead><tbody>` +
    state.records.map(r => `
      <tr>
        <td class="muted">${esc(r.timestamp || "")}</td>
        <td><b>${esc(r.case_id)}</b></td>
        <td>${esc(r.source || "-")}</td>
        <td>${gateBadge(r.gate)}</td>
        <td>${r.issue_count}</td>
        <td>${r.by_layer ? `${r.by_layer.gate}/${r.by_layer.safety}/${r.by_layer.quality}` : "-"}</td>
        <td>${r.judge_enabled ? "on" : `<span class="muted">off</span>`}</td>
        <td><button class="btn sm" data-rec="${esc(r.record_id)}">查看报告</button>
            <button class="btn sm danger" data-del="${esc(r.record_id)}">删</button></td>
      </tr>`).join("") + `</tbody></table>`;
  $$("#record-list [data-rec]").forEach(b => b.addEventListener("click", () => openReport(b.dataset.rec)));
  $$("#record-list [data-del]").forEach(b => b.addEventListener("click", async () => {
    if (confirm("删除这条记录？")) { await api(`/api/records/${encodeURIComponent(b.dataset.del)}`, { method: "DELETE" }); toast("已删除记录", "ok"); loadRecords(); }
  }));
}

async function openReport(recordId) {
  const rec = await api(`/api/records/${encodeURIComponent(recordId)}`);
  $("#report-body").innerHTML = renderReport(rec.report, { headerOnly: false, timestamp: rec.timestamp });
  openDrawer("#report-drawer");
}

// ---- 报告渲染 ----
function renderReport(r, opts = {}) {
  const c = r.conclusion || {};
  const by = c.by_layer || {};
  const inp = r.input || {};
  const ref = r.reference || {};
  const ext = r.extracted || {};
  const issues = r.issues || [];
  const judge = r.judge_results || {};

  let html = `
    <div class="report-header">
      <div class="flex">
        <h3>${esc(r.case_id)}</h3>
        ${gateBadge(c.gate)}
        ${c.judge_enabled ? `<span class="badge ok">judge on</span>` : `<span class="badge muted">judge off</span>`}
      </div>
      <div class="muted">${opts.timestamp ? esc(opts.timestamp) + " · " : ""}来源：${esc(r.source || "-")}</div>
    </div>

    <div class="layers">
      <div class="layer-box ${by.gate ? "fail" : "ok"}"><div class="lb-num">${by.gate ?? 0}</div><div class="s-label">gate 硬门禁</div></div>
      <div class="layer-box ${by.safety ? "fail" : "ok"}"><div class="lb-num">${by.safety ?? 0}</div><div class="s-label">safety 安全</div></div>
      <div class="layer-box ${by.quality ? "fail" : "ok"}"><div class="lb-num">${by.quality ?? 0}</div><div class="s-label">quality 质量</div></div>
    </div>

    <div class="card">
      <div class="section-title">入参（用户输入）</div>
      <dl class="kv">
        <dt>选择酒店</dt><dd>${esc((inp.hotels || []).join("、"))}</dd>
        <dt>入住条件</dt><dd>${inp.nights}晚 · ${inp.date || "-"} · ${inp.guests ? inp.guests + "人" : "-"}</dd>
        <dt>区域/预算</dt><dd>${inp.region || "-"} / ${inp.budget ?? "-"}</dd>
      </dl>
    </div>

    <div class="card">
      <div class="section-title">参考信息（基准）</div>
      <dl class="kv">
        <dt>酒店详情</dt><dd>${ref.fact_count ?? 0} 家</dd>
        <dt>用户画像</dt><dd>${esc((ref.profile || []).join(", ") || "-")}</dd>
        <dt>画像描述</dt><dd>${esc(ref.profile_text || "-")}</dd>
      </dl>
    </div>

    <div class="card">
      <div class="section-title">抽取结果</div>
      <dl class="kv">
        <dt>推荐结果</dt><dd>${(ext.results || []).map(x => esc(x.name)).join("、") || "-"}</dd>
        <dt>声称数</dt><dd>${ext.claims_count ?? 0}</dd>
        <dt>需求回显</dt><dd>酒店 ${esc((ext.requirement_hotels || []).join("、") || "-")} · 星级 ${esc(ext.requirement_star || "-")} · 区域 ${esc(ext.requirement_region || "-")} · 人数 ${esc(ext.requirement_guests ?? "-")}</dd>
        <dt>日期</dt><dd>${esc((ext.dates || []).join("、") || "-")}</dd>
      </dl>
    </div>
  `;

  // 问题（按层分组）
  const layerOrder = ["gate", "safety", "quality"];
  const layerLabel = { gate: "硬门禁（一致性·回显/自洽/事实）", safety: "安全层", quality: "软性层（需人工确认 / judge）" };
  html += `<div class="section-title">问题清单</div>`;
  let anyIssue = false;
  for (const layer of layerOrder) {
    const layerIssues = issues.filter(i => i.layer === layer);
    if (!layerIssues.length) continue;
    anyIssue = true;
    html += `<div class="card"><div class="section-title">【${layerLabel[layer]}】</div>`;
    layerIssues.forEach(i => {
      html += `
        <div class="issue ${i.passed ? "pass" : "fail"}">
          <div class="flex">
            ${layerBadge(i.layer, i.passed)}
            <span class="i-check">${esc(i.check)}</span>
            ${i.score != null ? `<span class="badge muted">score ${esc(i.score)}</span>` : ""}
          </div>
          <div class="i-detail">${esc(i.detail)}</div>
          ${i.evidence ? `<div class="i-evidence">证据：${esc(i.evidence)}</div>` : ""}
        </div>`;
    });
    html += `</div>`;
  }
  if (!anyIssue) html += `<div class="card muted">无发现问题。</div>`;

  // judge 结果
  html += `<div class="section-title">LLM-as-judge 层</div>`;
  const judgeDims = Object.keys(judge).filter(d => judge[d] && judge[d].score != null);
  if (judgeDims.length) {
    html += judgeDims.map(d => {
      const j = judge[d];
      return `<div class="judge-item">
        <div class="flex"><b>${esc(d)}</b><span class="j-score">${esc(j.score)}</span><span class="badge muted">${esc(j.confidence || "medium")}</span></div>
        <div class="i-detail mt">${esc(j.evidence || "")}</div>
        ${j.self_doubt ? `<div class="i-evidence">自疑：${esc(j.self_doubt)}</div>` : ""}
      </div>`;
    }).join("");
  } else {
    html += `<div class="card muted">${c.judge_enabled ? "judge 未返回分数。" : "未配置 judge，仅跑确定性层。"}</div>`;
  }

  // 结论
  html += `<div class="card"><div class="section-title">结论</div><div>${esc(c.summary || "")}</div></div>`;

  return html;
}

// =====================================================================
// 配置
// =====================================================================
async function loadConfig() {
  const cfg = await api("/api/config");
  state.config = cfg;
  $("#cfg-key").value = "";
  $("#cfg-key").placeholder = cfg.has_key ? "已配置（输入新值可覆盖）" : "sk-...";
  $("#cfg-base").value = cfg.judge_base_url || "";
  $("#cfg-model").value = cfg.judge_model || "gpt-4o-mini";
  updateJudgeStatus(cfg.has_key);
}
function updateJudgeStatus(hasKey) {
  const el = $("#judgeStatus");
  el.textContent = hasKey ? "judge：已配置" : "judge：未配置（仅确定性层）";
  el.className = "judge-status " + (hasKey ? "on" : "off");
}
async function saveConfig() {
  try {
    await api("/api/config", { method: "POST", body: JSON.stringify({
      judge_api_key: $("#cfg-key").value.trim(),
      judge_base_url: $("#cfg-base").value.trim(),
      judge_model: $("#cfg-model").value.trim() || "gpt-4o-mini",
    }) });
    toast("配置已保存", "ok");
    await loadConfig();
  } catch (e) { toast(e.message, "error"); }
}
async function testConfig() {
  const st = $("#cfg-status");
  st.textContent = "测试中…"; st.className = "status";
  try {
    const res = await api("/api/config/test", { method: "POST", body: JSON.stringify({
      judge_api_key: $("#cfg-key").value.trim(),
      judge_base_url: $("#cfg-base").value.trim(),
      judge_model: $("#cfg-model").value.trim() || "gpt-4o-mini",
    }) });
    st.textContent = res.detail;
    st.className = "status " + (res.ok ? "ok" : "err");
  } catch (e) { st.textContent = e.message; st.className = "status err"; }
}

// =====================================================================
// 初始化
// =====================================================================
function init() {
  $$(".nav-item").forEach(b => b.addEventListener("click", () => switchView(b.dataset.view)));
  $("#btn-new-case").addEventListener("click", () => openNewCaseDrawer());
  $("#btn-new-set").addEventListener("click", () => openSetDrawer(null));
  $("#btn-run-single").addEventListener("click", runSingle);
  $("#btn-run-batch").addEventListener("click", runBatch);
  $("#btn-clear-records").addEventListener("click", async () => {
    if (confirm("清空所有评测记录？")) { await api("/api/records/clear", { method: "POST" }); toast("已清空", "ok"); loadRecords(); }
  });
  $("#btn-save-config").addEventListener("click", saveConfig);
  $("#btn-test-config").addEventListener("click", testConfig);
  $("#btn-close-drawer").addEventListener("click", () => closeDrawer("#case-drawer"));
  $("#btn-close-report").addEventListener("click", () => closeDrawer("#report-drawer"));
  $("#drawer-backdrop").addEventListener("click", () => { closeDrawer("#case-drawer"); closeDrawer("#report-drawer"); });

  // run 模式 tab
  $$("#run-tabs .tab").forEach(t => t.addEventListener("click", () => {
    $$("#run-tabs .tab").forEach(x => x.classList.toggle("active", x === t));
    $("#run-single").classList.toggle("hidden", t.dataset.mode !== "single");
    $("#run-batch").classList.toggle("hidden", t.dataset.mode !== "batch");
  }));

  loadConfig();
  switchView("cases");
}

async function openNewCaseDrawer() {
  drawerCaseId = null; drawerMode = "edit";
  $("#drawer-title").textContent = "新建 case";
  renderCaseDrawer({ case_id: "", input: {}, reference: {} }, [], "edit");
  openDrawer("#case-drawer");
}

document.addEventListener("DOMContentLoaded", init);
