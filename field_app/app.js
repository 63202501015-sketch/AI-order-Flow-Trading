"use strict";
// Wang Sam Mo Field Research PWA — ทำงานบนเบราว์เซอร์ทั้งหมด ส่งข้อมูลตรงเข้า Google Apps Script
const CFG = window.WSM_CONFIG || {};
const KEY = "wsm_pending_v1";          // ใช้ key เดิมเพื่อไม่ให้ข้อมูลค้างในเครื่องหาย
const SET = "wsm_settings_v1";
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let master = {}, pos = {};

function store(k, fallback) { try { return JSON.parse(localStorage.getItem(k)) ?? fallback; } catch (e) { return fallback; } }
function settings() { const s = store(SET, {}); return { apiUrl: (s.apiUrl || CFG.API_URL || "").trim(), key: s.key || "" }; }
function pending() { return store(KEY, []); }
function put(a) { localStorage.setItem(KEY, JSON.stringify(a)); renderLocal(); }

function show(id) {
  document.querySelectorAll("section").forEach(x => x.classList.toggle("active", x.id === id));
  document.querySelectorAll("#tabs button").forEach(b => b.className = b.dataset.tab === id ? "primary" : "secondary");
  renderLocal();
  if (id === "dash") loadSummary();
}

async function init() {
  master = await fetch("master.json").then(r => r.json());
  $("pop").textContent = master.population_total.toLocaleString();
  $("sample").textContent = master.sample_total;
  $("cluster").textContent = master.cluster_total;
  Object.keys(master.targets).forEach(t => $("tambon").add(new Option(t, t)));
  $("tambon").onchange = fillVillages;
  fillVillages();
  renderPlan();
  renderLocal();
  const s = settings();
  $("apiUrl").value = s.apiUrl; $("teamKey").value = s.key;
  $("team").value = store("wsm_team", "");
  $("ver").textContent = "เวอร์ชัน " + (CFG.APP_VERSION || "");
  if (!s.apiUrl) $("msg").innerHTML = `<div class="warn">ยังไม่ได้ตั้งค่า URL ส่วนกลาง — บันทึกในเครื่องได้ แต่ต้องตั้งค่าที่แท็บ "ตั้งค่า" ก่อน Sync</div>`;
}

function fillVillages() {
  $("village").innerHTML = "";
  master.villages.filter(x => x.tambon === $("tambon").value)
    .forEach(x => $("village").add(new Option(`ม.${x.moo} ${x.village}`, x.id)));
}
function selectedVillage() { return master.villages.find(x => String(x.id) === $("village").value); }

function gps() {
  if (!navigator.geolocation) { $("gpsout").textContent = "อุปกรณ์ไม่รองรับ GPS"; return; }
  $("gpsout").textContent = "กำลังหาพิกัด…";
  navigator.geolocation.getCurrentPosition(p => {
    pos = { lat: p.coords.latitude, lon: p.coords.longitude, accuracy: Math.round(p.coords.accuracy) };
    $("gpsout").textContent = `${pos.lat.toFixed(6)}, ${pos.lon.toFixed(6)} ±${pos.accuracy}m`;
  }, e => $("gpsout").textContent = "GPS: " + e.message, { enableHighAccuracy: true, timeout: 15000 });
}

function qcFlags(x, all) {
  const f = [];
  if (!x.consent) f.push("ไม่มี Consent");
  if (x.consent === "ปฏิเสธ") f.push("ปฏิเสธ");
  if (!x.respondent_code) f.push("ไม่มีรหัส");
  if (x.lat == null) f.push("ไม่มี GPS");
  else if (x.accuracy > 50) f.push("GPS คลาดเคลื่อน >50m");
  if (x.respondent_code && all.some(y => y.uuid !== x.uuid && y.respondent_code === x.respondent_code && y.village === x.village && y.activity === x.activity)) f.push("รหัสซ้ำ");
  return f;
}

function saveLocal() {
  const v = selectedVillage();
  if (!v) { $("msg").innerHTML = `<div class="err">กรุณาเลือกหมู่บ้าน</div>`; return; }
  localStorage.setItem("wsm_team", JSON.stringify($("team").value));
  const x = {
    uuid: crypto.randomUUID ? crypto.randomUUID() : Date.now() + "-" + Math.random().toString(36).slice(2),
    created_at: new Date().toISOString(), team: $("team").value, activity: $("activity").value,
    tambon: v.tambon, moo: v.moo, village: v.village, respondent_code: $("rcode").value.trim(),
    consent: $("consent").value, note: $("note").value, qc: $("qcv").value, app_version: CFG.APP_VERSION, ...pos
  };
  const a = pending(); a.push(x); put(a);
  $("msg").innerHTML = `<div class="ok">✓ บันทึกในเครื่องแล้ว (รอ Sync ${a.length} รายการ)</div>`;
  $("note").value = ""; $("rcode").value = ""; $("consent").value = ""; pos = {}; $("gpsout").textContent = "ยังไม่มีพิกัด";
}

async function api(method, params, body) {
  const s = settings();
  if (!s.apiUrl) throw new Error('ยังไม่ได้ตั้งค่า URL ที่แท็บ "ตั้งค่า"');
  let r;
  if (method === "GET") {
    const q = new URLSearchParams({ ...params, key: s.key });
    r = await fetch(s.apiUrl + (s.apiUrl.includes("?") ? "&" : "?") + q, { redirect: "follow" });
  } else {
    // text/plain = simple request → ไม่มี CORS preflight (Apps Script ไม่รองรับ OPTIONS)
    r = await fetch(s.apiUrl, { method: "POST", redirect: "follow", headers: { "Content-Type": "text/plain;charset=utf-8" }, body: JSON.stringify({ ...body, key: s.key }) });
  }
  const j = await r.json().catch(() => { throw new Error("เซิร์ฟเวอร์ตอบกลับไม่ใช่ JSON — ตรวจว่า Deploy แบบ Anyone และใช้ URL /exec"); });
  if (!j.ok) throw new Error(j.error || "เกิดข้อผิดพลาด");
  return j;
}

async function sync() {
  const a = pending();
  if (!a.length) { $("msg").innerHTML = `<div class="ok">ไม่มีข้อมูลค้าง Sync</div>`; return; }
  if (!navigator.onLine) { $("msg").innerHTML = `<div class="warn">Offline — เก็บไว้ในเครื่องก่อน</div>`; return; }
  $("btnSync").disabled = true; $("msg").innerHTML = `<div class="warn">กำลังส่ง ${a.length} รายการ…</div>`;
  try {
    const records = a.map(x => ({ ...x, qc_flags: qcFlags(x, a).join("; ") }));
    const j = await api("POST", null, { records });
    const done = new Set([...(j.saved || []), ...(j.duplicates || [])]);
    const left = pending().filter(x => !done.has(x.uuid));
    put(left);
    $("msg").innerHTML = `<div class="ok">✓ ส่งเข้า Google Sheets ${j.saved.length} รายการ` +
      (j.duplicates.length ? `, เคยส่งแล้ว ${j.duplicates.length}` : "") + `; ค้าง ${left.length}</div>`;
  } catch (e) {
    $("msg").innerHTML = `<div class="err">Sync ไม่สำเร็จ: ${esc(e.message)} — ข้อมูลยังอยู่ในเครื่อง</div>`;
  } finally { $("btnSync").disabled = false; }
}

function renderPlan() {
  $("warnings").innerHTML = master.warnings.map(x => `<div class="warn">⚠ ${esc(x)}</div>`).join("");
  $("planTable").innerHTML = "<table><tr><th>ตำบล</th><th>N</th><th>n</th><th>Cluster</th></tr>" +
    Object.keys(master.targets).map(t => `<tr><td>${esc(t)}</td><td>${master.population[t].toLocaleString()}</td><td>${master.targets[t]}</td><td>${master.clusters[t]}</td></tr>`).join("") + "</table>";
}

function renderLocal() {
  const a = pending();
  $("localcount").textContent = a.length;
  const rows = a.map(x => {
    const f = qcFlags(x, a);
    return `<tr><td>${esc(x.tambon)}<br><small>ม.${esc(x.moo)} ${esc(x.village)}</small></td><td>${esc(x.activity)}<br><small>${esc(x.respondent_code)}</small></td>` +
      `<td><span class="badge">${esc(x.qc)}</span>${f.map(y => `<span class="badge bad">${esc(y)}</span>`).join("")}</td>` +
      `<td><button class="danger" data-del="${esc(x.uuid)}">ลบ</button></td></tr>`;
  }).join("");
  $("qcTable").innerHTML = a.length ? "<table><tr><th>พื้นที่</th><th>กิจกรรม/รหัส</th><th>QC</th><th></th></tr>" + rows + "</table>" : "<p>ไม่มีข้อมูลค้างในเครื่อง</p>";
}

async function loadSummary() {
  $("dashMsg").innerHTML = `<div class="warn">กำลังโหลด…</div>`;
  try {
    const s = await api("GET", { action: "summary" });
    const t = master.targets;
    const body = Object.keys(t).map(k => {
      const n = s.byTambon[k] || 0, pct = Math.min(100, Math.round(n / t[k] * 100));
      return `<tr><td>${esc(k)}</td><td>${n}</td><td>${t[k]}</td><td><div class="bar"><i style="width:${pct}%"></i></div>${pct}%</td></tr>`;
    }).join("");
    const tags = o => Object.entries(o).map(([k, v]) => `<span class="badge">${esc(k)}: ${v}</span>`).join(" ");
    $("dashMsg").innerHTML = `<div class="ok">ส่วนกลาง ${s.total} รายการ / เป้าหมาย ${master.sample_total} • รอ Sync ในเครื่อง ${pending().length} • อัปเดต ${new Date(s.updated_at).toLocaleString("th-TH")}</div>`;
    $("dashTable").innerHTML = "<table><tr><th>ตำบล</th><th>เก็บแล้ว</th><th>เป้า n</th><th>ความก้าวหน้า</th></tr>" + body + "</table>" +
      `<p><b>กิจกรรม</b><br>${tags(s.byActivity)}</p><p><b>QC</b><br>${tags(s.byQc)}</p><p><b>ทีม</b><br>${tags(s.byTeam)}</p>`;
  } catch (e) {
    $("dashMsg").innerHTML = `<div class="err">โหลดสรุปไม่ได้: ${esc(e.message)}</div>`;
    $("dashTable").innerHTML = "";
  }
}

function downloadCsv(headers, rows, name) {
  const cell = v => { let s = String(v ?? ""); if (/^[=+\-@]/.test(s)) s = "'" + s; return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  const csv = "﻿" + [headers, ...rows].map(r => r.map(cell).join(",")).join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
async function exportServer() {
  try { const j = await api("GET", { action: "export" }); downloadCsv(j.headers, j.rows, "field_data.csv"); }
  catch (e) { $("dashMsg").innerHTML = `<div class="err">ส่งออกไม่ได้: ${esc(e.message)}</div>`; }
}
function exportLocal() {
  const h = ["uuid", "created_at", "team", "activity", "tambon", "moo", "village", "respondent_code", "consent", "lat", "lon", "accuracy", "note", "qc"];
  downloadCsv(h, pending().map(x => h.map(k => x[k])), "field_data_pending_local.csv");
}

async function saveSettings() {
  localStorage.setItem(SET, JSON.stringify({ apiUrl: $("apiUrl").value.trim(), key: $("teamKey").value }));
  $("setMsg").innerHTML = `<div class="warn">กำลังทดสอบการเชื่อมต่อ…</div>`;
  try { const j = await api("GET", { action: "ping" }); $("setMsg").innerHTML = `<div class="ok">✓ เชื่อมต่อสำเร็จ — ชีต ${esc(j.sheet)} มี ${j.rows} รายการ</div>`; $("msg").innerHTML = ""; }
  catch (e) { $("setMsg").innerHTML = `<div class="err">เชื่อมต่อไม่ได้: ${esc(e.message)}</div>`; }
}

function netState() { $("net").style.display = navigator.onLine ? "none" : "inline"; }

document.querySelectorAll("#tabs button").forEach(b => b.onclick = () => show(b.dataset.tab));
$("btnGps").onclick = gps; $("btnSave").onclick = saveLocal; $("btnSync").onclick = sync;
$("btnRefresh").onclick = loadSummary; $("btnCsv").onclick = exportServer; $("btnCsvLocal").onclick = exportLocal;
$("btnSaveSettings").onclick = saveSettings;
$("qcTable").onclick = e => {
  const id = e.target.dataset && e.target.dataset.del;
  if (id && confirm("ลบรายการนี้ออกจากเครื่อง? (ยังไม่ได้ Sync)")) put(pending().filter(x => x.uuid !== id));
};
addEventListener("online", () => { netState(); if (pending().length && settings().apiUrl) sync(); });
addEventListener("offline", netState);
netState();
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
init();
