# คู่มือติดตั้งและใช้งาน — Claude AI MT5 EA

> **ใช้กับบัญชี demo หรือ Strategy Tester เท่านั้น** โค้ด MQL5 ยังไม่เคยผ่าน compiler และยังไม่เคยเรียก Anthropic API จริง
> ถ้า compile แล้วมี error ให้คัดลอกข้อความ error ส่งกลับมาเพื่อแก้

## สิ่งที่ต้องมี

- Windows ที่ติดตั้ง MetaTrader 5 (บัญชี demo)
- Python 3.10 ขึ้นไป (ตอนติดตั้งให้ติ๊ก "Add Python to PATH")
- API key จาก Claude Console (https://platform.claude.com) ซึ่งเป็นคนละบริการกับสมาชิก claude.ai และต้องเติมเครดิตแยก

## ส่วนที่ 1 — ติดตั้ง bridge (Python)

แตกไฟล์ zip ไว้ที่ใดก็ได้ เช่น `C:\ClaudeEA\` แล้วเปิด Command Prompt ในโฟลเดอร์ `mt5_claude_ea`

1. สร้างสภาพแวดล้อม

```bash
python -m venv .venv
```

2. เปิดใช้งาน (ต้องทำทุกครั้งที่เปิดหน้าต่างใหม่)

```bash
.venv\Scripts\activate
```

3. ติดตั้งไลบรารี

```bash
pip install -r requirements.txt
```

4. สร้าง token สำหรับให้ EA คุยกับ bridge (คัดลอกผลลัพธ์เก็บไว้)

```bash
python -m bridge --new-token
```

5. สร้างไฟล์ตั้งค่า

```bash
copy .env.example .env
```

6. เปิด `.env` ด้วย Notepad แล้วแก้บรรทัด `BRIDGE_TOKEN=` ให้เป็น token จากข้อ 4 บันทึกไฟล์

## ส่วนที่ 2 — ติดตั้งใน MT5

ใน MT5 กด **File > Open Data Folder** จะเห็นโฟลเดอร์ `MQL5`

| คัดลอกจาก (ใน zip) | ไปที่ (ใน Data Folder) |
|---|---|
| `EA\Include\ClaudeEA\` (ทั้งโฟลเดอร์) | `MQL5\Include\ClaudeEA\` |
| `EA\Claude_AI_MT5.mq5` | `MQL5\Experts\` |
| `EA\Scripts\ClaudeEA_SelfTest.mq5` | `MQL5\Scripts\` |
| `EA\Scripts\ClaudeEA_ExportBars.mq5` | `MQL5\Scripts\` |

จากนั้น

1. สร้างไฟล์ `MQL5\Files\claude_bridge_token.txt` ใส่ token เดียวกับใน `.env` บรรทัดเดียว ไม่มีช่องว่าง
2. กด **F4** เปิด MetaEditor เปิดไฟล์ทั้งสามแล้วกด **F7** (Compile) ทีละไฟล์ ต้องได้ `0 errors`
3. ใน MT5 ไปที่ **Tools > Options > Expert Advisors** ติ๊ก **Allow WebRequest for listed URL** แล้วเพิ่ม `http://127.0.0.1:8765`
4. ลากสคริปต์ `ClaudeEA_SelfTest` ลงกราฟใดก็ได้ ดูแท็บ **Experts** ต้องขึ้น `SELFTEST PASSED`

## ส่วนที่ 3 — ใช้งานทีละระดับ

### ระดับ 1: ตรวจว่าระบบต่อกันได้ (ไม่เรียก AI ไม่มีค่าใช้จ่าย)

1. รัน bridge ทิ้งไว้ในหน้าต่าง Command Prompt

```bash
python -m bridge
```

2. เปิดกราฟทองคำ timeframe **M5** ลาก `Claude_AI_MT5` ลงกราฟ
3. ในแท็บ Inputs ตั้ง `InpSymbolAllowlist` ให้ตรงชื่อสัญลักษณ์ของโบรกเกอร์ทุกตัวอักษร (เช่น `XAUUSD`, `XAUUSDm`, `GOLD`)
   และแก้ `SYMBOL_ALLOWLIST=` ใน `.env` ให้ตรงกัน แล้วรัน bridge ใหม่
4. เปิดปุ่ม **Algo Trading**

รอแท่ง M5 ปิด จะเห็นในแท็บ Experts: `ClaudeEA: ... SIGNAL ... HOLD ... AI disabled`
ถ้าขึ้น `NOT_ASKED ... outside allowed sessions` แปลว่าอยู่นอกช่วง London/New York ซึ่งถูกต้องแล้ว

### ระดับ 2: เปิด AI แต่ยังไม่ส่งคำสั่ง

1. แก้ `.env`

```
ANTHROPIC_API_KEY=sk-ant-...(key ของคุณ)
AI_ENABLED=true
```

2. ทดสอบการเชื่อมต่อจริง (เรียก API 1 ครั้ง เสียไม่กี่เซนต์)

```bash
python -m bridge.smoke
```

   ต้องขึ้น `SMOKE TEST PASSED` พร้อม latency และค่าใช้จ่ายโดยประมาณต่อวัน

3. ปิด bridge ด้วย Ctrl+C แล้วรัน `python -m bridge` ใหม่

EA จะบันทึกสัญญาณ BUY/SELL/HOLD พร้อมเหตุผล และขึ้น `GATE ... BLOCKED ... live orders not enabled` โดยไม่เปิดออเดอร์
แนะนำให้รันระดับนี้ 2–4 สัปดาห์ แล้ววัดคุณภาพสัญญาณตามส่วนที่ 5 ก่อนไประดับ 3

### ระดับ 3: ให้ EA ส่งคำสั่ง (demo เท่านั้น)

ตั้ง `InpAllowOrders=true` และตรวจค่าเหล่านี้ก่อน

| Input | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `InpFixedLot` | 0.01 | ขนาด lot |
| `InpMaxSpreadPoints` | 35 | spread เกินนี้ไม่เข้า ปรับตามโบรกเกอร์ |
| `InpMinConfidence` | 60 | confidence ต่ำกว่านี้ไม่เข้า |
| `InpMaxTradesPerDay` | 6 | เทรดสูงสุดต่อวัน |
| `InpCooldownSec` | 900 | เว้นระยะระหว่างไม้ (วินาที) |
| `InpDailyProfit` / `InpDailyLoss` | 200 / 100 | หยุดทั้งวันเมื่อถึงเกณฑ์ (สกุลเงินบัญชี) |
| `InpServerTimeMode` | AUTO | ถ้า session คลาดเวลา ให้ใช้ MANUAL แล้วใส่ offset ของโบรกเกอร์ |
| `InpQuickProfit`, `InpReverseMode`, `InpCloseOnHold` | false | ตัวเลือกเสริม ปิดไว้ทั้งหมด |

## ส่วนที่ 4 — ดูผลและหยุดฉุกเฉิน

- แท็บ **Experts** ใน MT5: ทุกบรรทัดขึ้นต้นด้วย `ClaudeEA:`
- `MQL5\Files\ClaudeEA_audit_<symbol>_<magic>.csv`: สัญญาณ ผล guard ออเดอร์ การเลื่อน SL
- `logs\bridge_audit.jsonl`: รุ่นโมเดล latency ค่าใช้จ่ายโดยประมาณ

**หยุดฉุกเฉิน**: ปิดปุ่ม Algo Trading หรือถอด EA ออกจากกราฟ ออเดอร์ที่เปิดอยู่ยังมี SL/TP ฝั่ง server

## ส่วนที่ 5 — วัดว่าสัญญาณ AI ใช้ได้หรือไม่ (ไม่ต้องเปิดคำสั่ง)

1. ลากสคริปต์ `ClaudeEA_ExportBars` ลงกราฟทองคำ จะได้ไฟล์ `<symbol>_M5.csv` ในโฟลเดอร์ Common\Files
   (เปิดได้จาก MetaEditor: File > Open Common Data Folder > Files)
2. คัดลอกไฟล์นั้นมาไว้ในโฟลเดอร์ `mt5_claude_ea` แล้วรัน

```bash
python -m replay.score --bars XAUUSD_M5.csv --audit logs/bridge_audit.jsonl
```

อ่านบรรทัด `verdict` ท้ายผลลัพธ์ ถ้าสัญญาณ BUY/SELL ยังไม่ถึง 100 ครั้งจะบอกว่ายังตัดสินไม่ได้

## ส่วนที่ 6 — ทดสอบย้อนหลังใน Strategy Tester

Tester เรียก bridge ไม่ได้ จึงต้องสร้างไฟล์สัญญาณก่อน

1. ส่งออกแท่งตามส่วนที่ 5 ข้อ 1
2. สร้างสัญญาณ (เรียก API จริงหนึ่งครั้งต่อแท่ง **มีค่าใช้จ่าย** คำสั่งจะแจ้งจำนวนครั้งก่อนถ้าไม่ใส่ `--confirm-cost`)

```bash
python -m replay.generate --bars XAUUSD_M5.csv --out claude_replay_signals.csv --provider anthropic --confirm-cost --server-utc-offset-hours 2
```

   ใช้ `--provider mock` แทนเพื่อทดลองขั้นตอนโดยไม่เสียเงิน (เป็นกฎจำลอง ไม่ใช่ AI)
3. คัดลอก `claude_replay_signals.csv` ไปไว้ใน Common\Files
4. ใน Strategy Tester เลือก EA, สัญลักษณ์, M5 แล้วตั้ง `InpAllowOrders=true`, `InpServerTimeMode=MANUAL`,
   `InpServerStdOffsetHours` และ `InpServerDstRule` ตามโบรกเกอร์

ผล backtest บนข้อมูลที่เก่ากว่าวันตัดข้อมูลฝึกของโมเดลเชื่อได้ไม่เต็มที่ เพราะโมเดลอาจเคยเห็นราคาช่วงนั้น

## แก้ปัญหาที่พบบ่อย

| อาการ | สาเหตุและวิธีแก้ |
|---|---|
| Alert `symbol ... is not in InpSymbolAllowlist` | ชื่อสัญลักษณ์ไม่ตรง แก้ `InpSymbolAllowlist` |
| Alert `bridge token file missing/invalid` | ไม่มี `MQL5\Files\claude_bridge_token.txt` หรือ token สั้นกว่า 32 ตัวอักษร |
| `bridge unavailable` / `bridge http -1` | bridge ไม่ได้รัน หรือยังไม่ได้เพิ่ม URL ใน Allow WebRequest |
| `bridge http 401` | token ในไฟล์ MT5 ไม่ตรงกับ `BRIDGE_TOKEN` ใน `.env` |
| `symbol not in bridge allowlist` | แก้ `SYMBOL_ALLOWLIST` ใน `.env` แล้วรัน bridge ใหม่ |
| `stale bar` | นาฬิกาเครื่องคลาด หรือ offset เวลา server ผิด ลอง `InpServerTimeMode=MANUAL` |
| `auth:401` ใน bridge log | API key ผิด |
| `model id not available` | บัญชีไม่มีสิทธิ์ใช้รุ่นนั้น เปลี่ยน `ANTHROPIC_MODEL` |
| `daily AI budget reached` | ถึงเพดาน `MAX_DAILY_COST_USD` แล้ว รอวันใหม่ (UTC) หรือปรับค่า |
| `circuit breaker open` | ล้มเหลวติดกันหลายครั้ง แก้สาเหตุแล้วรัน bridge ใหม่ |

ทุกกรณีข้างต้น EA ได้ HOLD และไม่เปิดออเดอร์
