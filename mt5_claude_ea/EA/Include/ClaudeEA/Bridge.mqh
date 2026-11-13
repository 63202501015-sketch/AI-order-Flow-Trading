//+------------------------------------------------------------------+
//| Bridge.mqh - client of the local Python bridge.                   |
//| One short WebRequest per call; no retry loops, no Sleep().        |
//| Any transport, status, schema or identity mismatch => HOLD.       |
//+------------------------------------------------------------------+
#ifndef CLAUDEEA_BRIDGE_MQH
#define CLAUDEEA_BRIDGE_MQH

#include "Json.mqh"

#define CAI_SIG_HOLD 0
#define CAI_SIG_BUY  1
#define CAI_SIG_SELL 2

#define CAI_BRIDGE_ERROR   0     // treat as HOLD for this bar
#define CAI_BRIDGE_PENDING 1
#define CAI_BRIDGE_FINAL   2

struct CaiSignal
  {
   int               side;          // CAI_SIG_*
   double            confidence;    // 0..100, uncalibrated self-report
   string            reason;        // logged only, never interpreted
   string            source;
   datetime          barTime;
  };

string g_caiBridgeToken = "";       // loaded from file, never printed

//+------------------------------------------------------------------+
string CaiSideName(const int side)
  {
   if(side == CAI_SIG_BUY)  return "BUY";
   if(side == CAI_SIG_SELL) return "SELL";
   return "HOLD";
  }
//+------------------------------------------------------------------+
void CaiHold(CaiSignal &sig, const string reason)
  {
   sig.side = CAI_SIG_HOLD;
   sig.confidence = 0.0;
   sig.reason = reason;
   sig.source = "ea";
   sig.barTime = 0;
  }
//+------------------------------------------------------------------+
//| Only loopback URLs are accepted.                                  |
//+------------------------------------------------------------------+
bool CaiBridgeUrlIsLocal(const string url)
  {
   return (StringFind(url, "http://127.0.0.1:") == 0 || StringFind(url, "http://localhost:") == 0);
  }
//+------------------------------------------------------------------+
//| Token lives in MQL5/Files/<file>, not in inputs/.set files.       |
//+------------------------------------------------------------------+
bool CaiBridgeLoadToken(const string fileName)
  {
   g_caiBridgeToken = "";
   int h = FileOpen(fileName, FILE_READ | FILE_TXT | FILE_ANSI);
   if(h == INVALID_HANDLE)
      return false;
   string t = FileReadString(h);
   FileClose(h);
   StringTrimLeft(t);
   StringTrimRight(t);
   if(StringLen(t) < 32 || StringLen(t) > 256)
      return false;
   for(int i = 0; i < StringLen(t); i++)
     {
      ushort c = StringGetCharacter(t, i);
      if(c <= 0x20 || c >= 0x7F)
         return false;
     }
   g_caiBridgeToken = t;
   return true;
  }
//+------------------------------------------------------------------+
//| Symbol characters allowed in request ids / JSON.                  |
//+------------------------------------------------------------------+
bool CaiSymbolCharsOk(const string symbol)
  {
   int n = StringLen(symbol);
   if(n < 1 || n > 30)
      return false;
   for(int i = 0; i < n; i++)
     {
      ushort c = StringGetCharacter(symbol, i);
      bool ok = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') ||
                c == '.' || c == '_' || c == '#' || c == '-';
      if(!ok)
         return false;
     }
   return true;
  }
//+------------------------------------------------------------------+
string CaiRequestId(const string symbol, const datetime barTime, const long magic)
  {
   return StringFormat("%s-M5-%I64d-%I64d", symbol, (long)barTime, magic);
  }
//+------------------------------------------------------------------+
//| Build the request body from 20 CLOSED bars (rates[0] = oldest).   |
//| Returns false if the series is incomplete or malformed.           |
//+------------------------------------------------------------------+
bool CaiBuildRequest(const string symbol, const string requestId, const MqlRates &rates[],
                     const double atr, const double spreadPoints, const int serverUtcOffsetSec,
                     string &body)
  {
   body = "";
   if(ArraySize(rates) != 20 || !(atr > 0.0) || !MathIsValidNumber(atr) || spreadPoints < 0.0)
      return false;
   int    digits   = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double point    = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double tickSize = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
   double contract = SymbolInfoDouble(symbol, SYMBOL_TRADE_CONTRACT_SIZE);
   if(point <= 0.0 || tickSize <= 0.0 || contract <= 0.0)
      return false;
   string candles = "";
   for(int i = 0; i < 20; i++)
     {
      double o = rates[i].open, h = rates[i].high, l = rates[i].low, c = rates[i].close;
      if(!(l > 0.0) || h < MathMax(o, c) || l > MathMin(o, c) || h < l)
         return false;                                       // malformed OHLC
      if(i > 0)
        {
         long gap = (long)rates[i].time - (long)rates[i - 1].time;
         if(gap <= 0 || gap % 300 != 0)
            return false;                                    // order / alignment
        }
      if((long)rates[i].time % 300 != 0)
         return false;
      if(i > 0)
         candles += ",";
      candles += StringFormat("{\"time\":%I64d,\"open\":%s,\"high\":%s,\"low\":%s,\"close\":%s}",
                              (long)rates[i].time,
                              DoubleToString(o, digits), DoubleToString(h, digits),
                              DoubleToString(l, digits), DoubleToString(c, digits));
     }
   body = StringFormat("{\"request_id\":\"%s\",\"symbol\":\"%s\",\"timeframe\":\"M5\","
                       "\"server_utc_offset_sec\":%d,\"spread_points\":%s,\"atr\":%s,\"digits\":%d,"
                       "\"point\":%s,\"tick_size\":%s,\"contract_size\":%s,\"candles\":[%s]}",
                       requestId, symbol, serverUtcOffsetSec,
                       DoubleToString(spreadPoints, 1), DoubleToString(atr, 8), digits,
                       DoubleToString(point, 8), DoubleToString(tickSize, 8),
                       DoubleToString(contract, 4), candles);
   return true;
  }
//+------------------------------------------------------------------+
//| One HTTP exchange. Returns HTTP status, or -1 on transport error. |
//+------------------------------------------------------------------+
int CaiHttp(const string method, const string url, const string body, const int timeoutMs, string &response)
  {
   response = "";
   if(g_caiBridgeToken == "" || !CaiBridgeUrlIsLocal(url))
      return -1;
   string headers = "Content-Type: application/json\r\nX-Bridge-Token: " + g_caiBridgeToken + "\r\n";
   char data[];
   char result[];
   string resultHeaders = "";
   if(body != "")
     {
      int n = StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
      if(n > 0)
         ArrayResize(data, n - 1);                           // drop the terminating zero
     }
   else
      ArrayResize(data, 0);
   ResetLastError();
   int status = WebRequest(method, url, headers, timeoutMs, data, result, resultHeaders);
   if(status == -1)
      return -1;                                             // 4014 = URL not in the allowed list
   if(ArraySize(result) > 8192)
      return -1;
   response = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   return status;
  }
//+------------------------------------------------------------------+
//| Validate a bridge response. Returns CAI_BRIDGE_*; sig is HOLD     |
//| unless the response is FINAL, well-formed and for OUR request.    |
//+------------------------------------------------------------------+
int CaiParseResponse(const int httpStatus, const string response, const string requestId,
                     const datetime barTime, CaiSignal &sig)
  {
   CaiHold(sig, "bridge unavailable");
   if(httpStatus != 200 && httpStatus != 202)
     {
      sig.reason = StringFormat("bridge http %d", httpStatus);
      return CAI_BRIDGE_ERROR;
     }
   CFlatJson json;
   if(!json.Parse(response))
     {
      sig.reason = "bridge response is not valid flat JSON";
      return CAI_BRIDGE_ERROR;
     }
   string rid = "", status = "", signal = "", reason = "", source = "";
   double conf = -1.0, bt = -1.0;
   if(!json.GetString("request_id", rid) || !json.GetString("status", status) ||
      !json.GetString("signal", signal) || !json.GetNumber("confidence", conf) ||
      !json.GetString("reason", reason) || !json.GetNumber("bar_time", bt) ||
      !json.GetString("source", source) || json.Count() != 7)
     {
      sig.reason = "bridge response schema mismatch";
      return CAI_BRIDGE_ERROR;
     }
   if(rid != requestId)
     {
      sig.reason = "bridge response is for another request";
      return CAI_BRIDGE_ERROR;
     }
   if(status == "pending")
     {
      sig.reason = "pending";
      return CAI_BRIDGE_PENDING;
     }
   if(status != "final" || conf < 0.0 || conf > 100.0)
     {
      sig.reason = "bridge response invalid status/confidence";
      return CAI_BRIDGE_ERROR;
     }
   sig.reason = reason;
   sig.source = source;
   sig.barTime = (datetime)(long)bt;
   if(signal == "HOLD")
      return CAI_BRIDGE_FINAL;
   if(signal != "BUY" && signal != "SELL")
     {
      CaiHold(sig, "bridge response has unknown signal");
      return CAI_BRIDGE_ERROR;
     }
   if((long)bt != (long)barTime)
     {
      CaiHold(sig, "bridge signal is for another bar");
      return CAI_BRIDGE_ERROR;
     }
   sig.side = (signal == "BUY") ? CAI_SIG_BUY : CAI_SIG_SELL;
   sig.confidence = conf;
   return CAI_BRIDGE_FINAL;
  }

#endif // CLAUDEEA_BRIDGE_MQH
