# Wang Sam Mo Field Research — Web App ออนไลน์ (ไม่ต้องติดตั้ง Python)

ทีมวิจัยเปิดใช้งานจากลิงก์บนมือถือ/คอมพิวเตอร์ได้ทันที และ "เพิ่มลงหน้าจอหลัก" ให้ใช้เหมือนแอป ทำงานได้แม้ไม่มีสัญญาณ

**ลิงก์แอป (หลัง Deploy):** https://63202501015-sketch.github.io/AI-order-Flow-Trading/

## สถาปัตยกรรม

```
มือถือทีมวิจัย (PWA บน GitHub Pages)          Google (ฟรี)
 ├ บันทึกลงเครื่อง (offline ได้)    ── Sync ──►  Apps Script Web App (/exec)
 ├ GPS / QC / Field Note                          └► Google Sheets ชีต 28_Field_App_Data
 └ Dashboard / CSV                   ◄─ สรุป ──     (ลงพื้นที่วิจัย วังสามหมอ)
```

แทน Flask + SQLite เดิมทั้งหมด: `app.py` → `apps_script/Code.gs` (ทำงานบน Google), หน้าเว็บ → ไฟล์ static บน GitHub Pages

## ขั้นตอน Deploy (ผู้ดูแลทำครั้งเดียว ~10 นาที)

### 1) ตั้ง Backend: Google Apps Script
1. เปิดชีต **ลงพื้นที่วิจัย วังสามหมอ** → เมนู **ส่วนขยาย → Apps Script**
2. ลบโค้ดเดิม วางเนื้อหาไฟล์ [`apps_script/Code.gs`](apps_script/Code.gs) → บันทึก
3. (แนะนำ) ⚙️ **Project Settings → Script properties → Add** : `TEAM_KEY` = รหัสทีม เช่น `wsm2569` แล้วแจ้งทีมทางช่องทางภายใน
4. **Deploy → New deployment** → ประเภท **Web app**
   - Execute as: **Me**
   - Who has access: **Anyone**
5. กด Authorize → คัดลอก **Web app URL** (ลงท้าย `/exec`)

> แก้โค้ดภายหลัง: Deploy → **Manage deployments** → ✏️ → Version: **New version** (URL เดิมใช้ต่อได้)

### 2) ตั้ง Frontend: GitHub Pages
1. GitHub repo → **Settings → Pages → Build and deployment → Source: GitHub Actions**
2. (ไม่บังคับ) ใส่ URL จากข้อ 1 ใน `field_app/config.js` ที่ `API_URL: "…/exec"` เพื่อให้ทุกเครื่องได้ค่าอัตโนมัติ
   ถ้าไม่ใส่ ให้แต่ละคนวาง URL ในแท็บ **ตั้งค่า** ของแอป
3. Merge เข้า default branch หรือ **Actions → Deploy Field App → Run workflow**
4. เปิด https://63202501015-sketch.github.io/AI-order-Flow-Trading/

### 3) ทีมวิจัยใช้งาน
1. เปิดลิงก์ใน Chrome (Android) / Safari (iPhone) → **เพิ่มลงหน้าจอหลัก**
2. แท็บ **ตั้งค่า** → ใส่ URL และรหัสทีม → **บันทึกและทดสอบ** ต้องขึ้น ✓
3. เก็บข้อมูล → **บันทึกข้อมูล** (เก็บในเครื่อง) → มีสัญญาณแล้วกด **Sync ส่วนกลาง** (หรือ Sync อัตโนมัติเมื่อกลับมาออนไลน์)

## ความปลอดภัยของข้อมูล
- ข้อมูลภาคสนามอยู่ใน Google Sheets ของผู้วิจัยเท่านั้น ไม่เก็บใน GitHub (repo นี้เป็น public — ห้ามใส่ข้อมูลผู้ให้ข้อมูล/TEAM_KEY ในโค้ด)
- ใช้รหัสผู้ให้ข้อมูล ไม่ใช้ชื่อ-สกุล; ตั้ง `TEAM_KEY` เพื่อกันคนนอกส่ง/อ่านข้อมูลผ่าน URL
- กันข้อมูลซ้ำด้วย `uuid` — กด Sync ซ้ำได้ไม่เกิดแถวซ้ำ

## ข้อมูลพื้นฐาน
6 ตำบล, 72 หมู่บ้าน, N=46,053, n จัดสรร=426, 30 clusters, m≈15/cluster
ชื่อหมู่บ้านซ้ำในฐานต้นทางถูกคงไว้และเตือนให้ยืนยัน ไม่แก้เอง
