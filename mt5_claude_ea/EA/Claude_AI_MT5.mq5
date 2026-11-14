//+------------------------------------------------------------------+
//|                                                Claude_AI_MT5.mq5 |
//| AI-assisted EA: a local Python bridge returns BUY/SELL/HOLD for   |
//| each closed M5 bar; THIS file decides whether anything is traded. |
//|                                                                   |
//| Safety model                                                      |
//|  - InpAllowOrders=false by default: signals are logged, no orders.|
//|  - Every bridge/HTTP/schema failure is HOLD (fail closed).        |
//|  - Protective management (BE, trailing, daily stop, quick profit) |
//|    runs on every tick and never depends on the bridge or the AI.  |
//|  - The AI output is three fields. It cannot set lot size, stops,  |
//|    limits or any other parameter, and its text is never executed. |
//|  - Only positions with this magic number on this symbol are ever  |
//|    modified or closed.                                            |
//|                                                                   |
//| NOT validated for real-money trading. See docs/TEST_REPORT.md.    |
//+------------------------------------------------------------------+
#property copyright "Research / demo use. No profitability claim."
#property version   "1.00"
#property description "Claude AI signal EA (M5). Orders are OFF by default. Demo/tester only until accepted."

#include <ClaudeEA\Sessions.mqh>
#include <ClaudeEA\Risk.mqh>
#include <ClaudeEA\Audit.mqh>
#include <ClaudeEA\Bridge.mqh>
#include <ClaudeEA\Replay.mqh>
#include <ClaudeEA\Execution.mqh>

enum ENUM_CAI_SIGNAL_SOURCE
  {
   CAI_SRC_AUTO   = 0,   // AUTO: bridge when live, replay file in the tester
   CAI_SRC_BRIDGE = 1,   // Local bridge (live/demo only)
   CAI_SRC_REPLAY = 2    // Replay CSV (Strategy Tester only)
  };

enum ENUM_CAI_LOT_MODE
  {
   CAI_LOT_FIXED      = 0,   // Fixed lot
   CAI_LOT_RISK_MONEY = 1    // Fixed money risk per trade (account currency)
  };

input group "=== Safety ==="
input bool   InpAllowOrders        = false;      // Allow the EA to send orders (opt-in)
input long   InpMagic              = 770001;     // Magic number (position ownership)
input string InpSymbolAllowlist    = "XAUUSD,XAUUSD.sc"; // Exact broker symbols allowed, comma separated

input group "=== Signal source ==="
input ENUM_CAI_SIGNAL_SOURCE InpSignalSource = CAI_SRC_AUTO;
input string InpBridgeUrl          = "http://127.0.0.1:8765";     // Loopback only; add to WebRequest list
input string InpBridgeTokenFile    = "claude_bridge_token.txt";   // In MQL5/Files (not the Anthropic key)
input int    InpHttpTimeoutMs      = 1500;       // Per HTTP call (bridge is local)
input int    InpSignalDeadlineSec  = 90;         // Give up (HOLD) if no final answer by then
input int    InpMaxSignalAgeSec    = 120;        // Stale-signal guard, seconds after bar close
input int    InpEvalIntervalSec    = 300;        // Minimum seconds between evaluated bars
input double InpMinConfidence      = 60.0;       // Uncalibrated model self-report, not a probability
input bool   InpSkipAiWhenBlocked  = true;       // Do not ask (or pay for) the AI when no action is possible
input string InpReplayFile         = "claude_replay_signals.csv"; // Terminal Common\Files (tester)

input group "=== Sessions (local exchange time, DST-aware) ==="
input bool   InpUseLondon          = true;
input int    InpLondonStartHHMM    = 800;        // Europe/London
input int    InpLondonEndHHMM      = 1700;
input bool   InpUseNewYork         = true;
input int    InpNewYorkStartHHMM   = 800;        // America/New_York
input int    InpNewYorkEndHHMM     = 1700;
input bool   InpUseAsia            = false;      // Asia blocked by default
input int    InpAsiaStartHHMM      = 900;        // Asia/Tokyo
input int    InpAsiaEndHHMM        = 1500;
input ENUM_CAI_SERVER_TIME_MODE InpServerTimeMode = CAI_SERVER_TIME_AUTO;
input int    InpServerStdOffsetHours = 2;        // MANUAL: broker winter offset from UTC
input ENUM_CAI_DST_RULE InpServerDstRule = CAI_DST_US;            // MANUAL: broker DST calendar

input group "=== Entry risk ==="
input ENUM_CAI_LOT_MODE InpLotMode = CAI_LOT_FIXED;
input double InpFixedLot           = 0.01;
input double InpRiskMoney          = 25.0;       // Used when lot mode = risk money
input double InpMaxSpreadPoints    = 35.0;
input int    InpMaxSlippagePoints  = 20;         // Max order deviation
input int    InpCooldownSec        = 900;
input int    InpMaxTradesPerDay    = 6;
input double InpMaxMarginUsePct    = 50.0;       // Order margin must be <= this % of free margin

input group "=== Stops (ATR multiples) ==="
input int    InpAtrPeriod          = 14;
input double InpSlAtr              = 1.0;
input double InpTpAtr              = 3.0;
input double InpBeTriggerAtr       = 1.0;        // Move SL to entry at +N ATR
input double InpTrailStartAtr      = 1.5;        // Start trailing at +N ATR
input double InpTrailDistAtr       = 1.0;        // Trailing distance
input int    InpBeBufferTicks      = 0;          // Optional BE offset in ticks (0 = exact entry)

input group "=== Account-currency stops ==="
input bool   InpDailyStops         = true;
input double InpDailyProfit        = 200.0;      // Latch when realized+floating >= this
input double InpDailyLoss          = 100.0;      // Latch when realized+floating <= -this
input bool   InpQuickProfit        = false;      // Optional
input double InpQuickProfitMoney   = 9.0;        // Close managed positions at this floating P/L

input group "=== Optional behaviour (OFF by default) ==="
input bool   InpReverseMode        = false;      // Opposite signal: close, verify, re-check, reverse
input bool   InpCloseOnHold        = false;      // HOLD closes the managed position
input bool   InpAuditLog           = true;

//--- state
#define ST_IDLE   0
#define ST_SUBMIT 1
#define ST_POLL   2

int      g_atrHandle      = INVALID_HANDLE;
bool     g_useReplay      = false;
bool     g_signalsEnabled = false;
bool     g_symbolOk       = false;
datetime g_lastEvalBar    = 0;

int      g_state          = ST_IDLE;
datetime g_reqBar         = 0;
string   g_reqId          = "";
string   g_reqBody        = "";
datetime g_reqDeadline    = 0;
int      g_reqSubmitTries = 0;
int      g_reqPollErrors  = 0;
ulong    g_reqStartMs     = 0;

bool     g_dailyOk        = false;   // false => P/L unknown => entries blocked
bool     g_dailyDirty     = true;
datetime g_dailyCalcAt    = 0;
double   g_realized       = 0.0;
double   g_floating       = 0.0;
int      g_tradesToday    = 0;
bool     g_latched        = false;
datetime g_lastCloseTry   = 0;
datetime g_lastModifyFail = 0;

//+------------------------------------------------------------------+
datetime ServerNow()
  {
   datetime t = TimeTradeServer();
   datetime c = TimeCurrent();
   return (t > c) ? t : c;
  }
//+------------------------------------------------------------------+
bool UtcNow(datetime &utc, int &offsetSec)
  {
   datetime now = ServerNow();
   if(!CaiServerUtcOffset(InpServerTimeMode, InpServerStdOffsetHours, InpServerDstRule, now, offsetSec))
     {
      utc = now;
      return false;
     }
   utc = now - offsetSec;
   return true;
  }
//+------------------------------------------------------------------+
double SpreadPoints()
  {
   MqlTick tick;
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   if(!SymbolInfoTick(_Symbol, tick) || point <= 0.0)
      return 1e9;                                            // unknown spread blocks entries
   return (tick.ask - tick.bid) / point;
  }
//+------------------------------------------------------------------+
void AuditEvent(const string event, const datetime barTime, const string requestId, const string signal,
         const double confidence, const string decision, const string reason,
         const double volume = 0.0, const double sl = 0.0, const double tp = 0.0,
         const ulong ticket = 0, const uint retcode = 0, const long latencyMs = 0)
  {
   datetime utc;
   int off;
   UtcNow(utc, off);
   CaiAudit(utc, event, _Symbol, barTime, requestId, signal, confidence, decision, reason,
            AccountInfoDouble(ACCOUNT_EQUITY), g_realized + g_floating, SpreadPoints(),
            volume, sl, tp, ticket, retcode, latencyMs);
  }
//+------------------------------------------------------------------+
bool SymbolInAllowlist()
  {
   string parts[];
   int n = StringSplit(InpSymbolAllowlist, ',', parts);
   for(int i = 0; i < n; i++)
     {
      string s = parts[i];
      StringTrimLeft(s);
      StringTrimRight(s);
      if(s != "" && s == _Symbol)
         return true;
     }
   return false;
  }
//+------------------------------------------------------------------+
bool InputsValid(string &why)
  {
   why = "";
   if(InpMagic <= 0)                                           why = "InpMagic must be > 0";
   else if(InpAtrPeriod < 2)                                   why = "InpAtrPeriod must be >= 2";
   else if(InpSlAtr <= 0.0 || InpTpAtr <= 0.0)                 why = "SL/TP ATR multiples must be > 0";
   else if(InpBeTriggerAtr <= 0.0 || InpTrailStartAtr < InpBeTriggerAtr || InpTrailDistAtr <= 0.0)
                                                               why = "BE/trailing ATR settings inconsistent";
   else if(InpBeBufferTicks < 0)                               why = "InpBeBufferTicks must be >= 0";
   else if(InpFixedLot <= 0.0 && InpLotMode == CAI_LOT_FIXED)  why = "InpFixedLot must be > 0";
   else if(InpRiskMoney <= 0.0 && InpLotMode == CAI_LOT_RISK_MONEY) why = "InpRiskMoney must be > 0";
   else if(InpMaxSpreadPoints <= 0.0)                          why = "InpMaxSpreadPoints must be > 0";
   else if(InpMaxSlippagePoints < 0)                           why = "InpMaxSlippagePoints must be >= 0";
   else if(InpMaxTradesPerDay < 1 || InpCooldownSec < 0)       why = "daily cap / cooldown invalid";
   else if(InpMaxMarginUsePct <= 0.0 || InpMaxMarginUsePct > 100.0) why = "InpMaxMarginUsePct must be in (0,100]";
   else if(InpMinConfidence < 0.0 || InpMinConfidence > 100.0) why = "InpMinConfidence must be 0..100";
   else if(InpHttpTimeoutMs < 100 || InpHttpTimeoutMs > 5000)  why = "InpHttpTimeoutMs must be 100..5000";
   else if(InpSignalDeadlineSec < 5 || InpSignalDeadlineSec > 280) why = "InpSignalDeadlineSec must be 5..280";
   else if(InpMaxSignalAgeSec < 1 || InpMaxSignalAgeSec > 295) why = "InpMaxSignalAgeSec must be 1..295";
   else if(InpEvalIntervalSec < 300)                           why = "InpEvalIntervalSec must be >= 300";
   else if(InpDailyStops && (InpDailyProfit < 0.0 || InpDailyLoss < 0.0)) why = "daily stop amounts must be >= 0";
   else if(InpQuickProfit && InpQuickProfitMoney <= 0.0)       why = "InpQuickProfitMoney must be > 0";
   else if(!CaiHhmmValid(InpLondonStartHHMM) || !CaiHhmmValid(InpLondonEndHHMM) ||
           !CaiHhmmValid(InpNewYorkStartHHMM) || !CaiHhmmValid(InpNewYorkEndHHMM) ||
           !CaiHhmmValid(InpAsiaStartHHMM) || !CaiHhmmValid(InpAsiaEndHHMM))
                                                               why = "session times must be HHMM";
   else if(InpServerStdOffsetHours < -12 || InpServerStdOffsetHours > 14) why = "InpServerStdOffsetHours invalid";
   return (why == "");
  }
//+------------------------------------------------------------------+
//| Remove per-position ATR records of positions that no longer exist.|
//+------------------------------------------------------------------+
void CleanupAtrRecords()
  {
   string prefix = CaiGvName("ATR_");
   ulong tickets[];
   CaiManagedTickets(tickets);
   for(int i = GlobalVariablesTotal() - 1; i >= 0; i--)
     {
      string name = GlobalVariableName(i);
      if(StringFind(name, prefix) != 0)
         continue;
      ulong ticket = (ulong)StringToInteger(StringSubstr(name, StringLen(prefix)));
      bool alive = false;
      for(int k = 0; k < ArraySize(tickets); k++)
         if(tickets[k] == ticket)
            alive = true;
      if(!alive)
         GlobalVariableDel(name);
     }
  }
//+------------------------------------------------------------------+
int OnInit()
  {
   string why;
   if(!InputsValid(why))
     {
      Alert("ClaudeEA: invalid inputs: ", why);
      return INIT_PARAMETERS_INCORRECT;
     }
   g_symbolOk = (CaiSymbolCharsOk(_Symbol) && SymbolInAllowlist());
   if(!g_symbolOk)
     {
      Alert("ClaudeEA: symbol ", _Symbol, " is not in InpSymbolAllowlist");
      return INIT_PARAMETERS_INCORRECT;
     }
   bool tester = (bool)MQLInfoInteger(MQL_TESTER);
   if(InpSignalSource == CAI_SRC_BRIDGE && tester)
     {
      Alert("ClaudeEA: the bridge (WebRequest) is not available in the Strategy Tester; use the replay file");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpSignalSource == CAI_SRC_REPLAY && !tester)
     {
      Alert("ClaudeEA: replay signals are for the Strategy Tester only");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(tester && InpServerTimeMode == CAI_SERVER_TIME_AUTO)
     {
      Alert("ClaudeEA: set InpServerTimeMode=MANUAL in the tester (UTC cannot be detected there)");
      return INIT_PARAMETERS_INCORRECT;
     }
   g_useReplay = tester;

   CaiExecInit(_Symbol, InpMagic, InpMaxSlippagePoints);
   CaiAuditInit(InpAuditLog, _Symbol, InpMagic);

   g_atrHandle = iATR(_Symbol, PERIOD_M5, InpAtrPeriod);
   if(g_atrHandle == INVALID_HANDLE)
     {
      Alert("ClaudeEA: cannot create ATR handle");
      return INIT_FAILED;
     }

   g_signalsEnabled = false;
   if(g_useReplay)
     {
      g_signalsEnabled = CaiReplayLoad(InpReplayFile);
      if(!g_signalsEnabled)
         Print("ClaudeEA: replay file missing or malformed -> all signals HOLD: ", InpReplayFile);
      else
         PrintFormat("ClaudeEA: replay signals loaded: %d rows", g_caiReplayCount);
     }
   else
     {
      if(!CaiBridgeUrlIsLocal(InpBridgeUrl))
         Alert("ClaudeEA: InpBridgeUrl must be http://127.0.0.1:<port> -> signals disabled (protection still active)");
      else if(!CaiBridgeLoadToken(InpBridgeTokenFile))
         Alert("ClaudeEA: bridge token file missing/invalid (MQL5\\Files\\", InpBridgeTokenFile,
               ") -> signals disabled (protection still active)");
      else
         g_signalsEnabled = true;
     }

   double v = 0.0;
   if(CaiGvGet("LASTEVALBAR", v))
      g_lastEvalBar = (datetime)(long)v;
   CleanupAtrRecords();
   g_dailyDirty = true;
   g_state = ST_IDLE;

   if(!EventSetTimer(1))
     {
      Alert("ClaudeEA: cannot start timer");
      return INIT_FAILED;
     }
   PrintFormat("ClaudeEA init: symbol=%s magic=%I64d orders=%s source=%s signals=%s reverse=%s holdClose=%s quickProfit=%s netting=%s",
               _Symbol, InpMagic, InpAllowOrders ? "ON" : "OFF", g_useReplay ? "replay" : "bridge",
               g_signalsEnabled ? "enabled" : "DISABLED", InpReverseMode ? "ON" : "OFF",
               InpCloseOnHold ? "ON" : "OFF", InpQuickProfit ? "ON" : "OFF", CaiIsNetting() ? "yes" : "no");
   AuditEvent("INIT", 0, "", "HOLD", 0.0, InpAllowOrders ? "ORDERS_ON" : "ORDERS_OFF",
       g_signalsEnabled ? "signals enabled" : "signals disabled");
   return INIT_SUCCEEDED;
  }
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   EventKillTimer();
   if(g_atrHandle != INVALID_HANDLE)
      IndicatorRelease(g_atrHandle);
   // Open positions keep their server-side SL/TP. Nothing is closed on deinit.
  }
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   g_dailyDirty = true;
  }
//+------------------------------------------------------------------+
//| Daily P/L + persistent latch. Realized P/L is rebuilt from broker |
//| history; the latch is stored in terminal GlobalVariables (flushed |
//| to disk), so both survive an EA or terminal restart.              |
//+------------------------------------------------------------------+
void UpdateDaily(const bool force)
  {
   datetime now = ServerNow();
   int day = CaiDayId(now);

   double gvDay = 0.0, gvLatch = 0.0;
   bool haveDay = CaiGvGet("DAY", gvDay);
   if(!haveDay || (int)gvDay != day)
     {
      // New broker day (or first run): reset the latch.
      if(!CaiGvSet("DAY", (double)day) || !CaiGvSet("LATCH", 0.0))
        {
         g_dailyOk = false;                                  // cannot persist -> do not trade
         return;
        }
      g_latched = false;
      g_dailyDirty = true;
     }
   else
     {
      CaiGvGet("LATCH", gvLatch);
      g_latched = (gvLatch != 0.0);
     }

   if(force || g_dailyDirty || now != g_dailyCalcAt)         // at most once per second unless forced
     {
      datetime dayStart = (datetime)((long)now - (long)now % 86400);
      double realized = 0.0;
      int entries = 0;
      if(CaiDayHistory(dayStart, now, realized, entries))
        {
         g_realized = realized;
         g_tradesToday = entries;
         g_dailyOk = true;
         g_dailyDirty = false;
        }
      else
         g_dailyOk = false;
      g_dailyCalcAt = now;
     }
   g_floating = CaiManagedFloating();

   if(InpDailyStops && g_dailyOk && !g_latched)
     {
      int breach = CaiDailyBreach(g_realized, g_floating, InpDailyProfit, InpDailyLoss);
      if(breach != 0)
        {
         g_latched = true;
         bool saved = CaiGvSet("LATCH", (double)breach);
         AuditEvent("DAILY_STOP", 0, "", "HOLD", 0.0, "LATCHED",
             StringFormat("%s; persisted=%s", breach == 1 ? "daily profit target" : "daily loss limit",
                          saved ? "yes" : "NO"));
        }
     }
  }
//+------------------------------------------------------------------+
double AtrForPosition(const ulong ticket, const double entry, const double tp)
  {
   double v = 0.0;
   if(CaiGvGet(StringFormat("ATR_%I64u", ticket), v) && v > 0.0)
      return v;                                              // ATR recorded at entry
   if(tp > 0.0 && InpTpAtr > 0.0)
      return MathAbs(tp - entry) / InpTpAtr;                 // TP was placed at entry +/- InpTpAtr*ATR
   double buf[];
   if(CopyBuffer(g_atrHandle, 0, 1, 1, buf) == 1 && buf[0] > 0.0)
      return buf[0];
   return 0.0;
  }
//+------------------------------------------------------------------+
//| Runs on every tick and every timer second. No HTTP, no AI.        |
//+------------------------------------------------------------------+
void Protect()
  {
   UpdateDaily(false);
   datetime now = ServerNow();
   ulong tickets[];
   int n = CaiManagedTickets(tickets);
   if(n == 0)
      return;

   //--- daily stop: close managed positions; repeat once per second until flat
   if(InpDailyStops && g_latched)
     {
      if(now != g_lastCloseTry)
        {
         g_lastCloseTry = now;
         uint rc = 0;
         bool flat = CaiCloseManaged(rc);
         g_dailyDirty = true;
         AuditEvent("DAILY_STOP_CLOSE", 0, "", "HOLD", 0.0, flat ? "CLOSED" : "CLOSE_PENDING", "daily stop latched",
             0.0, 0.0, 0.0, tickets[0], rc);
        }
      return;
     }

   //--- quick profit (optional): aggregate floating P/L of managed positions
   if(InpQuickProfit && g_floating >= InpQuickProfitMoney - CAI_EPS)
     {
      if(now != g_lastCloseTry)
        {
         g_lastCloseTry = now;
         uint rc = 0;
         bool flat = CaiCloseManaged(rc);
         g_dailyDirty = true;
         AuditEvent("QUICK_PROFIT", 0, "", "HOLD", 0.0, flat ? "CLOSED" : "CLOSE_PENDING",
             StringFormat("floating %.2f >= %.2f", g_floating, InpQuickProfitMoney), 0.0, 0.0, 0.0, tickets[0], rc);
        }
      return;
     }

   //--- break-even / trailing
   if(now == g_lastModifyFail)
      return;                                                // do not hammer the server after a rejection
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol, tick))
      return;
   double point    = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double minDist  = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
   double freeze   = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL) * point;
   if(tickSize <= 0.0)
      return;
   for(int i = 0; i < n; i++)
     {
      if(!PositionSelectByTicket(tickets[i]))
         continue;
      bool   isBuy = ((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY);
      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl    = PositionGetDouble(POSITION_SL);
      double tp    = PositionGetDouble(POSITION_TP);
      double price = isBuy ? tick.bid : tick.ask;
      double atr   = AtrForPosition(tickets[i], entry, tp);
      double newSl = CaiTrailSL(isBuy, entry, sl, price, atr, tickSize,
                                InpBeTriggerAtr, InpTrailStartAtr, InpTrailDistAtr,
                                InpBeBufferTicks, minDist, freeze);
      if(newSl <= 0.0)
         continue;
      // Defence in depth: never loosen a stop, whatever the calculation returned.
      if(sl > 0.0 && ((isBuy && newSl <= sl) || (!isBuy && newSl >= sl)))
         continue;
      uint rc = 0;
      bool ok = CaiModifySl(tickets[i], newSl, tp, rc);
      if(!ok)
         g_lastModifyFail = now;
      AuditEvent("SL_MOVE", 0, "", isBuy ? "BUY" : "SELL", 0.0, ok ? "MODIFIED" : "MODIFY_FAILED",
          StringFormat("sl %.5f -> %.5f", sl, newSl), PositionGetDouble(POSITION_VOLUME), newSl, tp, tickets[i], rc);
     }
  }
//+------------------------------------------------------------------+
//| A closed M5 bar that has not been evaluated yet (restart-safe).   |
//+------------------------------------------------------------------+
bool NextClosedBar(datetime &barTime)
  {
   datetime t1 = iTime(_Symbol, PERIOD_M5, 1);
   if(t1 <= 0 || t1 <= g_lastEvalBar)
      return false;
   if(g_lastEvalBar > 0 && (long)t1 - (long)g_lastEvalBar < InpEvalIntervalSec)
      return false;
   barTime = t1;
   return true;
  }
//+------------------------------------------------------------------+
void MarkEvaluated(const datetime barTime)
  {
   g_lastEvalBar = barTime;
   CaiGvSet("LASTEVALBAR", (double)(long)barTime);
  }
//+------------------------------------------------------------------+
long SignalAgeSec(const datetime barTime)
  {
   return (long)ServerNow() - ((long)barTime + 300);
  }
//+------------------------------------------------------------------+
//| Cheap pre-check before a paid AI call: returns a reason when no   |
//| signal could lead to any action right now, "" otherwise. Uses     |
//| only guards whose state cannot improve within one signal deadline.|
//| The full gate in TryEnter still runs on every signal.             |
//+------------------------------------------------------------------+
string AskBlockedReason()
  {
   if(!InpSkipAiWhenBlocked)
      return "";
   UpdateDaily(false);
   ulong tickets[];
   if(CaiManagedTickets(tickets) > 0)
     {
      // With a position open a signal matters only if it may close or reverse it.
      if(!InpReverseMode && !InpCloseOnHold)
         return "position open; reverse and HOLD-close are OFF";
      return "";
     }
   if(InpDailyStops && g_latched)
      return "daily stop latched";
   if(g_dailyOk && g_tradesToday >= InpMaxTradesPerDay)
      return "daily trade cap reached";
   datetime utc;
   int off = 0;
   string session = "NONE";
   if(!UtcNow(utc, off))
      return "server UTC offset unknown";
   if(!CaiSessionAllowed(utc, InpUseLondon, InpLondonStartHHMM, InpLondonEndHHMM,
                         InpUseNewYork, InpNewYorkStartHHMM, InpNewYorkEndHHMM,
                         InpUseAsia, InpAsiaStartHHMM, InpAsiaEndHHMM, session))
      return "outside allowed sessions";
   double lastEntry = 0.0;
   if(CaiGvGet("LASTENTRY", lastEntry) && lastEntry > 0.0 &&
      (long)ServerNow() - (long)lastEntry + InpSignalDeadlineSec < InpCooldownSec)
      return "cooldown active";
   return "";
  }
//+------------------------------------------------------------------+
//| All entry guards, in fixed order. The first failure blocks.       |
//| Mirrors refmodel/risk.py::entry_gate.                             |
//+------------------------------------------------------------------+
void TryEnter(const CaiSignal &sig, const datetime barTime, const string requestId, const long latencyMs)
  {
   string name = CaiSideName(sig.side);
   bool   isBuy = (sig.side == CAI_SIG_BUY);
   string block = "";
   double volume = 0.0, sl = 0.0, tp = 0.0, atr = 0.0;

   UpdateDaily(true);
   MqlTick tick;
   bool haveTick = SymbolInfoTick(_Symbol, tick);
   double point    = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double spread   = (haveTick && point > 0.0) ? (tick.ask - tick.bid) / point : 1e9;
   datetime utc;
   int off = 0;
   bool haveUtc = UtcNow(utc, off);
   string session = "NONE";
   double lastOrderBar = -1.0, lastEntry = 0.0;
   CaiGvGet("LASTORDERBAR", lastOrderBar);
   CaiGvGet("LASTENTRY", lastEntry);
   ulong tickets[];

   if(sig.side != CAI_SIG_BUY && sig.side != CAI_SIG_SELL)        block = "signal is HOLD/invalid";
   else if(!InpAllowOrders)                                       block = "live orders not enabled (InpAllowOrders=false)";
   else if(!CaiTradePermitted())                                  block = "trading not permitted";
   else if(!g_symbolOk)                                           block = "symbol not allowlisted";
   else if(sig.barTime != barTime || barTime != iTime(_Symbol, PERIOD_M5, 1))
                                                                  block = "signal is not for the last closed bar";
   else if(SignalAgeSec(barTime) > InpMaxSignalAgeSec || SignalAgeSec(barTime) < -5)
                                                                  block = "signal stale";
   else if((long)lastOrderBar == (long)barTime)                   block = "bar already traded (dedup)";
   else if(sig.confidence < InpMinConfidence)                     block = "confidence below minimum";
   else if(!g_dailyOk)                                            block = "daily P/L unavailable";
   else if(InpDailyStops && g_latched)                            block = "daily stop latched";
   else if(!haveUtc)                                              block = "server UTC offset unknown";
   else if(!CaiSessionAllowed(utc, InpUseLondon, InpLondonStartHHMM, InpLondonEndHHMM,
                              InpUseNewYork, InpNewYorkStartHHMM, InpNewYorkEndHHMM,
                              InpUseAsia, InpAsiaStartHHMM, InpAsiaEndHHMM, session))
                                                                  block = "outside allowed sessions";
   else if(!haveTick || spread > InpMaxSpreadPoints)              block = "spread above limit";
   else if(g_tradesToday >= InpMaxTradesPerDay)                   block = "daily trade cap reached";
   else if(lastEntry > 0.0 && (long)ServerNow() - (long)lastEntry < InpCooldownSec)
                                                                  block = "cooldown active";
   else if(CaiForeignPositionOnNetting())                         block = "netting account holds a non-EA position on this symbol";
   else if(CaiManagedTickets(tickets) != 0)                       block = "managed position already open";
   else
     {
      double buf[];
      if(CopyBuffer(g_atrHandle, 0, 1, 1, buf) != 1 || !(buf[0] > 0.0) || !MathIsValidNumber(buf[0]) || tickSize <= 0.0)
         block = "ATR unavailable";
      else
        {
         atr = buf[0];
         double entry = isBuy ? tick.ask : tick.bid;
         CaiInitialStops(isBuy, entry, atr, tickSize, InpSlAtr, InpTpAtr, sl, tp);
         double raw = (InpLotMode == CAI_LOT_FIXED) ? InpFixedLot : CaiVolumeForRisk(isBuy, entry, sl, InpRiskMoney);
         volume = CaiNormalizeVolume(raw, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN),
                                     SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX),
                                     SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP));
         double minDist = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * point;
         if(volume <= 0.0)                                          block = "volume below broker minimum";
         else if(!CaiStopsValid(isBuy, tick.bid, tick.ask, sl, tp, minDist))
                                                                    block = "SL/TP violate broker stop level";
         else if(!CaiMarginOk(isBuy, volume, entry, InpMaxMarginUsePct))
                                                                    block = "insufficient free margin";
        }
     }

   if(block != "")
     {
      AuditEvent("GATE", barTime, requestId, name, sig.confidence, "BLOCKED", block, volume, sl, tp, 0, 0, latencyMs);
      return;
     }

   // Write-ahead de-duplication: record the bar BEFORE sending. If the terminal dies between
   // these two steps the bar is skipped, never traded twice. The order itself is never retried.
   if(!CaiGvSet("LASTORDERBAR", (double)(long)barTime))
     {
      AuditEvent("GATE", barTime, requestId, name, sig.confidence, "BLOCKED", "cannot persist dedup state", volume, sl, tp);
      return;
     }
   uint  retcode = 0;
   ulong order = 0;
   bool ok = CaiOpen(isBuy, volume, sl, tp, "ClaudeEA", retcode, order);
   g_dailyDirty = true;
   if(ok)
     {
      CaiGvSet("LASTENTRY", (double)(long)ServerNow());
      ulong opened[];
      int n = CaiManagedTickets(opened);
      for(int i = 0; i < n; i++)
        {
         string key = StringFormat("ATR_%I64u", opened[i]);
         double dummy = 0.0;
         if(!CaiGvGet(key, dummy))
            CaiGvSet(key, atr);
        }
     }
   AuditEvent("ORDER", barTime, requestId, name, sig.confidence, ok ? "SENT" : "REJECTED",
       StringFormat("session=%s atr=%.5f", session, atr), volume, sl, tp, order, retcode, latencyMs);
  }
//+------------------------------------------------------------------+
//| Act on one FINAL signal for one closed bar.                       |
//+------------------------------------------------------------------+
void HandleSignal(const CaiSignal &sig, const datetime barTime, const string requestId, const long latencyMs)
  {
   string name = CaiSideName(sig.side);
   AuditEvent("SIGNAL", barTime, requestId, name, sig.confidence, "RECEIVED", sig.source + ": " + sig.reason,
       0.0, 0.0, 0.0, 0, 0, latencyMs);

   ulong tickets[];
   int n = CaiManagedTickets(tickets);
   int posSide = CAI_SIG_HOLD;
   if(n > 0 && PositionSelectByTicket(tickets[0]))
      posSide = ((ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? CAI_SIG_BUY : CAI_SIG_SELL;

   if(sig.side == CAI_SIG_HOLD)
     {
      // HOLD never closes a position unless the operator explicitly enabled it.
      if(InpCloseOnHold && n > 0)
        {
         uint rc = 0;
         bool flat = CaiCloseManaged(rc);
         g_dailyDirty = true;
         AuditEvent("HOLD_CLOSE", barTime, requestId, name, 0.0, flat ? "CLOSED" : "CLOSE_FAILED", "InpCloseOnHold",
             0.0, 0.0, 0.0, tickets[0], rc);
        }
      return;
     }
   if(n > 0 && posSide == sig.side)
     {
      AuditEvent("GATE", barTime, requestId, name, sig.confidence, "NO_ACTION", "managed position already in this direction");
      return;
     }
   if(n > 0)
     {
      if(!InpReverseMode)
        {
         AuditEvent("GATE", barTime, requestId, name, sig.confidence, "IGNORED", "opposite signal; reverse mode is OFF");
         return;
        }
      if(!InpAllowOrders || sig.confidence < InpMinConfidence || sig.barTime != barTime ||
         SignalAgeSec(barTime) > InpMaxSignalAgeSec)
        {
         AuditEvent("GATE", barTime, requestId, name, sig.confidence, "BLOCKED", "reverse pre-check failed; position kept");
         return;
        }
      uint rc = 0;
      bool flat = CaiCloseManaged(rc);
      g_dailyDirty = true;
      AuditEvent("REVERSE_CLOSE", barTime, requestId, name, sig.confidence, flat ? "CLOSED" : "CLOSE_NOT_VERIFIED",
          "reverse mode", 0.0, 0.0, 0.0, tickets[0], rc);
      if(!flat)
         return;                                             // never open against a position that may still exist
     }
   TryEnter(sig, barTime, requestId, latencyMs);             // full gate re-check (incl. daily stop) before any order
  }
//+------------------------------------------------------------------+
//| Strategy Tester path: historical replay, no HTTP.                 |
//+------------------------------------------------------------------+
void ReplayStep()
  {
   datetime barTime;
   if(!NextClosedBar(barTime))
      return;
   MarkEvaluated(barTime);
   if(!g_signalsEnabled)
      return;
   CaiSignal sig;
   CaiReplayLookup(barTime, sig);
   HandleSignal(sig, barTime, CaiRequestId(_Symbol, barTime, InpMagic), 0);
  }
//+------------------------------------------------------------------+
void FinishRequest(const string decision, const string reason)
  {
   AuditEvent("SIGNAL", g_reqBar, g_reqId, "HOLD", 0.0, decision, reason, 0.0, 0.0, 0.0, 0, 0,
       (long)(GetTickCount64() - g_reqStartMs));
   g_state = ST_IDLE;
  }
//+------------------------------------------------------------------+
//| Live path, called once per second from OnTimer. At most ONE short |
//| HTTP call per invocation; retries/backoff live in the bridge.     |
//+------------------------------------------------------------------+
void BridgeStep()
  {
   if(g_state == ST_IDLE)
     {
      datetime barTime;
      if(!NextClosedBar(barTime))
         return;
      MarkEvaluated(barTime);
      g_reqBar = barTime;
      g_reqId = CaiRequestId(_Symbol, barTime, InpMagic);
      g_reqStartMs = GetTickCount64();
      if(!g_signalsEnabled)
         return;
      if(SignalAgeSec(barTime) > InpMaxSignalAgeSec)
        {
         FinishRequest("SKIPPED", "bar already stale (market gap or late start)");
         return;
        }
      string skip = AskBlockedReason();
      if(skip != "")
        {
         FinishRequest("NOT_ASKED", skip);                   // no HTTP, no API cost
         return;
        }
      MqlRates rates[];
      ArraySetAsSeries(rates, false);
      double atr[];
      int off = 0;
      datetime utc;
      if(CopyRates(_Symbol, PERIOD_M5, 1, 20, rates) != 20 || rates[19].time != barTime ||
         CopyBuffer(g_atrHandle, 0, 1, 1, atr) != 1 || !UtcNow(utc, off) ||
         !CaiBuildRequest(_Symbol, g_reqId, rates, atr[0], SpreadPoints(), off, g_reqBody))
        {
         FinishRequest("HOLD", "market data incomplete or malformed");
         return;
        }
      g_reqDeadline = ServerNow() + InpSignalDeadlineSec;
      g_reqSubmitTries = 0;
      g_reqPollErrors = 0;
      g_state = ST_SUBMIT;
     }

   // A newer bar has closed, or the deadline passed: the pending answer is worthless.
   if(iTime(_Symbol, PERIOD_M5, 1) != g_reqBar || ServerNow() > g_reqDeadline)
     {
      FinishRequest("HOLD", "no final signal before deadline");
      return;
     }

   string response = "";
   CaiSignal sig;
   int status = -1;
   int result = CAI_BRIDGE_ERROR;
   if(g_state == ST_SUBMIT)
     {
      g_reqSubmitTries++;
      status = CaiHttp("POST", InpBridgeUrl + "/v1/signal", g_reqBody, InpHttpTimeoutMs, response);
      result = CaiParseResponse(status, response, g_reqId, g_reqBar, sig);
      if(result == CAI_BRIDGE_ERROR)
        {
         // The POST is idempotent (request id), so one more attempt on the next second is safe.
         if(status == -1 && g_reqSubmitTries < 2)
            return;
         FinishRequest("HOLD", sig.reason);
         return;
        }
     }
   else
     {
      status = CaiHttp("GET", InpBridgeUrl + "/v1/signal/" + g_reqId, "", InpHttpTimeoutMs, response);
      result = CaiParseResponse(status, response, g_reqId, g_reqBar, sig);
      if(result == CAI_BRIDGE_ERROR)
        {
         g_reqPollErrors++;
         if(g_reqPollErrors < 3 && status == -1)
            return;
         FinishRequest("HOLD", sig.reason);
         return;
        }
     }
   if(result == CAI_BRIDGE_PENDING)
     {
      g_state = ST_POLL;
      return;
     }
   g_state = ST_IDLE;
   HandleSignal(sig, g_reqBar, g_reqId, (long)(GetTickCount64() - g_reqStartMs));
  }
//+------------------------------------------------------------------+
void OnTick()
  {
   Protect();                       // position protection first, on every tick
   if(g_useReplay)
      ReplayStep();                 // tester: one evaluation per new closed bar
  }
//+------------------------------------------------------------------+
void OnTimer()
  {
   Protect();                       // also when the market is quiet
   if(!g_useReplay)
      BridgeStep();                 // live: all HTTP happens here, never in OnTick
  }
//+------------------------------------------------------------------+
