/**
 * Wang Sam Mo Field Research — Google Apps Script backend
 * แทนที่ Flask (app.py) ทั้งหมด: รับข้อมูลจาก PWA, กันข้อมูลซ้ำด้วย uuid,
 * สรุป Dashboard และส่งข้อมูลให้ Export CSV — ทำงานบน Google ไม่ต้องมี Python
 *
 * ตั้งค่า (Project Settings → Script properties) — ไม่บังคับ:
 *   TEAM_KEY = รหัสทีม (ถ้าตั้ง ทุกคำขอต้องส่งรหัสนี้มา)
 */
const SPREADSHEET_ID = "1lfrkQ34ztLWGwjnN_a6tKn6diPiyP3_81NPVrE6bdiU";
const TARGET_SHEET = "28_Field_App_Data";
const HEADERS = ["uuid", "created_at", "received_at", "team", "activity", "tambon", "moo", "village",
  "respondent_code", "consent", "lat", "lon", "accuracy", "note", "qc", "qc_flags", "app_version"];

function doPost(e) {
  try {
    const body = JSON.parse((e && e.postData && e.postData.contents) || "{}");
    checkKey_(body.key);
    const records = Array.isArray(body.records) ? body.records : [body];
    return json_(saveRecords_(records));
  } catch (err) {
    return json_({ ok: false, error: String(err.message || err) });
  }
}

function doGet(e) {
  try {
    const p = (e && e.parameter) || {};
    checkKey_(p.key);
    const action = p.action || "ping";
    if (action === "ping") return json_({ ok: true, sheet: TARGET_SHEET, rows: sheet_().getLastRow() - 1 });
    if (action === "summary") return json_(summary_());
    if (action === "export") return json_({ ok: true, headers: HEADERS, rows: rows_() });
    return json_({ ok: false, error: "unknown action" });
  } catch (err) {
    return json_({ ok: false, error: String(err.message || err) });
  }
}

function checkKey_(key) {
  const expected = PropertiesService.getScriptProperties().getProperty("TEAM_KEY");
  if (expected && String(key || "") !== expected) throw new Error("รหัสทีมไม่ถูกต้อง (TEAM_KEY)");
}

function sheet_() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  let sh = ss.getSheetByName(TARGET_SHEET);
  if (!sh) {
    sh = ss.insertSheet(TARGET_SHEET);
    sh.appendRow(HEADERS);
    sh.setFrozenRows(1);
    sh.getRange(1, 1, 1, HEADERS.length).setFontWeight("bold");
  }
  return sh;
}

function saveRecords_(records) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const sh = sheet_();
    const last = sh.getLastRow();
    const existing = new Set(last > 1 ? sh.getRange(2, 1, last - 1, 1).getValues().map(r => String(r[0])) : []);
    const saved = [], duplicates = [], invalid = [], out = [];
    const now = new Date().toISOString();
    records.forEach(x => {
      if (!x || !x.uuid || !x.tambon || !x.village || !x.activity) { invalid.push(x && x.uuid); return; }
      if (existing.has(String(x.uuid))) { duplicates.push(x.uuid); return; }
      existing.add(String(x.uuid));
      out.push(HEADERS.map(h => {
        if (h === "received_at") return now;
        const v = x[h];
        if (v === undefined || v === null) return "";
        // กันสูตรที่ถูกฉีดเข้ามาในข้อความ (=, +, -, @)
        return typeof v === "string" && /^[=+\-@]/.test(v) ? "'" + v : v;
      }));
      saved.push(x.uuid);
    });
    if (out.length) sh.getRange(sh.getLastRow() + 1, 1, out.length, HEADERS.length).setValues(out);
    return { ok: true, saved: saved, duplicates: duplicates, invalid: invalid };
  } finally {
    lock.releaseLock();
  }
}

function rows_() {
  const sh = sheet_();
  const last = sh.getLastRow();
  if (last < 2) return [];
  return sh.getRange(2, 1, last - 1, HEADERS.length).getDisplayValues();
}

function summary_() {
  const idx = name => HEADERS.indexOf(name);
  const byTambon = {}, byActivity = {}, byQc = {}, byTeam = {};
  const rows = rows_();
  const inc = (o, k) => { k = k || "(ว่าง)"; o[k] = (o[k] || 0) + 1; };
  rows.forEach(r => {
    inc(byTambon, r[idx("tambon")]);
    inc(byActivity, r[idx("activity")]);
    inc(byQc, r[idx("qc")]);
    inc(byTeam, r[idx("team")]);
  });
  return { ok: true, total: rows.length, byTambon, byActivity, byQc, byTeam, updated_at: new Date().toISOString() };
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
