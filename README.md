# AI Order Flow Trading

เครื่องมือ Python สำหรับวิเคราะห์โครงสร้างราคาตามแนวคิด **Smart Money Concepts (SMC)** —
หาจุดที่เจ้ามือ/สถาบัน (Smart Money) น่าจะเข้าสะสมหรือผลักดันราคา โดยอ่านจากข้อมูล OHLCV
โดยตรง ไม่ใช้ตัวชี้วัดสำเร็จรูป (indicator-free), ให้ผล reproducible และทดสอบได้

## เทคนิคที่รองรับ

1. **Order Block (OB)** — แท่งเทียนสวนทางแท่งสุดท้ายก่อนเกิดการเคลื่อนไหวรุนแรง
   (displacement) ที่ทำให้เกิดการเปลี่ยนโครงสร้าง (`smc/order_blocks.py`)
2. **Market Structure Shift** — ตรวจจับ **BOS (Break of Structure)** สำหรับการไปต่อของเทรนด์
   และ **CHoCH (Change of Character)** สำหรับสัญญาณกลับตัว โดยอิงจาก swing high/low แบบ fractal
   (`smc/structure.py`)
3. **Liquidity Pool** — หาโซน equal highs/equal lows (ที่สภาพคล่อง/stop-loss น่าจะกองอยู่)
   และโซนสะสมราคา (consolidation range) ก่อนการกระชากออกจากกรอบ (`smc/liquidity.py`)

4. **Single Candlestick Patterns (รูปแบบแท่งเทียนรายแท่ง)** — Hammer, Inverted Hammer,
   Shooting Star, Hanging Man, Marubozu และ Doji พร้อมบอกว่าเกิดที่แนวรับ/แนวต้านสำคัญหรือไม่
   และแผนเข้าออเดอร์ (`smc/candlestick.py`)

ทุกส่วนถูกรวมไว้ใน `smc.analyze()` ซึ่งคืนค่า bias (ขาขึ้น/ขาลง) พร้อมโซนที่ยังไม่ถูก
แตะ (unmitigated) ที่สอดคล้องกับเทรนด์ปัจจุบัน

> ⚠️ นี่คือเครื่องมือช่วยวิเคราะห์โครงสร้างราคาเชิงกฎเกณฑ์ ไม่ใช่คำแนะนำการลงทุน และไม่รับประกัน
> ผลกำไร ควรใช้ร่วมกับการบริหารความเสี่ยงของคุณเอง

## ติดตั้ง

```bash
pip install -r requirements.txt
# สำหรับรัน tests และ plotting เพิ่มเติม
pip install -r requirements-dev.txt
```

## ใช้งาน

```python
import pandas as pd
from smc import analyze

# df ต้องมีคอลัมน์ open, high, low, close (volume ไม่บังคับ)
# และ index เป็นเวลา เรียงจากเก่าไปใหม่
df = pd.read_csv("your_ohlcv.csv", index_col="time", parse_dates=True)

result = analyze(df)
print(result.summary())

for ob in result.active_order_blocks():
    print(ob.direction, ob.bottom, ob.top, ob.time)
```

รันตัวอย่างแบบสมบูรณ์ (สร้างข้อมูลจำลองเองเพื่อไม่ต้องพึ่งพาแหล่งข้อมูลภายนอก):

```bash
python examples/analyze_sample.py
```

### แท่งเทียนรายแท่ง (Single Candlestick Patterns)

```python
from smc import find_candle_patterns

for sig in find_candle_patterns(df, require_key_level=True):
    print(sig.describe())
# 2024-01-01 15:00:00: Hammer (ค้อน) ที่แนว 99.80 — Buy: สายซิ่งเข้าที่ open แท่งถัดไป (101.40),
#   สายชัวร์รอทะลุ High 101.50 | SL 99.90 [ยืนยันแล้ว]
```

| Pattern | รูปร่าง | ตำแหน่ง | ความหมาย |
|---|---|---|---|
| Hammer (ค้อน) | บอดี้เล็กด้านบน ไส้ล่าง ≥ 2 เท่าบอดี้ ไส้บนสั้น | แนวรับ / ปลายขาลง | กลับตัวขึ้น |
| Hanging Man (คนแขวนคอ) | เหมือน Hammer | แนวต้าน / ปลายขาขึ้น | กลับตัวลง |
| Shooting Star (ดาวตก) | บอดี้เล็กด้านล่าง ไส้บน ≥ 2 เท่าบอดี้ ไส้ล่างสั้น | แนวต้าน / ปลายขาขึ้น | กลับตัวลง |
| Inverted Hammer (ค้อนหงาย) | เหมือน Shooting Star | แนวรับ / ปลายขาลง | กลับตัวขึ้น |
| Marubozu (แท่งเต็มบอดี้) | บอดี้ ≥ 90% ของแท่ง แทบไม่มีไส้ | — | ไปต่อตามทิศแท่ง (continuation) |
| Doji (โดจิ) | บอดี้ ≤ 10% ของแท่ง | — | ลังเล รอแท่งถัดไปปิดนอกกรอบเพื่อเลือกทาง |

กติกาที่ใช้:

- **ตำแหน่งสำคัญที่สุด** — แนวรับ/แนวต้านคือ swing low/high ที่ *ยืนยันแล้วก่อน* แท่งแพทเทิร์น
  (ไม่มี lookahead) แท่งที่ไส้แตะแนวภายใน `level_tolerance_atr` × ATR แล้วปิดกลับเข้ามาได้จะนับว่า
  `at_key_level=True` ส่วนแพทเทิร์นที่เกิดลอย ๆ กลางทางจะยังถูกรายงานแต่ `tradeable=False`
  (ใช้ `require_key_level=True` เพื่อกรองทิ้ง) — Hammer กับ Hanging Man (และ Shooting Star กับ
  Inverted Hammer) แยกกันด้วยตำแหน่งนี้ หรือเทรนด์ก่อนหน้าถ้าไม่มีแนวใกล้ ๆ
- **ใช้แท่งที่ปิดแล้วเท่านั้น** — ทุกแถวใน `df` ถือเป็นแท่งที่ปิดสนิท อย่าส่งแท่งที่ยังวิ่งอยู่เข้าไป
- **Entry** — สายซิ่ง: `aggressive_entry` = open ของแท่งถัดไป; สายชัวร์: รอทะลุ `buy_trigger`
  (High ของแท่งแพทเทิร์น) หรือหลุด `sell_trigger` (Low) โดย `confirmed` บอกว่าแท่งถัดไปทะลุแล้วหรือยัง
- **Stop Loss** — ปลายไส้ของแท่งแพทเทิร์น (Low สำหรับฝั่ง Buy, High สำหรับฝั่ง Sell)

แนะนำใช้ไทม์เฟรม H1, H4 หรือ Day เพื่อลดสัญญาณหลอก

### พล็อตกราฟ (optional)

```python
from smc.visualize import plot

plot(df, result, save_path="chart.png")  # ต้องติดตั้ง mplfinance
```

## แนวคิดเบื้องหลังอัลกอริทึม

- **Swing point**: ใช้วิธี fractal — แท่งใดเป็น high/low สูงสุด/ต่ำสุดในหน้าต่าง
  `[i-left, i+right]` แบบ strict ถือเป็น swing point
- **BOS/CHoCH**: ไล่ตามลำดับเวลา เมื่อราคาปิดทะลุ swing high/low ล่าสุดที่ยังไม่ถูกทำลาย
  จะนับเป็น BOS ถ้าเป็นทิศทางเดียวกับเทรนด์เดิม หรือ CHoCH ถ้าสวนทาง (และเปลี่ยนเทรนด์)
- **Order Block**: ย้อนดูแท่งเทียนก่อนแท่งที่ทำให้เกิด BOS/CHoCH สูงสุด `lookback` แท่ง
  หาแท่งสีตรงข้ามล่าสุด และยืนยันว่ามีการเคลื่อนไหวที่รุนแรงพอ (>= `displacement_atr_mult`
  เท่าของ ATR) ก่อนนับเป็น OB ที่น่าเชื่อถือ
- **Liquidity pool**: จัดกลุ่ม swing high (หรือ low) ที่ราคาใกล้เคียงกันภายใน
  `tolerance_pct` เข้าด้วยกัน ถ้ามีจำนวนแตะ >= `min_touches` จะถือเป็น liquidity pool
- **Consolidation range**: หาช่วงที่ high-low range ของหน้าต่าง `window` แท่ง แคบกว่า
  `range_atr_mult` เท่าของ ATR เฉลี่ย

พารามิเตอร์ทั้งหมดปรับได้ผ่าน `analyze(df, swing_left=..., swing_right=..., ob_lookback=...,
displacement_atr_mult=..., equal_level_tolerance_pct=..., consolidation_window=...)`

## โครงสร้างโปรเจกต์

```
smc/
  structure.py      # swing points, BOS, CHoCH
  order_blocks.py    # order block detection + mitigation tracking
  liquidity.py         # equal highs/lows, consolidation ranges
  candlestick.py       # single-candlestick patterns + key-level context
  analyzer.py            # pipeline รวม + bias summary
  visualize.py             # plotting ด้วย mplfinance (optional)
examples/
  analyze_sample.py         # ตัวอย่างรันแบบ end-to-end บนข้อมูลจำลอง
tests/
  test_structure.py, test_order_blocks.py, test_liquidity.py, test_candlestick.py
```

## รันเทส

```bash
pip install -r requirements-dev.txt
pytest -q
```

## ที่มาของแนวคิด

สรุปมาจากเทคนิคการอ่านโครงสร้างราคาแบบ Smart Money Concepts / ICT ทั่วไป (Order Block,
Market Structure Shift, Liquidity) ที่ใช้กันแพร่หลายในการเทรด เช่น คู่เงิน XAUUSD — โค้ดในที่นี้
implement ขึ้นใหม่ทั้งหมดจากหลักการดังกล่าว ไม่ได้ดึงข้อมูลหรือโค้ดจากแหล่งภายนอกใด ๆ
