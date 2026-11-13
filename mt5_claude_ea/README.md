# Claude AI MT5 EA (M5) — แพ็กเกจพัฒนา

> **สถานะ: ยังไม่ผ่านเกณฑ์รับมอบ ห้ามใช้กับเงินจริง**
> โค้ด MQL5 ในแพ็กเกจนี้ **ยังไม่เคยถูก compile ใน MetaEditor และยังไม่เคยรันใน Strategy Tester/บัญชี demo**
> (เครื่องที่ใช้พัฒนาไม่มี MetaTrader) รายการที่ยังเปิดอยู่ทั้งหมดอยู่ใน [docs/TEST_REPORT.md](docs/TEST_REPORT.md)
> ไม่มีข้ออ้างเรื่องกำไรใด ๆ ในแพ็กเกจนี้

AI (Claude) ให้สัญญาณ BUY/SELL/HOLD จากแท่ง M5 ที่ปิดแล้ว 20 แท่ง ผ่าน bridge ภาษา Python ที่รันบนเครื่องเดียวกัน
ส่วน EA เป็นผู้ตัดสินใจทั้งหมดว่าจะส่งคำสั่งหรือไม่ AI ไม่มีสิทธิ์กำหนด lot, SL/TP หรือพารามิเตอร์ความเสี่ยงใด ๆ

```
MT5 OnTick  -> ป้องกันสถานะ (BE / trailing / daily stop / quick profit)   ไม่มี HTTP
MT5 OnTimer -> แท่ง M5 ปิดใหม่ -> POST /v1/signal -> poll GET /v1/signal/{id}
                                     |
                         bridge (127.0.0.1) -> background worker: retry + circuit breaker
                                     |
                         Anthropic Messages API (structured output) -> ตรวจ schema -> (โหวต 3 รุ่น ถ้าเปิด)
EA: ตรวจ guard 18 ข้อตามลำดับ -> CTrade (ส่งครั้งเดียว ไม่ retry)
```

ทุกความผิดพลาด (API ล่ม, 400/401/429/5xx/529, timeout, JSON ผิด schema, ข้อมูลไม่ครบ, token ผิด) ให้ผล **HOLD**

## โครงสร้าง

| ที่อยู่ | หน้าที่ |
|---|---|
| `EA/Claude_AI_MT5.mq5` | EA หลัก: state machine, guard, การจัดการสถานะ |
| `EA/Include/ClaudeEA/Json.mqh` | JSON parser แบบ strict (flat object เท่านั้น) |
| `EA/Include/ClaudeEA/Sessions.mqh` | session London/New York พร้อมปฏิทิน DST ของ EU/US |
| `EA/Include/ClaudeEA/Risk.mqh` | volume, SL/TP, break-even/trailing (monotonic), daily breach |
| `EA/Include/ClaudeEA/Execution.mqh` | ความเป็นเจ้าของ position (magic+symbol), P/L รายวัน, CTrade |
| `EA/Include/ClaudeEA/Bridge.mqh` | HTTP client ไปยัง bridge + ตรวจคำตอบ |
| `EA/Include/ClaudeEA/Replay.mqh` | อ่านสัญญาณย้อนหลังใน Strategy Tester |
| `EA/Include/ClaudeEA/Audit.mqh` | audit log CSV |
| `EA/Scripts/ClaudeEA_SelfTest.mq5` | unit test ในเทอร์มินัล (เวกเตอร์เดียวกับ pytest) |
| `EA/Scripts/ClaudeEA_ExportBars.mq5` | ส่งออกแท่ง M5 เป็น CSV สำหรับสร้าง replay |
| `bridge/` | FastAPI bridge: `server` `service` `providers` `voting` `retry` `parsing` `store` `audit` `sessions` `config` |
| `refmodel/` | reference model ภาษา Python ของกฎฝั่ง EA (ใช้ทดสอบ logic และ replay) |
| `replay/` | สร้างสัญญาณย้อนหลังแบบไม่มี look-ahead, backtest ระดับแท่ง, metrics |
| `tests/` | pytest 205 ข้อ |

## ติดตั้ง

### 1. Bridge

```bash
cd mt5_claude_ea
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

```bash
python -m bridge --new-token
```

คัดลอก `.env.example` เป็น `.env` แล้วใส่ token ที่ได้ใน `BRIDGE_TOKEN` (คนละตัวกับ Anthropic API key)
ค่าเริ่มต้นคือ `AI_ENABLED=false` ซึ่งให้ HOLD ทุกครั้ง จากนั้นรัน

```bash
python -m bridge
```

Bridge ผูกกับ `127.0.0.1` เท่านั้น และปฏิเสธการตั้งค่า host อื่น

### 2. MT5

1. คัดลอก `EA/Include/ClaudeEA/` ไปที่ `<Data Folder>/MQL5/Include/ClaudeEA/`
2. คัดลอก `EA/Claude_AI_MT5.mq5` ไปที่ `MQL5/Experts/` และ `EA/Scripts/*.mq5` ไปที่ `MQL5/Scripts/`
3. compile ทั้งสามไฟล์ใน MetaEditor **บันทึก log การ compile (errors/warnings) ไว้** เพราะยังไม่เคยทำ
4. รันสคริปต์ `ClaudeEA_SelfTest` ต้องได้ `SELFTEST PASSED`
5. สร้างไฟล์ `MQL5/Files/claude_bridge_token.txt` ใส่ token เดียวกับ `BRIDGE_TOKEN` (บรรทัดเดียว)
6. Tools > Options > Expert Advisors > Allow WebRequest: เพิ่ม `http://127.0.0.1:8765`
7. วาง EA บนกราฟ ตรวจ `InpSymbolAllowlist` ให้ตรงชื่อสัญลักษณ์ของโบรกเกอร์ (เช่น `XAUUSD` หรือ `XAUUSDm`) และแก้ `SYMBOL_ALLOWLIST` ใน `.env` ให้ตรงกัน

`InpAllowOrders=false` เป็นค่าเริ่มต้น EA จะบันทึกสัญญาณและผล guard โดยไม่ส่งคำสั่ง

### 3. สิ่งที่ต้องยืนยันกับโบรกเกอร์ก่อนเปิดคำสั่ง (ยังไม่ได้ยืนยัน)

ชื่อสัญลักษณ์, digits, point/tick size, volume min/step/max, สกุลเงินบัญชี, เวลา server และกฎ DST,
hedging หรือ netting, spread ปกติ, stops level และ freeze level ค่าพวกนี้ EA อ่านจากโบรกเกอร์ตอนรัน
แต่ค่าตั้งต้น `InpMaxSpreadPoints`, `InpFixedLot`, `InpServerStdOffsetHours`, `InpServerDstRule` ต้องตั้งเองให้ตรง

## Strategy Tester (AI historical replay)

Tester เรียก WebRequest ไม่ได้ จึงใช้ไฟล์สัญญาณที่สร้างไว้ก่อน

1. รัน `ClaudeEA_ExportBars` บนกราฟ ได้ `Common\Files\<symbol>_M5.csv` (เวลาเป็น server time)
2. สร้างสัญญาณ: แต่ละแท่งใช้ข้อมูล 20 แท่งที่ปิดแล้วจนถึงแท่งนั้นเท่านั้น

```bash
python -m replay.generate --bars XAUUSD_M5.csv --out claude_replay_signals.csv --provider anthropic --confirm-cost
```

   (`--provider mock` ใช้กฎ momentum แทน AI สำหรับทดสอบ pipeline และไม่มีค่าใช้จ่าย)
3. วาง `claude_replay_signals.csv` ใน `Common\Files\`
4. ใน tester ตั้ง `InpServerTimeMode=MANUAL` พร้อม offset/DST ของโบรกเกอร์ และ `InpAllowOrders=true`

Backtest ระดับแท่งด้วย Python (ประมาณการแบบ pessimistic ไม่ใช่ตัวแทนของ MT5 tester):

```bash
python -m replay.backtest --bars XAUUSD_M5.csv --signals claude_replay_signals.csv
```

## พฤติกรรมสำคัญ

- **Entry**: หนึ่งการประเมินต่อแท่ง M5 ที่ปิด, session London/New York (Asia ปิด), spread, margin, volume step, stops level,
  managed position ได้สูงสุด 1, cooldown, จำนวนเทรดต่อวัน, slippage สูงสุด, สัญญาณต้องเป็นของแท่งล่าสุดและไม่เก่าเกินกำหนด
- **SL/TP**: SL 1 ATR, TP 3 ATR, ย้าย SL ไปจุดเข้าเมื่อกำไร 1 ATR, trailing ระยะ 1 ATR เมื่อกำไร 1.5 ATR
  SL ของ BUY ไม่ลดลง ของ SELL ไม่เพิ่มขึ้น buffer ของ BE ตั้งได้เป็นจำนวน tick (ค่าเริ่มต้น 0)
- **Daily stop**: +200 / −100 สกุลเงินบัญชี คิดจาก realized + floating รวม commission/swap เฉพาะ position ของ EA
  เมื่อถึงเกณฑ์จะ latch, ปิด position ของ EA และไม่เข้าใหม่จนขึ้นวันใหม่ของโบรกเกอร์ latch เก็บใน GlobalVariables ของเทอร์มินัล
- **Quick Profit** (ปิดไว้): ปิด position ของ EA เมื่อ floating รวม ≥ 9
- **Reverse** (ปิดไว้): สัญญาณตรงข้าม → ปิด → ตรวจว่าปิดจริง → ตรวจ guard ใหม่ทั้งหมด → จึงเปิดฝั่งตรงข้าม
- **HOLD** ไม่ปิด position เว้นแต่เปิด `InpCloseOnHold`
- **Voting** (ปิดไว้): ต้องมี 3 รุ่นที่ต่างกันและตอบครบทั้ง 3, ต้องได้ BUY หรือ SELL ตรงกัน 2 ใน 3, confidence เป็นค่าเฉลี่ยของเสียงที่ตรงกัน
  เสียงของโมเดลมีความสัมพันธ์กันสูง จึงไม่ใช่หลักฐานทางสถิติที่อิสระต่อกัน
- **Confidence** เป็นการประเมินตัวเองของโมเดลที่ยังไม่ได้ calibrate ไม่ใช่ความน่าจะเป็นที่จะชนะ

## รุ่นของโมเดล

ค่าเริ่มต้น `claude-opus-5-5` รุ่นสำหรับโหวต `claude-opus-5-5,claude-sonnet-5-5,claude-haiku-5-5`
รหัสรุ่นตรวจจากเอกสาร Anthropic (ข้อมูล ณ 2026-11-03) และ bridge จะถาม Models API ก่อนใช้ครั้งแรก
รุ่นที่ API ไม่รู้จักให้ผล HOLD เสมอ ยังไม่เคยทดสอบกับ API จริงในแพ็กเกจนี้

## Rollback

1. ปิดปุ่ม Algo Trading หรือถอด EA ออกจากกราฟ position ที่เปิดอยู่ยังมี SL/TP ฝั่ง server
2. ตั้ง `InpAllowOrders=false` และ/หรือ `AI_ENABLED=false` แล้วเริ่ม bridge ใหม่
3. ล้างสถานะ: ลบ GlobalVariables ที่ขึ้นต้นด้วย `CAI_<magic>_<symbol>_` (F3 ใน MT5) และไฟล์ `bridge_state.sqlite3`
   การลบ `..._LATCH` คือการปลด daily stop ด้วยมือ
4. ย้อนโค้ด: `git revert` commit ของแพ็กเกจนี้ ไม่มีส่วนใดแตะโค้ด `smc/` เดิม
