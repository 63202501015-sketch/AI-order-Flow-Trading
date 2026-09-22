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

ทั้งสามส่วนถูกรวมไว้ใน `smc.analyze()` ซึ่งคืนค่า bias (ขาขึ้น/ขาลง) พร้อมโซนที่ยังไม่ถูก
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
  analyzer.py            # pipeline รวม + bias summary
  visualize.py             # plotting ด้วย mplfinance (optional)
examples/
  analyze_sample.py         # ตัวอย่างรันแบบ end-to-end บนข้อมูลจำลอง
tests/
  test_structure.py, test_order_blocks.py, test_liquidity.py
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
