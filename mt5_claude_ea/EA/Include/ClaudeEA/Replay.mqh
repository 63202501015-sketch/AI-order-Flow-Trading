//+------------------------------------------------------------------+
//| Replay.mqh - historical AI replay for the Strategy Tester.        |
//| WebRequest is not available in the tester, so signals come from a |
//| CSV produced offline by `python -m replay.generate`:              |
//|   bar_time,signal,confidence,source                               |
//| bar_time = open time (broker server clock) of the CLOSED bar the  |
//| signal was computed from. The EA reads the row only after that    |
//| bar has closed, so no future information is available to it.      |
//+------------------------------------------------------------------+
#ifndef CLAUDEEA_REPLAY_MQH
#define CLAUDEEA_REPLAY_MQH

#include "Bridge.mqh"

long   g_caiReplayTime[];
int    g_caiReplaySide[];
double g_caiReplayConf[];
int    g_caiReplayCount = 0;

//+------------------------------------------------------------------+
//| Loads the file from the terminal COMMON folder. Rows must be      |
//| strictly ascending by time; any malformed row aborts the load.    |
//+------------------------------------------------------------------+
bool CaiReplayLoad(const string fileName)
  {
   g_caiReplayCount = 0;
   ArrayResize(g_caiReplayTime, 0);
   ArrayResize(g_caiReplaySide, 0);
   ArrayResize(g_caiReplayConf, 0);
   int h = FileOpen(fileName, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
      return false;
   bool first = true;
   bool ok = true;
   long prev = 0;
   while(!FileIsEnding(h))
     {
      string line = FileReadString(h);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(line == "" || StringGetCharacter(line, 0) == '#')
         continue;
      if(first)
        {
         first = false;
         if(StringFind(line, "bar_time") == 0)
            continue;                                         // header
        }
      string parts[];
      if(StringSplit(line, ',', parts) < 3)
        { ok = false; break; }
      long   t = StringToInteger(parts[0]);
      double c = StringToDouble(parts[2]);
      int side = CAI_SIG_HOLD;
      if(parts[1] == "BUY")       side = CAI_SIG_BUY;
      else if(parts[1] == "SELL") side = CAI_SIG_SELL;
      else if(parts[1] == "HOLD") side = CAI_SIG_HOLD;
      else { ok = false; break; }
      if(t <= prev || t % 300 != 0 || c < 0.0 || c > 100.0 || !MathIsValidNumber(c))
        { ok = false; break; }
      prev = t;
      int n = g_caiReplayCount;
      if(n >= ArraySize(g_caiReplayTime))
        {
         ArrayResize(g_caiReplayTime, n + 4096);
         ArrayResize(g_caiReplaySide, n + 4096);
         ArrayResize(g_caiReplayConf, n + 4096);
        }
      g_caiReplayTime[n] = t;
      g_caiReplaySide[n] = side;
      g_caiReplayConf[n] = c;
      g_caiReplayCount++;
     }
   FileClose(h);
   if(!ok)
      g_caiReplayCount = 0;
   return (ok && g_caiReplayCount > 0);
  }
//+------------------------------------------------------------------+
//| Exact-match lookup for a closed bar. Missing row => HOLD.         |
//+------------------------------------------------------------------+
void CaiReplayLookup(const datetime closedBarTime, CaiSignal &sig)
  {
   CaiHold(sig, "replay: no signal for this bar");
   sig.source = "replay";
   long key = (long)closedBarTime;
   int lo = 0, hi = g_caiReplayCount - 1;
   while(lo <= hi)
     {
      int mid = (lo + hi) / 2;
      if(g_caiReplayTime[mid] == key)
        {
         sig.side = g_caiReplaySide[mid];
         sig.confidence = g_caiReplayConf[mid];
         sig.reason = "replay";
         sig.barTime = closedBarTime;
         return;
        }
      if(g_caiReplayTime[mid] < key)
         lo = mid + 1;
      else
         hi = mid - 1;
     }
  }

#endif // CLAUDEEA_REPLAY_MQH
