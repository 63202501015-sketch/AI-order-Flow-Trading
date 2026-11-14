//+------------------------------------------------------------------+
//| Sessions.mqh - DST-aware London / New York session gate.          |
//| MQL5 has no IANA time-zone database, so the EU and US daylight    |
//| saving calendars are computed arithmetically. Mirrors             |
//| refmodel/sessions.py, which is tested against IANA zoneinfo.      |
//+------------------------------------------------------------------+
#ifndef CLAUDEEA_SESSIONS_MQH
#define CLAUDEEA_SESSIONS_MQH

enum ENUM_CAI_SERVER_TIME_MODE
  {
   CAI_SERVER_TIME_AUTO   = 0,   // AUTO: TimeTradeServer()-TimeGMT() (live only)
   CAI_SERVER_TIME_MANUAL = 1    // MANUAL: standard offset + DST rule (required in tester)
  };

enum ENUM_CAI_DST_RULE
  {
   CAI_DST_NONE = 0,             // broker clock never changes
   CAI_DST_EU   = 1,             // +1h during EU summer time
   CAI_DST_US   = 2              // +1h during US daylight time
  };

//+------------------------------------------------------------------+
datetime CaiMakeTime(const int y, const int mo, const int d, const int h)
  {
   MqlDateTime s;
   ZeroMemory(s);
   s.year = y; s.mon = mo; s.day = d; s.hour = h;
   return StructToTime(s);
  }
//+------------------------------------------------------------------+
int CaiDayOfWeek(const int y, const int mo, const int d)      // 0 = Sunday
  {
   MqlDateTime s;
   TimeToStruct(CaiMakeTime(y, mo, d, 0), s);
   return s.day_of_week;
  }
//+------------------------------------------------------------------+
int CaiNthSunday(const int y, const int mo, const int n)
  {
   int dow = CaiDayOfWeek(y, mo, 1);
   return 1 + (7 - dow) % 7 + 7 * (n - 1);
  }
//+------------------------------------------------------------------+
int CaiLastSunday31(const int y, const int mo)                // for 31-day months (March, October)
  {
   return 31 - CaiDayOfWeek(y, mo, 31);
  }
//+------------------------------------------------------------------+
//| EU/UK: last Sunday of March 01:00 UTC .. last Sunday of Oct 01:00 |
//+------------------------------------------------------------------+
bool CaiEuDst(const datetime utc)
  {
   MqlDateTime s;
   TimeToStruct(utc, s);
   datetime start = CaiMakeTime(s.year, 3,  CaiLastSunday31(s.year, 3),  1);
   datetime end   = CaiMakeTime(s.year, 10, CaiLastSunday31(s.year, 10), 1);
   return (utc >= start && utc < end);
  }
//+------------------------------------------------------------------+
//| US: 2nd Sunday of March 07:00 UTC .. 1st Sunday of Nov 06:00 UTC  |
//+------------------------------------------------------------------+
bool CaiUsDst(const datetime utc)
  {
   MqlDateTime s;
   TimeToStruct(utc, s);
   datetime start = CaiMakeTime(s.year, 3,  CaiNthSunday(s.year, 3, 2),  7);
   datetime end   = CaiMakeTime(s.year, 11, CaiNthSunday(s.year, 11, 1), 6);
   return (utc >= start && utc < end);
  }
//+------------------------------------------------------------------+
int CaiLondonOffset(const datetime utc)  { return CaiEuDst(utc) ? 3600 : 0; }
int CaiNewYorkOffset(const datetime utc) { return CaiUsDst(utc) ? -4 * 3600 : -5 * 3600; }
//+------------------------------------------------------------------+
//| Window in minutes after local midnight: [startMin, endMin).       |
//| Saturday and Sunday (local) are always closed.                    |
//+------------------------------------------------------------------+
bool CaiInWindow(const datetime utc, const int offsetSec, const int startMin, const int endMin)
  {
   long local = (long)utc + offsetSec;
   if(local < 0)
      return false;
   int dow = (int)((local / 86400 + 4) % 7);                  // 1970-01-01 was a Thursday; 0 = Sunday
   if(dow == 0 || dow == 6)
      return false;
   int minute = (int)((local % 86400) / 60);
   return (minute >= startMin && minute < endMin);
  }
//+------------------------------------------------------------------+
int CaiHhmmToMin(const int hhmm) { return (hhmm / 100) * 60 + (hhmm % 100); }
bool CaiHhmmValid(const int hhmm) { return (hhmm >= 0 && hhmm <= 2400 && hhmm % 100 < 60); }
//+------------------------------------------------------------------+
//| Returns true and the session name if utc falls in an enabled      |
//| session. Asia (Tokyo, UTC+9, no DST) is OFF unless enabled.       |
//+------------------------------------------------------------------+
bool CaiSessionAllowed(const datetime utc,
                       const bool useLondon, const int lonStart, const int lonEnd,
                       const bool useNewYork, const int nyStart, const int nyEnd,
                       const bool useAsia, const int asiaStart, const int asiaEnd,
                       string &name)
  {
   name = "NONE";
   if(useLondon && CaiInWindow(utc, CaiLondonOffset(utc), CaiHhmmToMin(lonStart), CaiHhmmToMin(lonEnd)))
     { name = "LONDON"; return true; }
   if(useNewYork && CaiInWindow(utc, CaiNewYorkOffset(utc), CaiHhmmToMin(nyStart), CaiHhmmToMin(nyEnd)))
     { name = "NEW_YORK"; return true; }
   if(useAsia && CaiInWindow(utc, 9 * 3600, CaiHhmmToMin(asiaStart), CaiHhmmToMin(asiaEnd)))
     { name = "ASIA"; return true; }
   return false;
  }
//+------------------------------------------------------------------+
bool CaiDstByRule(const ENUM_CAI_DST_RULE rule, const datetime utc)
  {
   if(rule == CAI_DST_EU) return CaiEuDst(utc);
   if(rule == CAI_DST_US) return CaiUsDst(utc);
   return false;
  }
//+------------------------------------------------------------------+
//| Manual conversion of a broker-server timestamp to UTC.            |
//+------------------------------------------------------------------+
datetime CaiServerToUtcManual(const datetime server, const int stdOffsetHours, const ENUM_CAI_DST_RULE rule)
  {
   datetime utc = server - stdOffsetHours * 3600;
   utc = server - (stdOffsetHours + (CaiDstByRule(rule, utc) ? 1 : 0)) * 3600;
   return server - (stdOffsetHours + (CaiDstByRule(rule, utc) ? 1 : 0)) * 3600;
  }
//+------------------------------------------------------------------+
//| Server-minus-UTC offset in seconds. Returns false when it cannot  |
//| be determined (caller must then block entries).                   |
//+------------------------------------------------------------------+
bool CaiServerUtcOffset(const ENUM_CAI_SERVER_TIME_MODE mode, const int stdOffsetHours,
                        const ENUM_CAI_DST_RULE rule, const datetime serverNow, int &offsetSec)
  {
   offsetSec = 0;
   if(mode == CAI_SERVER_TIME_MANUAL)
     {
      datetime utc = CaiServerToUtcManual(serverNow, stdOffsetHours, rule);
      offsetSec = (int)(serverNow - utc);
      return true;
     }
   if(MQLInfoInteger(MQL_TESTER))
      return false;                           // TimeGMT() is simulated in the tester: AUTO is meaningless
   long diff = (long)TimeTradeServer() - (long)TimeGMT();
   long rounded = (long)MathRound((double)diff / 900.0) * 900;      // offsets are multiples of 15 minutes
   if(MathAbs(diff - rounded) > 120 || MathAbs(rounded) > 14 * 3600)
      return false;                           // local clock is off: do not guess
   offsetSec = (int)rounded;
   return true;
  }

#endif // CLAUDEEA_SESSIONS_MQH
