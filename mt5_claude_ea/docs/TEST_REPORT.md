# Test report — 2026-11-13

**ข้อสรุป: ยังไม่ผ่านเกณฑ์รับมอบ ห้ามใช้เงินจริง** ส่วน Python ผ่านเทสต์ครบ ส่วน MQL5 ยังไม่เคย compile หรือรัน

## 1. สิ่งที่รันจริงและผล

| รายการ | คำสั่ง | ผล |
|---|---|---|
| pytest (แพ็กเกจนี้) | `python -m pytest -q tests` | **205 passed**, 0 failed ([log](test_logs/pytest_summary.txt)) |
| pytest (ทั้ง repo รวม `smc/` เดิม) | `python -m pytest -q` จาก root | **217 passed** |
| MQL5 lexical lint | `python tools_mql_lint.py` | 10 ไฟล์ วงเล็บสมดุล ([log](test_logs/mql_lexical_lint.txt)) ตรวจได้แค่โครงสร้าง ไม่ใช่ compile |
| Replay pipeline | `replay.generate` + `replay.backtest` บนข้อมูล SYNTHETIC | รันจบ ([รายงาน](test_logs/replay_SYNTHETIC_mock_report.json)) |

สภาพแวดล้อม: Linux, Python 3.13.18, anthropic 2.8.0, fastapi 0.162.5, pydantic 2.13.5, pytest 9.2.0
ไม่มีการเรียก Anthropic API จริงแม้แต่ครั้งเดียว และไม่มี MetaTrader

### สิ่งที่ pytest ครอบคลุม

- **Fail-closed**: 401, 400, 403, 404, 429, 500, 503, 529, timeout, connection error, HTML error page, refusal, `max_tokens`,
  ข้อความที่ไม่ใช่ JSON, JSON ที่มีช่องเกิน → HOLD ทุกกรณี ทดสอบทั้งกับ provider จำลองและกับ **Anthropic SDK ตัวจริงที่ต่อกับ HTTP จำลอง**
- **Retry**: retry เฉพาะ 429/5xx/529/timeout/connection สูงสุด 5 ครั้ง (รวม 6 calls), ไม่ retry 400/401/403/404, หยุดเมื่อเลย deadline
- **Circuit breaker**: เปิดเมื่อพลาดติดกันครบเกณฑ์, 401 เปิดทันที, half-open ปล่อย probe เดียว
- **Dedup**: request id เดิมเรียก AI ครั้งเดียว, อยู่รอดหลัง bridge restart, คำขอที่ค้างตอน restart กลายเป็น HOLD
- **Voting**: 3/3, 2/3, แตกเสียง, ตอบไม่ครบ 3 (รวมกรณี BUY 2 เสียง + ล้มเหลว 1 → HOLD)
- **Security**: token, client ที่ไม่ใช่ loopback, Host header แปลกปลอม, Origin header, body เกินขนาด, ไม่มี secret ใน log
- **Sessions**: offset ของ London/New York ตรงกับ IANA ทุกชั่วโมงตั้งแต่ 2015 ถึง 2040
- **Risk logic** (reference model): volume ไม่ปัดขึ้น, SL monotonic บนเส้นทางสุ่ม 600 เส้น, stop/freeze level, daily latch + restart
- **Replay**: สัญญาณไม่ขึ้นกับแท่งในอนาคต, เข้าเทรดหลังแท่งสัญญาณปิดเสมอ, ไม่มีสอง position ซ้อนกัน, ไม่มีเทรดนอก session หรือ spread เกิน

## 2. ผล replay บนข้อมูลสังเคราะห์ (ไม่ใช่ผลการเทรด)

ข้อมูล: random walk สังเคราะห์ 20 วัน (5,760 แท่ง) สัญญาณจากกฎ momentum จำลอง **ไม่ใช่ AI และไม่ใช่ราคาตลาดจริง**
ใช้ยืนยันว่า pipeline ทำงานเท่านั้น ตัวเลขด้านล่างไม่บอกอะไรเกี่ยวกับกำไรขาดทุนของระบบจริง

| ชุด | เทรด | สุทธิ | Expectancy/เทรด | Win rate | PF | Max DD | 95% CI ของ expectancy |
|---|---|---|---|---|---|---|---|
| ทั้งหมด | 99 | −1,783.39 | −18.01 | 14.1% | 0.23 | 1,902.65 | −22.69 ถึง −12.75 |
| In-sample 70% | 72 | −1,224.60 | −17.01 | 15.3% | 0.25 | 1,343.86 | −22.77 ถึง −10.53 |
| Out-of-sample 30% | 27 | −558.79 | −20.70 | 11.1% | 0.16 | 558.79 | −28.05 ถึง −11.41 |

Walk-forward 4 ช่วง: −364.87, −443.19, −521.40, −453.93 · Monte Carlo 200 รอบ (slippage สุ่ม + พลาดสัญญาณ 10%): สุทธิ P5/P50/P95 = −1,870 / −1,776 / −1,654

ผลติดลบเป็นสิ่งที่คาดไว้บน random walk ข้อสังเกตเดียวที่นำไปใช้ได้คือ **ต้นทุน**: ความเสี่ยงต่อเทรด 25 แต่ spread + slippage + commission
รวม 1,177 จาก 99 เทรด หรือราว 11.9 ต่อเทรด คิดเป็นเกือบครึ่งของความเสี่ยงต่อเทรด เพราะ SL 1 ATR บน M5 แคบเมื่อเทียบกับ spread
ต้องตรวจซ้ำด้วย spread จริงของโบรกเกอร์ก่อนตัดสินใจเรื่องขนาด SL

## 3. ความไม่สอดคล้องที่พบในไฟล์ต้นแบบ

| ที่พบ | ปัญหา | สิ่งที่ทำ |
|---|---|---|
| `server.py` ส่ง `temperature: 0` | โมเดลปัจจุบันปฏิเสธพารามิเตอร์ sampling (400) จะกลายเป็น HOLD ตลอด | ไม่ส่ง; ใช้ structured output + `effort` |
| `server.py` ใช้ `claude-sonnet-4-5`, `max_tokens: 220` | รุ่นเก่า; 220 token ไม่พอเมื่อโมเดลใช้ thinking (ถูกตัด → HOLD) | ค่าเริ่มต้น `claude-opus-5-5`, 4096, ตรวจรุ่นผ่าน Models API |
| `server.py` เรียก API แบบ synchronous ใน request | EA ต้องรอ AI สูงสุด 20 วินาที ขัดกับข้อ 9 | เปลี่ยนเป็น submit (202) + poll, worker เบื้องหลัง |
| `server.py` ไม่มี request id | ไม่มี dedup ข้าม restart | request id = symbol + bar time + magic, เก็บใน SQLite |
| `server.py` ใช้ `httpx` ตรง | — | เปลี่ยนเป็น Anthropic SDK ทางการ (ปิด retry ของ SDK ให้ bridge คุมเอง) |
| Master prompt ข้อ 5 | BE = entry+200 points ในกราฟตัวอย่างไม่ตรงกับคำว่า break-even | buffer เป็นตัวเลือก หน่วยเป็น tick ค่าเริ่มต้น 0 |
| Master prompt ข้อ 4 "sessions in UTC with DST or IANA" | MQL5 ไม่มีฐานข้อมูล IANA | EA คำนวณปฏิทิน DST ของ EU/US เอง แล้วเทียบกับ IANA ใน pytest |
| Master prompt ข้อ 1 กล่าวถึง "H/L" แยกจาก OHLC | ไม่ชัดว่าหมายถึงอะไรเพิ่ม | ตีความว่าเป็น high/low ในแท่ง ไม่ได้เพิ่มช่องใหม่ |
| Master prompt อ้าง "image diagrams" | ไม่มีไฟล์ภาพแนบมา | ไม่ได้ตรวจ |

## 4. รายการ OPEN (ต้องปิดก่อนพิจารณาเงินจริง)

1. **Compile ใน MetaEditor** ยังไม่ได้ทำ โค้ด MQL5 ราว 2,200 บรรทัดเขียนโดยไม่มี compiler จึงควรคาดว่าจะมี error/warning ให้แก้
2. **`ClaudeEA_SelfTest`** ยังไม่เคยรันในเทอร์มินัล
3. **Strategy Tester** ด้วย replay จากข้อมูลจริงของโบรกเกอร์ ยังไม่ได้ทำ รวมการยืนยันว่า `TimeTradeServer`, GlobalVariables และ `TERMINAL_CONNECTED` ทำงานตามที่โค้ดสมมติใน tester
4. **เรียก Anthropic API จริง** ยังไม่เคยทำ: structured output, รหัสรุ่น, latency จริงเทียบกับ deadline 75/90 วินาที และค่าใช้จ่ายจริงต่อวัน (โหมดโหวตเรียก 3 เท่า)
5. **WebRequest ไป `127.0.0.1:8765`** ยังไม่ได้ยืนยันว่า build ของ MT5 ที่ใช้ยอมรับ port นี้
6. **ค่าของโบรกเกอร์** (สัญลักษณ์, tick, volume, stops/freeze level, offset เวลา, hedging/netting) ยังไม่ได้ยืนยัน
7. **Daily latch และ dedup หลัง EA/terminal restart** ทดสอบแล้วเฉพาะใน reference model
8. **Reverse mode, HOLD-close, quick profit, netting account** ใน MT5 จริง ยังไม่ได้ทดสอบ
9. **Out-of-sample / walk-forward / Monte Carlo บนข้อมูลจริง** และ **calibration ของ confidence** ยังไม่มี
10. **Demo forward test** ยังไม่ได้เริ่ม
11. Circuit breaker เก็บสถานะในหน่วยความจำ จะรีเซ็ตเมื่อ bridge restart
12. Backtest ของ Python ทำงานระดับแท่ง: trailing ขยับเฉพาะตอนปิดแท่ง ไม่ได้จำลอง tick, margin หรือ partial fill
13. ไม่ได้ใช้ server-side refusal fallback ของ API โดยตั้งใจ: refusal ให้ HOLD เพื่อให้เสียงโหวตมาจากรุ่นที่ตั้งค่าไว้เท่านั้น

## 5. ความเสี่ยงที่ยังไม่ครอบคลุม

- ไม่มีหลักฐานใดว่าสัญญาณจาก LLM บนแท่ง M5 20 แท่งมี edge หลังหักต้นทุน
- สัญญาณมาถึงช้ากว่าแท่งปิดหลายวินาทีถึงราว 90 วินาที ราคาเข้าอาจต่างจากที่โมเดลเห็น
- Daily stop เป็นเกณฑ์สั่งปิด ไม่ใช่การรับประกันผลลัพธ์: gap และ slippage ทำให้ขาดทุนจริงเกิน −100 ได้ และกำไรจริงต่ำกว่า +200 ได้
- Daily stop ไม่นับ position ที่เปิดด้วยมือหรือ EA อื่น
- ถ้า GlobalVariables ถูกลบ latch จะหาย (realized P/L ยังคำนวณใหม่จาก history ได้)
- ข้อมูลแท่งถูกส่งไปยัง Anthropic API ทุกครั้งที่ประเมิน
