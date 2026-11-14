//+------------------------------------------------------------------+
//| Audit.mqh - append-only CSV audit log (MQL5/Files).               |
//| Never receives the bridge token; text fields are sanitised.       |
//+------------------------------------------------------------------+
#ifndef CLAUDEEA_AUDIT_MQH
#define CLAUDEEA_AUDIT_MQH

string g_caiAuditFile = "";
bool   g_caiAuditOn   = false;

//+------------------------------------------------------------------+
string CaiClean(const string text, const int maxLen = 300)
  {
   string s = text;
   StringReplace(s, ",", ";");
   StringReplace(s, "\"", "'");
   StringReplace(s, "\r", " ");
   StringReplace(s, "\n", " ");
   if(StringLen(s) > maxLen)
      s = StringSubstr(s, 0, maxLen);
   return s;
  }
//+------------------------------------------------------------------+
string CaiUtcStamp(const datetime utc)
  {
   MqlDateTime s;
   TimeToStruct(utc, s);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ", s.year, s.mon, s.day, s.hour, s.min, s.sec);
  }
//+------------------------------------------------------------------+
void CaiAuditInit(const bool enabled, const string symbol, const long magic)
  {
   g_caiAuditOn = enabled;
   g_caiAuditFile = StringFormat("ClaudeEA_audit_%s_%I64d.csv", symbol, magic);
   if(!g_caiAuditOn)
      return;
   int h = FileOpen(g_caiAuditFile, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ);
   if(h == INVALID_HANDLE)
     {
      PrintFormat("ClaudeEA: cannot open audit file %s (error %d); audit disabled", g_caiAuditFile, GetLastError());
      g_caiAuditOn = false;
      return;
     }
   if(FileSize(h) == 0)
      FileWriteString(h, "ts_utc,event,symbol,bar_time,request_id,signal,confidence,decision,reason,"
                         "equity,daily_pnl,spread_points,volume,sl,tp,ticket,retcode,latency_ms\r\n");
   FileClose(h);
  }
//+------------------------------------------------------------------+
void CaiAudit(const datetime utcNow, const string event, const string symbol, const datetime barTime,
              const string requestId, const string signal, const double confidence,
              const string decision, const string reason,
              const double equity, const double dailyPnl, const double spreadPoints,
              const double volume, const double sl, const double tp,
              const ulong ticket, const uint retcode, const long latencyMs)
  {
   string line = StringFormat("%s,%s,%s,%I64d,%s,%s,%.1f,%s,%s,%.2f,%.2f,%.1f,%.2f,%.5f,%.5f,%I64u,%u,%I64d",
                              CaiUtcStamp(utcNow), CaiClean(event, 32), CaiClean(symbol, 32), (long)barTime,
                              CaiClean(requestId, 96), CaiClean(signal, 8), confidence,
                              CaiClean(decision, 32), CaiClean(reason),
                              equity, dailyPnl, spreadPoints, volume, sl, tp, ticket, retcode, latencyMs);
   PrintFormat("ClaudeEA: %s", line);
   if(!g_caiAuditOn)
      return;
   int h = FileOpen(g_caiAuditFile, FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ);
   if(h == INVALID_HANDLE)
      return;
   FileSeek(h, 0, SEEK_END);
   FileWriteString(h, line + "\r\n");
   FileClose(h);
  }

#endif // CLAUDEEA_AUDIT_MQH
