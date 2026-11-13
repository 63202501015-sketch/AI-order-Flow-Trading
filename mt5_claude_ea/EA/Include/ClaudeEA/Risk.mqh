//+------------------------------------------------------------------+
//| Risk.mqh - pure, broker-aware calculations (no trading calls).    |
//| Mirrors refmodel/risk.py function-for-function.                   |
//+------------------------------------------------------------------+
#ifndef CLAUDEEA_RISK_MQH
#define CLAUDEEA_RISK_MQH

#define CAI_EPS 1e-9
#define CAI_ROUND_NEAREST 0
#define CAI_ROUND_DOWN    1
#define CAI_ROUND_UP      2

//+------------------------------------------------------------------+
double CaiRoundToTick(const double price, const double tick, const int mode = CAI_ROUND_NEAREST)
  {
   if(tick <= 0.0)
      return price;
   double q = price / tick;
   double n;
   if(mode == CAI_ROUND_DOWN)
      n = MathFloor(q + CAI_EPS);
   else if(mode == CAI_ROUND_UP)
      n = MathCeil(q - CAI_EPS);
   else
      n = MathFloor(q + 0.5);
   return NormalizeDouble(n * tick, 8);
  }
//+------------------------------------------------------------------+
//| Floor to step, cap at max. Below broker minimum -> 0.             |
//| Risk is never rounded UP.                                         |
//+------------------------------------------------------------------+
double CaiNormalizeVolume(const double vol, const double vmin, const double vmax, const double step)
  {
   if(!(vol > 0.0) || !(step > 0.0) || !(vmin > 0.0) || vmax < vmin)
      return 0.0;
   double v = MathFloor(vol / step + CAI_EPS) * step;
   double cap = MathFloor(vmax / step + CAI_EPS) * step;
   if(v > cap)
      v = cap;
   if(v + CAI_EPS < vmin)
      return 0.0;
   return NormalizeDouble(v, 8);
  }
//+------------------------------------------------------------------+
//| isBuy: SL = entry - slMult*ATR, TP = entry + tpMult*ATR           |
//+------------------------------------------------------------------+
void CaiInitialStops(const bool isBuy, const double entry, const double atr, const double tick,
                     const double slMult, const double tpMult, double &sl, double &tp)
  {
   if(isBuy)
     {
      sl = CaiRoundToTick(entry - slMult * atr, tick);
      tp = CaiRoundToTick(entry + tpMult * atr, tick);
     }
   else
     {
      sl = CaiRoundToTick(entry + slMult * atr, tick);
      tp = CaiRoundToTick(entry - tpMult * atr, tick);
     }
  }
//+------------------------------------------------------------------+
//| Broker StopLevel rule for market orders. minDist is a PRICE       |
//| distance (stops level in points * point).                         |
//+------------------------------------------------------------------+
bool CaiStopsValid(const bool isBuy, const double bid, const double ask,
                   const double sl, const double tp, const double minDist)
  {
   if(sl <= 0.0 || tp <= 0.0)
      return false;
   if(isBuy)
      return (bid - sl >= minDist - CAI_EPS && tp - bid >= minDist - CAI_EPS);
   return (sl - ask >= minDist - CAI_EPS && ask - tp >= minDist - CAI_EPS);
  }
//+------------------------------------------------------------------+
//| Break-even + trailing. Returns the new SL, or 0.0 for "no change".|
//| price = Bid for BUY, Ask for SELL.                                |
//|  gain >= beTrigger*ATR   -> SL to entry (+ buffer ticks, default 0)|
//|  gain >= trailStart*ATR  -> SL follows price at trailDist*ATR     |
//| BUY SL never decreases, SELL SL never increases.                  |
//+------------------------------------------------------------------+
double CaiTrailSL(const bool isBuy, const double entry, const double curSl, const double price,
                  const double atr, const double tick,
                  const double beTrigger, const double trailStart, const double trailDist,
                  const int beBufferTicks, const double minDist, const double freezeDist)
  {
   if(atr <= 0.0 || tick <= 0.0)
      return 0.0;
   double sign = isBuy ? 1.0 : -1.0;
   double gain = (price - entry) * sign;
   bool   have = false;
   double cand = 0.0;
   if(gain >= beTrigger * atr - CAI_EPS)
     {
      cand = entry + sign * beBufferTicks * tick;
      have = true;
     }
   if(gain >= trailStart * atr - CAI_EPS)
     {
      double t = price - sign * trailDist * atr;
      if(!have)
         cand = t;
      else
         cand = isBuy ? MathMax(cand, t) : MathMin(cand, t);
      have = true;
     }
   if(!have)
      return 0.0;
   if(curSl > 0.0 && freezeDist > 0.0 && MathAbs(price - curSl) <= freezeDist + CAI_EPS)
      return 0.0;                              // inside freeze level: broker would reject
   double limit = price - sign * minDist;      // closest SL the broker accepts
   if(isBuy)
     {
      cand = CaiRoundToTick(MathMin(cand, limit), tick, CAI_ROUND_DOWN);
      if(curSl <= 0.0 || cand >= curSl + tick - CAI_EPS)
         return cand;
      return 0.0;
     }
   cand = CaiRoundToTick(MathMax(cand, limit), tick, CAI_ROUND_UP);
   if(curSl <= 0.0 || cand <= curSl - tick + CAI_EPS)
      return cand;
   return 0.0;
  }
//+------------------------------------------------------------------+
//| Daily latch decision. Returns 0 none, 1 profit target, 2 loss.    |
//+------------------------------------------------------------------+
int CaiDailyBreach(const double realized, const double floating,
                   const double profitTarget, const double lossLimit)
  {
   double total = realized + floating;
   if(profitTarget > 0.0 && total >= profitTarget - CAI_EPS)
      return 1;
   if(lossLimit > 0.0 && total <= -lossLimit + CAI_EPS)
      return 2;
   return 0;
  }
//+------------------------------------------------------------------+
int CaiDayId(const datetime serverTime)        // broker day as yyyymmdd
  {
   MqlDateTime s;
   TimeToStruct(serverTime, s);
   return s.year * 10000 + s.mon * 100 + s.day;
  }

#endif // CLAUDEEA_RISK_MQH
