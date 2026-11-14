//+------------------------------------------------------------------+
//| ClaudeEA_SelfTest.mq5 - in-terminal unit tests of the pure        |
//| modules (JSON, sessions, risk, bridge response validation).       |
//| Run on any chart; result is printed in the Experts tab. The same  |
//| vectors are asserted in Python (tests/test_ref_*.py).             |
//+------------------------------------------------------------------+
#property script_show_inputs
#property version "1.00"

#include <ClaudeEA\Sessions.mqh>
#include <ClaudeEA\Risk.mqh>
#include <ClaudeEA\Bridge.mqh>

int g_pass = 0;
int g_fail = 0;

void Check(const bool cond, const string name)
  {
   if(cond)
      g_pass++;
   else
     {
      g_fail++;
      Print("FAIL: ", name);
     }
  }
bool Near(const double a, const double b) { return MathAbs(a - b) < 1e-6; }
datetime T(const int y, const int mo, const int d, const int h, const int mi = 0)
  {
   return CaiMakeTime(y, mo, d, h) + mi * 60;
  }
//+------------------------------------------------------------------+
void TestJson()
  {
   CFlatJson j;
   string s;
   double v;
   Check(j.Parse("{\"signal\":\"BUY\",\"confidence\":72.5,\"reason\":\"a \\\"b\\\"\"}"), "json valid");
   Check(j.GetString("signal", s) && s == "BUY", "json string");
   Check(j.GetNumber("confidence", v) && Near(v, 72.5), "json number");
   Check(j.Count() == 3, "json count");
   Check(!j.GetNumber("signal", v), "json type mismatch");
   Check(j.Parse(" { } "), "json empty object");
   Check(j.Parse("{\"a\":-1.5e2,\"b\":true,\"c\":null}") && j.GetNumber("a", v) && Near(v, -150.0), "json exp");
   Check(!j.Parse(""), "json empty");
   Check(!j.Parse("BUY"), "json bare word");
   Check(!j.Parse("[1,2]"), "json array");
   Check(!j.Parse("{\"a\":{\"b\":1}}"), "json nested object");
   Check(!j.Parse("{\"a\":[1]}"), "json nested array");
   Check(!j.Parse("{\"a\":1,\"a\":2}"), "json duplicate key");
   Check(!j.Parse("{\"a\":1} x"), "json trailing");
   Check(!j.Parse("{\"a\":1,}"), "json trailing comma");
   Check(!j.Parse("{\"a\":01}"), "json leading zero");
   Check(!j.Parse("{\"a\":1.}"), "json bad fraction");
   Check(!j.Parse("{\"a\":NaN}"), "json NaN");
   Check(!j.Parse("{\"a\":\"x}"), "json unterminated");
   Check(!j.Parse("{a:1}"), "json unquoted key");
   Check(!j.Parse("```json {\"a\":1} ```"), "json markdown");
  }
//+------------------------------------------------------------------+
void TestBridgeResponse()
  {
   CaiSignal sig;
   string rid = "XAUUSD-M5-1793600000-770001";
   datetime bar = (datetime)1793600000;
   string ok = "{\"request_id\":\"" + rid + "\",\"status\":\"final\",\"signal\":\"BUY\",\"confidence\":72.0,"
               "\"reason\":\"x\",\"bar_time\":1793600000,\"source\":\"single\"}";
   Check(CaiParseResponse(200, ok, rid, bar, sig) == CAI_BRIDGE_FINAL && sig.side == CAI_SIG_BUY &&
         Near(sig.confidence, 72.0), "resp final buy");
   Check(CaiParseResponse(500, ok, rid, bar, sig) == CAI_BRIDGE_ERROR && sig.side == CAI_SIG_HOLD, "resp http 500");
   Check(CaiParseResponse(401, ok, rid, bar, sig) == CAI_BRIDGE_ERROR && sig.side == CAI_SIG_HOLD, "resp http 401");
   Check(CaiParseResponse(-1, "", rid, bar, sig) == CAI_BRIDGE_ERROR && sig.side == CAI_SIG_HOLD, "resp transport");
   Check(CaiParseResponse(200, "<html>", rid, bar, sig) == CAI_BRIDGE_ERROR && sig.side == CAI_SIG_HOLD, "resp html");
   Check(CaiParseResponse(200, ok, "other-request-id", bar, sig) == CAI_BRIDGE_ERROR && sig.side == CAI_SIG_HOLD,
         "resp wrong request id");
   Check(CaiParseResponse(200, ok, rid, bar + 300, sig) == CAI_BRIDGE_ERROR && sig.side == CAI_SIG_HOLD,
         "resp wrong bar");
   string pending = ok;
   StringReplace(pending, "\"final\"", "\"pending\"");
   Check(CaiParseResponse(202, pending, rid, bar, sig) == CAI_BRIDGE_PENDING && sig.side == CAI_SIG_HOLD, "resp pending");
   string bad = ok;
   StringReplace(bad, "\"BUY\"", "\"CLOSE_ALL\"");
   Check(CaiParseResponse(200, bad, rid, bar, sig) == CAI_BRIDGE_ERROR && sig.side == CAI_SIG_HOLD, "resp unknown signal");
   bad = ok;
   StringReplace(bad, "72.0", "172.0");
   Check(CaiParseResponse(200, bad, rid, bar, sig) == CAI_BRIDGE_ERROR && sig.side == CAI_SIG_HOLD, "resp confidence range");
   bad = ok;
   StringReplace(bad, ",\"source\":\"single\"", ",\"source\":\"single\",\"lot\":5");
   Check(CaiParseResponse(200, bad, rid, bar, sig) == CAI_BRIDGE_ERROR && sig.side == CAI_SIG_HOLD, "resp extra field");
   Check(CaiSymbolCharsOk("XAUUSD.m") && !CaiSymbolCharsOk("XAU USD") && !CaiSymbolCharsOk("A\"B"), "symbol chars");
   Check(CaiBridgeUrlIsLocal("http://127.0.0.1:8765") && !CaiBridgeUrlIsLocal("http://10.0.0.5:8765") &&
         !CaiBridgeUrlIsLocal("https://example.com"), "bridge url local only");
  }
//+------------------------------------------------------------------+
void TestSessions()
  {
   Check(!CaiEuDst(T(2026, 3, 29, 0, 59)) && CaiEuDst(T(2026, 3, 29, 1, 0)), "EU DST start 2026");
   Check(CaiEuDst(T(2026, 10, 25, 0, 59)) && !CaiEuDst(T(2026, 10, 25, 1, 0)), "EU DST end 2026");
   Check(!CaiUsDst(T(2026, 3, 8, 6, 59)) && CaiUsDst(T(2026, 3, 8, 7, 0)), "US DST start 2026");
   Check(CaiUsDst(T(2026, 11, 1, 5, 59)) && !CaiUsDst(T(2026, 11, 1, 6, 0)), "US DST end 2026");
   string n;
   Check(!CaiSessionAllowed(T(2026, 1, 14, 7, 30), true, 800, 1700, false, 800, 1700, false, 900, 1500, n), "London winter closed 07:30Z");
   Check(CaiSessionAllowed(T(2026, 1, 14, 8, 0), true, 800, 1700, false, 800, 1700, false, 900, 1500, n) && n == "LONDON", "London winter open 08:00Z");
   Check(CaiSessionAllowed(T(2026, 7, 15, 7, 0), true, 800, 1700, false, 800, 1700, false, 900, 1500, n), "London summer open 07:00Z");
   Check(!CaiSessionAllowed(T(2026, 7, 15, 16, 0), true, 800, 1700, false, 800, 1700, false, 900, 1500, n), "London summer closed 16:00Z");
   Check(!CaiSessionAllowed(T(2026, 3, 16, 11, 59), false, 800, 1700, true, 800, 1700, false, 900, 1500, n), "NY gap week closed 11:59Z");
   Check(CaiSessionAllowed(T(2026, 3, 16, 12, 0), false, 800, 1700, true, 800, 1700, false, 900, 1500, n) && n == "NEW_YORK", "NY gap week open 12:00Z");
   Check(!CaiSessionAllowed(T(2026, 7, 15, 2, 0), true, 800, 1700, true, 800, 1700, false, 900, 1500, n), "Asia blocked by default");
   Check(CaiSessionAllowed(T(2026, 7, 15, 2, 0), true, 800, 1700, true, 800, 1700, true, 900, 1500, n) && n == "ASIA", "Asia optional");
   Check(!CaiSessionAllowed(T(2026, 7, 18, 12, 0), true, 800, 1700, true, 800, 1700, true, 900, 1500, n), "Saturday closed");
   Check(CaiServerToUtcManual(T(2026, 1, 14, 12), 2, CAI_DST_US) == T(2026, 1, 14, 10), "server->utc winter");
   Check(CaiServerToUtcManual(T(2026, 7, 15, 12), 2, CAI_DST_US) == T(2026, 7, 15, 9), "server->utc summer");
   Check(CaiServerToUtcManual(T(2026, 3, 16, 12), 2, CAI_DST_EU) == T(2026, 3, 16, 10), "server->utc EU rule gap week");
  }
//+------------------------------------------------------------------+
void TestRisk()
  {
   Check(Near(CaiNormalizeVolume(0.017, 0.01, 100, 0.01), 0.01), "vol floor");
   Check(Near(CaiNormalizeVolume(0.009, 0.01, 100, 0.01), 0.0), "vol below min -> 0");
   Check(Near(CaiNormalizeVolume(250, 0.01, 100, 0.01), 100.0), "vol cap");
   Check(Near(CaiNormalizeVolume(1.239, 0.01, 100, 0.01), 1.23), "vol never rounds up");
   Check(Near(CaiRoundToTick(2650.127, 0.05, CAI_ROUND_DOWN), 2650.10), "tick down");
   Check(Near(CaiRoundToTick(2650.127, 0.05, CAI_ROUND_UP), 2650.15), "tick up");
   double sl, tp;
   CaiInitialStops(true, 2650.0, 2.0, 0.01, 1.0, 3.0, sl, tp);
   Check(Near(sl, 2648.0) && Near(tp, 2656.0), "buy SL 1 ATR / TP 3 ATR");
   CaiInitialStops(false, 2650.0, 2.0, 0.01, 1.0, 3.0, sl, tp);
   Check(Near(sl, 2652.0) && Near(tp, 2644.0), "sell SL 1 ATR / TP 3 ATR");
   Check(CaiStopsValid(true, 2650.0, 2650.3, 2648.0, 2656.0, 0.5), "stops valid buy");
   Check(!CaiStopsValid(true, 2650.0, 2650.3, 2649.8, 2656.0, 0.5), "stops too close buy");
   Check(!CaiStopsValid(false, 2650.0, 2650.3, 2650.5, 2644.0, 0.5), "stops too close sell");
   // break-even / trailing: same vectors as tests/test_ref_risk.py
   Check(CaiTrailSL(true, 2650, 2648, 2651.99, 2, 0.01, 1, 1.5, 1, 0, 0, 0) == 0.0, "buy < 1 ATR no move");
   Check(Near(CaiTrailSL(true, 2650, 2648, 2652.00, 2, 0.01, 1, 1.5, 1, 0, 0, 0), 2650.00), "buy BE at +1 ATR");
   Check(CaiTrailSL(true, 2650, 2650, 2652.90, 2, 0.01, 1, 1.5, 1, 0, 0, 0) == 0.0, "buy at BE no move");
   Check(Near(CaiTrailSL(true, 2650, 2650, 2653.00, 2, 0.01, 1, 1.5, 1, 0, 0, 0), 2651.00), "buy trail at +1.5 ATR");
   Check(Near(CaiTrailSL(false, 2650, 2652, 2648.00, 2, 0.01, 1, 1.5, 1, 0, 0, 0), 2650.00), "sell BE");
   Check(Near(CaiTrailSL(false, 2650, 2650, 2647.00, 2, 0.01, 1, 1.5, 1, 0, 0, 0), 2649.00), "sell trail");
   Check(Near(CaiTrailSL(true, 2650, 2648, 2652, 2, 0.05, 1, 1.5, 1, 4, 0, 0), 2650.20), "BE buffer ticks");
   Check(Near(CaiTrailSL(true, 2650, 2648, 2652, 2, 0.01, 1, 1.5, 1, 0, 2.5, 0), 2649.50), "stop level clamp");
   Check(CaiTrailSL(true, 2650, 2649.6, 2652, 2, 0.01, 1, 1.5, 1, 0, 2.5, 0) == 0.0, "clamp does not improve");
   Check(CaiTrailSL(true, 2650, 2651.8, 2652, 0.1, 0.01, 1, 1.5, 1, 0, 0, 0.5) == 0.0, "freeze level");
   // monotonic on a pseudo-random path
   MathSrand(11);
   bool mono = true;
   for(int run = 0; run < 200 && mono; run++)
     {
      double entry = 2650.0;
      double atr = 0.5 + (MathRand() % 350) / 100.0;
      double curSl = entry - atr;
      double price = entry;
      for(int k = 0; k < 300; k++)
        {
         price += ((MathRand() % 200) - 98) / 100.0;
         double ns = CaiTrailSL(true, entry, curSl, price, atr, 0.01, 1, 1.5, 1, 0, 0, 0);
         if(ns == 0.0)
            continue;
         if(ns < curSl + 0.01 - 1e-9 || ns > price + 1e-9)
           { mono = false; break; }
         curSl = ns;
        }
     }
   Check(mono, "buy SL monotonic on random path");
   Check(CaiDailyBreach(150, 49.99, 200, 100) == 0 && CaiDailyBreach(150, 50, 200, 100) == 1 &&
         CaiDailyBreach(-60, -40, 200, 100) == 2, "daily breach");
   Check(CaiDayId(T(2026, 11, 13, 23, 59)) == 20261113, "day id");
  }
//+------------------------------------------------------------------+
void OnStart()
  {
   TestJson();
   TestBridgeResponse();
   TestSessions();
   TestRisk();
   PrintFormat("ClaudeEA SELFTEST %s: %d passed, %d failed", g_fail == 0 ? "PASSED" : "FAILED", g_pass, g_fail);
  }
//+------------------------------------------------------------------+
