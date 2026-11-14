//+------------------------------------------------------------------+
//| Execution.mqh - position ownership, P/L accounting and CTrade     |
//| calls. Every function acts ONLY on positions/deals with this EA's |
//| magic number on this symbol; nothing else is ever touched.        |
//+------------------------------------------------------------------+
#ifndef CLAUDEEA_EXECUTION_MQH
#define CLAUDEEA_EXECUTION_MQH

#include <Trade\Trade.mqh>
#include "Risk.mqh"

CTrade g_caiTrade;
string g_caiSymbol = "";
long   g_caiMagic  = 0;

//+------------------------------------------------------------------+
void CaiExecInit(const string symbol, const long magic, const int maxSlippagePoints)
  {
   g_caiSymbol = symbol;
   g_caiMagic  = magic;
   g_caiTrade.SetExpertMagicNumber(magic);
   g_caiTrade.SetDeviationInPoints((ulong)MathMax(0, maxSlippagePoints));
   g_caiTrade.SetTypeFillingBySymbol(symbol);
   g_caiTrade.SetAsyncMode(false);            // synchronous: we read the retcode of each request
   g_caiTrade.LogLevel(LOG_LEVEL_ERRORS);
  }
//+------------------------------------------------------------------+
string CaiGvName(const string key)
  {
   return StringFormat("CAI_%I64d_%s_%s", g_caiMagic, g_caiSymbol, key);
  }
//+------------------------------------------------------------------+
bool CaiGvGet(const string key, double &value)
  {
   string name = CaiGvName(key);
   if(!GlobalVariableCheck(name))
      return false;
   return GlobalVariableGet(name, value);
  }
//+------------------------------------------------------------------+
//| Persist a value and flush it to disk. Returns false on failure so |
//| callers can refuse to trade when state cannot be saved.           |
//+------------------------------------------------------------------+
bool CaiGvSet(const string key, const double value)
  {
   if(GlobalVariableSet(CaiGvName(key), value) == 0)
      return false;
   GlobalVariablesFlush();
   return true;
  }
//+------------------------------------------------------------------+
bool CaiIsNetting()
  {
   return ((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);
  }
//+------------------------------------------------------------------+
bool CaiTradePermitted()
  {
   if(!MQLInfoInteger(MQL_TESTER) && !TerminalInfoInteger(TERMINAL_CONNECTED))
      return false;                                   // connection lost: fail closed
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED))  return false;
   if(!MQLInfoInteger(MQL_TRADE_ALLOWED))            return false;
   if(!AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))    return false;
   if(!AccountInfoInteger(ACCOUNT_TRADE_EXPERT))     return false;
   if((ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(g_caiSymbol, SYMBOL_TRADE_MODE) != SYMBOL_TRADE_MODE_FULL)
      return false;
   return true;
  }
//+------------------------------------------------------------------+
//| Collect tickets of managed positions (this symbol + this magic).  |
//+------------------------------------------------------------------+
int CaiManagedTickets(ulong &tickets[])
  {
   ArrayResize(tickets, 0);
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != g_caiSymbol)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != g_caiMagic)
         continue;
      int n = ArraySize(tickets);
      ArrayResize(tickets, n + 1);
      tickets[n] = ticket;
     }
   return ArraySize(tickets);
  }
//+------------------------------------------------------------------+
//| On netting accounts a position on this symbol with another magic  |
//| cannot be separated from ours: block entries entirely.            |
//+------------------------------------------------------------------+
bool CaiForeignPositionOnNetting()
  {
   if(!CaiIsNetting())
      return false;
   if(!PositionSelect(g_caiSymbol))
      return false;
   return (PositionGetInteger(POSITION_MAGIC) != g_caiMagic);
  }
//+------------------------------------------------------------------+
//| Floating P/L of managed positions (profit + swap).                |
//+------------------------------------------------------------------+
double CaiManagedFloating()
  {
   double sum = 0.0;
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != g_caiSymbol || PositionGetInteger(POSITION_MAGIC) != g_caiMagic)
         continue;
      sum += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
     }
   return sum;
  }
//+------------------------------------------------------------------+
//| Realized result of managed deals since dayStart, including        |
//| commission, fee and swap; also counts today's entries.            |
//| Recomputed from broker history, so it survives EA restarts.       |
//+------------------------------------------------------------------+
bool CaiDayHistory(const datetime dayStart, const datetime now, double &realized, int &entries)
  {
   realized = 0.0;
   entries = 0;
   if(!HistorySelect(dayStart, now + 86400))
      return false;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
     {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0)
         continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != g_caiSymbol)
         continue;
      if(HistoryDealGetInteger(deal, DEAL_MAGIC) != g_caiMagic)
         continue;
      ENUM_DEAL_TYPE type = (ENUM_DEAL_TYPE)HistoryDealGetInteger(deal, DEAL_TYPE);
      if(type != DEAL_TYPE_BUY && type != DEAL_TYPE_SELL)
         continue;
      realized += HistoryDealGetDouble(deal, DEAL_PROFIT) + HistoryDealGetDouble(deal, DEAL_SWAP) +
                  HistoryDealGetDouble(deal, DEAL_COMMISSION) + HistoryDealGetDouble(deal, DEAL_FEE);
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal, DEAL_ENTRY) == DEAL_ENTRY_IN)
         entries++;
     }
   return true;
  }
//+------------------------------------------------------------------+
//| Volume for a fixed money risk at the given stop distance.         |
//| Uses OrderCalcProfit so contract/currency conversion is the       |
//| broker's own. Returns 0 if it cannot be computed.                 |
//+------------------------------------------------------------------+
double CaiVolumeForRisk(const bool isBuy, const double entry, const double sl, const double riskMoney)
  {
   if(riskMoney <= 0.0)
      return 0.0;
   double pl = 0.0;
   if(!OrderCalcProfit(isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, g_caiSymbol, 1.0, entry, sl, pl))
      return 0.0;
   double lossPerLot = -pl;
   if(!(lossPerLot > 0.0) || !MathIsValidNumber(lossPerLot))
      return 0.0;
   return riskMoney / lossPerLot;
  }
//+------------------------------------------------------------------+
bool CaiMarginOk(const bool isBuy, const double volume, const double price, const double maxUsePct)
  {
   double margin = 0.0;
   if(!OrderCalcMargin(isBuy ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, g_caiSymbol, volume, price, margin))
      return false;
   double freeMargin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   if(!(margin > 0.0) || !(freeMargin > 0.0))
      return false;
   return (margin <= freeMargin * maxUsePct / 100.0);
  }
//+------------------------------------------------------------------+
//| Send ONE market order. Never retried by the EA.                   |
//+------------------------------------------------------------------+
bool CaiOpen(const bool isBuy, const double volume, const double sl, const double tp,
             const string comment, uint &retcode, ulong &order)
  {
   bool sent = isBuy ? g_caiTrade.Buy(volume, g_caiSymbol, 0.0, sl, tp, comment)
                     : g_caiTrade.Sell(volume, g_caiSymbol, 0.0, sl, tp, comment);
   retcode = g_caiTrade.ResultRetcode();
   order   = g_caiTrade.ResultOrder();
   return (sent && (retcode == TRADE_RETCODE_DONE || retcode == TRADE_RETCODE_DONE_PARTIAL));
  }
//+------------------------------------------------------------------+
//| Close all managed positions and VERIFY none remains.              |
//| Closing a specific ticket is idempotent, so the caller may call   |
//| this again on a later tick if it returns false.                   |
//+------------------------------------------------------------------+
bool CaiCloseManaged(uint &lastRetcode)
  {
   lastRetcode = 0;
   ulong tickets[];
   int n = CaiManagedTickets(tickets);
   for(int i = 0; i < n; i++)
     {
      g_caiTrade.PositionClose(tickets[i]);
      lastRetcode = g_caiTrade.ResultRetcode();
     }
   ulong left[];
   return (CaiManagedTickets(left) == 0);
  }
//+------------------------------------------------------------------+
//| Move SL of one managed position; TP is preserved.                 |
//+------------------------------------------------------------------+
bool CaiModifySl(const ulong ticket, const double newSl, const double tp, uint &retcode)
  {
   bool ok = g_caiTrade.PositionModify(ticket, newSl, tp);
   retcode = g_caiTrade.ResultRetcode();
   return (ok && retcode == TRADE_RETCODE_DONE);
  }

#endif // CLAUDEEA_EXECUTION_MQH
