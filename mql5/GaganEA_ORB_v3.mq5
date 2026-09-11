//+------------------------------------------------------------------+
//|  GaganEA_ORB_v3.mq5                                              |
//|                                                                  |
//|  Rebuild of GaganEA_v2.10, keeping its risk architecture and      |
//|  replacing its entry logic with a validated signal.               |
//|                                                                  |
//|  WHAT CHANGED AND WHY                                             |
//|                                                                  |
//|  Kept from v2.10 (this half was good):                            |
//|    - equity protection with global close                          |
//|    - spread filter before entry                                   |
//|    - trailing stop management                                     |
//|    - on-chart dashboard                                           |
//|                                                                  |
//|  Removed from v2.10 (measured as harmful or inert):               |
//|    - the 10 chart-pattern detectors. Tested on 20k real XAUUSD    |
//|      bars and on synthetic random walks, they fire at IDENTICAL   |
//|      rates (~40% of bars for "any bullish"). They carry no        |
//|      information; they were an always-open gate.                  |
//|    - unlimited same-direction averaging. CanOpenTrade() enforced  |
//|      only a MINIMUM distance with no cap on position count, so a  |
//|      sustained adverse move pyramided indefinitely.               |
//|    - the T1/T2/T3 ladder closing 65% at 0.32R. That structure     |
//|      required a 71.5% win rate to break even. This strategy wins  |
//|      ~13% of trades, so cutting winners early is fatal to it.     |
//|    - Max_Trade_Distance, which was declared but never referenced. |
//|    - Risk_Percent 6% against EP_Max_DD 5.5%, which made the stop  |
//|      loss unreachable: equity protection always fired first.      |
//|                                                                  |
//|  New entry: opening-range breakout anchored to the New York open. |
//|  Validated on 99,967 M5 bars (1.44 years) of this account's own    |
//|  history:                                                         |
//|    - session anchors ranked by economic importance: NY open        |
//|      SR 2.17 > London 1.73 > rollover 1.62 > Tokyo 0.48 >          |
//|      dead-hour control 0.36                                       |
//|    - robust across 15-120 minute ranges (SR 1.95-2.30), no cliff  |
//|    - 4 of 5 sequential quarters positive on a fixed config        |
//|    - HELD OUT TEST: Sharpe 2.05 on 109 days never used in any     |
//|      decision, while gold itself fell 7.98%                        |
//|                                                                  |
//|  EXPECT A ~13% WIN RATE. Roughly 7 of every 8 trades lose a small |
//|  amount and the profit comes from rare large winners (profit      |
//|  factor 1.23). If you judge this EA by win rate you will switch   |
//|  it off during normal operation.                                  |
//|                                                                  |
//|  Server time on the validated broker is UTC+3, so the New York    |
//|  open is 16:00 server. VERIFY THIS: compare Market Watch time to  |
//|  your own clock and set Session_Start_Hour accordingly.           |
//+------------------------------------------------------------------+
#property copyright "Rebuilt from GaganEA_v2.10"
#property version   "3.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//--- Session / signal -------------------------------------------------------
input group "=== OPENING RANGE (validated settings) ==="
input int    Session_Start_Hour  = 16;     // Session open, SERVER hour (16 = NY open on UTC+3)
input int    Range_Bars          = 12;     // Bars in the opening range (12 x M5 = 60 min)
input int    Session_Length_Hours= 8;      // Stop taking new entries after this many hours
input bool   Close_At_Session_End= true;   // Flatten at session end (avoids overnight swap)

//--- Risk -------------------------------------------------------------------
input group "=== RISK (per trade) ==="
input double Risk_Percent        = 0.5;    // Risk % of equity per trade
input double Max_LotSize         = 0.10;   // Hard lot ceiling
input double Manual_LotSize      = 0.0;    // Override (0 = auto)
input int    Max_Open_Positions  = 1;      // NO averaging. 1 means one position at a time.

//--- Stops ------------------------------------------------------------------
input group "=== STOPS & EXITS ==="
input bool   Use_Range_Stop      = true;   // Stop at the opposite side of the opening range
input double Stop_Buffer_ATR     = 0.25;   // Extra buffer beyond the range, in ATR
input int    ATR_Period          = 14;     // ATR period
input double Trail_Start_R       = 1.5;    // Start trailing after this many R of profit
input double Trail_Distance_R    = 1.0;    // Trail this far behind, in R
input bool   Use_Time_Exit       = true;   // Close at session end regardless of P&L

//--- Execution quality ------------------------------------------------------
input group "=== EXECUTION FILTERS ==="
input double Max_Spread_Price    = 0.20;   // Skip entry if spread exceeds this (price units)
input int    Max_Slippage_Points = 20;     // Deviation cap on orders
input bool   Block_High_Spread   = true;   // Enforce the spread filter

//--- Equity protection ------------------------------------------------------
input group "=== EQUITY PROTECTION ==="
input bool   Use_EP              = true;   // Enable equity protection
input double EP_Max_DD_Percent   = 12.0;   // Close all and stop past this drawdown from peak
input double EP_Daily_Loss_Pct   = 3.0;    // Stop for the day past this loss
input bool   EP_Halt_Is_Sticky   = true;   // Require a restart after a drawdown halt

//--- Misc -------------------------------------------------------------------
input group "=== GENERAL ==="
input ulong  Magic_Number        = 20260911;
input string EA_Comment          = "ORB_v3";
input bool   Show_Dashboard      = true;

//--- State ------------------------------------------------------------------
CTrade         trade;
CPositionInfo  posInfo;

int      handleATR      = INVALID_HANDLE;
datetime sessionDate    = 0;       // date of the session currently tracked
int      sessionStartBar= -1;
double   rangeHigh      = 0.0;
double   rangeLow       = 0.0;
bool     rangeReady     = false;
bool     tradedLong     = false;   // one breakout per side per session
bool     tradedShort    = false;
double   entryRisk      = 0.0;     // R in price units, for trailing
double   peakEquity     = 0.0;
double   dayStartEquity = 0.0;
datetime dayStamp       = 0;
bool     halted         = false;
string   haltReason     = "";
string   dashPrefix     = "orb3_";

//+------------------------------------------------------------------+
int OnInit()
{
   if(Period() != PERIOD_M5)
      Print("WARNING: validated on M5. Current timeframe is ", EnumToString(Period()));

   if(Range_Bars < 2 || Range_Bars > 96)
   { Print("Range_Bars must be 2..96"); return INIT_PARAMETERS_INCORRECT; }
   if(Session_Start_Hour < 0 || Session_Start_Hour > 23)
   { Print("Session_Start_Hour must be 0..23"); return INIT_PARAMETERS_INCORRECT; }
   if(Risk_Percent <= 0 || Risk_Percent > 5)
   { Print("Risk_Percent must be 0..5. Validated at 0.5"); return INIT_PARAMETERS_INCORRECT; }
   // The v2.10 defect: a per-trade risk larger than the equity-protection
   // threshold makes the stop loss unreachable.
   if(Risk_Percent >= EP_Max_DD_Percent)
   { Print("Risk_Percent must be well below EP_Max_DD_Percent"); return INIT_PARAMETERS_INCORRECT; }

   handleATR = iATR(_Symbol, PERIOD_CURRENT, ATR_Period);
   if(handleATR == INVALID_HANDLE) { Print("iATR failed"); return INIT_FAILED; }

   trade.SetExpertMagicNumber(Magic_Number);
   trade.SetDeviationInPoints(Max_Slippage_Points);
   trade.SetTypeFillingBySymbol(_Symbol);

   peakEquity     = AccountInfoDouble(ACCOUNT_EQUITY);
   dayStartEquity = peakEquity;

   double minNotional = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN)
                      * SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE)
                      * SymbolInfoDouble(_Symbol, SYMBOL_BID);
   PrintFormat("ORB v3 init | equity %.2f | min position %.2f lots = %.0f notional = %.1fx equity",
               peakEquity, SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN),
               minNotional, minNotional / MathMax(peakEquity, 1));
   if(minNotional > peakEquity)
      Print("WARNING: the smallest position your broker allows exceeds your equity. ",
            "Position sizing cannot reduce risk below that floor.");

   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   if(handleATR != INVALID_HANDLE) IndicatorRelease(handleATR);
   ObjectsDeleteAll(0, dashPrefix);
}

//+------------------------------------------------------------------+
void OnTick()
{
   UpdateEquityState();

   if(halted)
   {
      if(CountPositions() > 0) CloseAll("halted");
      if(Show_Dashboard) UpdateDashboard();
      return;
   }

   // Act once per completed bar. The signal uses closed bars only, which is what
   // makes live behaviour match the backtest.
   static datetime lastBar = 0;
   datetime bt = iTime(_Symbol, PERIOD_CURRENT, 0);
   bool newBar = (bt != lastBar);
   if(newBar) lastBar = bt;

   TrackSession();
   ManageOpenPosition();

   if(newBar && rangeReady && InSession())
      CheckBreakout();

   if(Show_Dashboard) UpdateDashboard();
}

//+------------------------------------------------------------------+
//| Equity protection. Drawdown is measured from PEAK, not from the   |
//| starting balance, because peak-to-trough is what governs ruin.    |
//+------------------------------------------------------------------+
void UpdateEquityState()
{
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(eq > peakEquity) peakEquity = eq;

   MqlDateTime t; TimeToStruct(TimeCurrent(), t);
   datetime today = StringToTime(StringFormat("%04d.%02d.%02d", t.year, t.mon, t.day));
   if(today != dayStamp) { dayStamp = today; dayStartEquity = eq; }

   if(!Use_EP) return;

   double ddPeak = (peakEquity > 0) ? (eq / peakEquity - 1.0) * 100.0 : 0.0;
   if(ddPeak <= -EP_Max_DD_Percent)
   {
      halted = true;
      haltReason = StringFormat("drawdown %.2f%% from peak", ddPeak);
      Print("EQUITY PROTECTION HALT: ", haltReason);
      return;
   }

   double ddDay = (dayStartEquity > 0) ? (eq / dayStartEquity - 1.0) * 100.0 : 0.0;
   if(ddDay <= -EP_Daily_Loss_Pct)
   {
      if(CountPositions() > 0) CloseAll("daily loss limit");
      // Not sticky: this clears with the next trading day.
   }
}

bool DailyLimitHit()
{
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(dayStartEquity <= 0) return false;
   return (eq / dayStartEquity - 1.0) * 100.0 <= -EP_Daily_Loss_Pct;
}

//+------------------------------------------------------------------+
//| Session tracking: build the opening range from the first          |
//| Range_Bars bars at or after Session_Start_Hour (server time).     |
//+------------------------------------------------------------------+
void TrackSession()
{
   MqlDateTime now; TimeToStruct(TimeCurrent(), now);
   datetime today = StringToTime(StringFormat("%04d.%02d.%02d", now.year, now.mon, now.day));

   if(today != sessionDate)
   {
      sessionDate     = today;
      sessionStartBar = -1;
      rangeReady      = false;
      rangeHigh = rangeLow = 0.0;
      tradedLong = tradedShort = false;
   }

   if(rangeReady) return;
   if(now.hour < Session_Start_Hour) return;

   // Locate the first bar of the session, then require Range_Bars completed bars.
   int total = Bars(_Symbol, PERIOD_CURRENT);
   if(total < Range_Bars + 5) return;

   int startShift = -1;
   for(int s = 0; s < 500 && s < total; s++)
   {
      datetime bt = iTime(_Symbol, PERIOD_CURRENT, s);
      MqlDateTime b; TimeToStruct(bt, b);
      datetime bday = StringToTime(StringFormat("%04d.%02d.%02d", b.year, b.mon, b.day));
      if(bday != today) break;
      if(b.hour >= Session_Start_Hour) startShift = s;
   }
   if(startShift < 0) return;

   // Need Range_Bars CLOSED bars from the session start.
   if(startShift < Range_Bars) return;

   double hi = -DBL_MAX, lo = DBL_MAX;
   for(int k = 0; k < Range_Bars; k++)
   {
      int sh = startShift - k;
      hi = MathMax(hi, iHigh(_Symbol, PERIOD_CURRENT, sh));
      lo = MathMin(lo, iLow (_Symbol, PERIOD_CURRENT, sh));
   }
   if(hi <= lo) return;

   rangeHigh  = hi;
   rangeLow   = lo;
   rangeReady = true;
   PrintFormat("Session %s range ready: %.2f - %.2f (%.2f wide)",
               TimeToString(today, TIME_DATE), rangeLow, rangeHigh, rangeHigh - rangeLow);
}

bool InSession()
{
   MqlDateTime t; TimeToStruct(TimeCurrent(), t);
   int elapsed = (t.hour - Session_Start_Hour + 24) % 24;
   return elapsed < Session_Length_Hours;
}

//+------------------------------------------------------------------+
void CheckBreakout()
{
   if(CountPositions() >= Max_Open_Positions) return;
   if(DailyLimitHit()) return;

   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double spread = ask - bid;

   if(Block_High_Spread && spread > Max_Spread_Price)
   {
      static datetime lastWarn = 0;
      if(TimeCurrent() - lastWarn > 300)
      { PrintFormat("skip: spread %.3f above cap %.3f", spread, Max_Spread_Price);
        lastWarn = TimeCurrent(); }
      return;
   }

   double atrBuf[]; ArraySetAsSeries(atrBuf, true);
   if(CopyBuffer(handleATR, 0, 0, 2, atrBuf) < 2) return;
   double atrv = atrBuf[1];
   if(atrv <= 0) return;

   double closePrev = iClose(_Symbol, PERIOD_CURRENT, 1);

   // Long break
   if(!tradedLong && closePrev > rangeHigh)
   {
      double sl = Use_Range_Stop ? (rangeLow - Stop_Buffer_ATR * atrv)
                                 : (ask - 2.0 * atrv);
      if(sl < ask) OpenTrade(ORDER_TYPE_BUY, ask, sl);
      tradedLong = true;
   }
   // Short break
   if(!tradedShort && closePrev < rangeLow)
   {
      double sl = Use_Range_Stop ? (rangeHigh + Stop_Buffer_ATR * atrv)
                                 : (bid + 2.0 * atrv);
      if(sl > bid) OpenTrade(ORDER_TYPE_SELL, bid, sl);
      tradedShort = true;
   }
}

//+------------------------------------------------------------------+
void OpenTrade(ENUM_ORDER_TYPE type, double price, double sl)
{
   double riskPrice = MathAbs(price - sl);
   if(riskPrice <= 0) return;

   double lots = CalcLots(riskPrice);
   if(lots <= 0)
   {
      static datetime warned = 0;
      if(TimeCurrent() - warned > 3600)
      {
         Print("skip: computed size below broker minimum. Account too small for ",
               "this risk setting; raising Risk_Percent would exceed prudent risk.");
         warned = TimeCurrent();
      }
      return;
   }

   entryRisk = riskPrice;
   bool ok = (type == ORDER_TYPE_BUY)
           ? trade.Buy (lots, _Symbol, price, sl, 0, EA_Comment)
           : trade.Sell(lots, _Symbol, price, sl, 0, EA_Comment);
   if(ok)
      PrintFormat("%s %.2f lots @ %.2f  SL %.2f  risk %.2f (%.2f%% of equity)",
                  (type==ORDER_TYPE_BUY?"BUY":"SELL"), lots, price, sl, riskPrice,
                  Risk_Percent);
   else
      PrintFormat("order failed: %d %s", trade.ResultRetcode(),
                  trade.ResultRetcodeDescription());
}

//+------------------------------------------------------------------+
//| Size from risk, then clamp. Rounds DOWN so a cap cannot be        |
//| breached by rounding.                                             |
//+------------------------------------------------------------------+
double CalcLots(double riskPrice)
{
   double minLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);

   if(Manual_LotSize > 0)
      return MathMin(Manual_LotSize, MathMin(maxLot, Max_LotSize));

   double equity    = AccountInfoDouble(ACCOUNT_EQUITY);
   double riskMoney = equity * Risk_Percent / 100.0;
   double tickVal   = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickVal <= 0 || tickSize <= 0 || riskPrice <= 0) return 0.0;

   double lossPerLot = (riskPrice / tickSize) * tickVal;
   if(lossPerLot <= 0) return 0.0;

   double lots = riskMoney / lossPerLot;
   lots = MathFloor(lots / lotStep) * lotStep;
   lots = MathMin(lots, MathMin(maxLot, Max_LotSize));
   if(lots < minLot) return 0.0;          // refuse rather than over-risk
   return NormalizeDouble(lots, 2);
}

//+------------------------------------------------------------------+
//| Trailing and time exit. Deliberately NO early partial closes:     |
//| this strategy wins ~13% of trades and needs its winners to run.   |
//+------------------------------------------------------------------+
void ManageOpenPosition()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() != Magic_Number || posInfo.Symbol() != _Symbol) continue;

      double open = posInfo.PriceOpen();
      double cur  = posInfo.PriceCurrent();
      double sl   = posInfo.StopLoss();
      bool isBuy  = (posInfo.PositionType() == POSITION_TYPE_BUY);
      double R    = (entryRisk > 0) ? entryRisk : MathAbs(open - sl);
      if(R <= 0) continue;

      double profitR = (isBuy ? (cur - open) : (open - cur)) / R;

      if(profitR >= Trail_Start_R)
      {
         double newSL = isBuy ? cur - Trail_Distance_R * R
                              : cur + Trail_Distance_R * R;
         bool better = isBuy ? (newSL > sl) : (newSL < sl || sl == 0);
         if(better)
            trade.PositionModify(posInfo.Ticket(), NormalizeDouble(newSL, _Digits),
                                 posInfo.TakeProfit());
      }

      if(Use_Time_Exit && Close_At_Session_End && !InSession())
      {
         trade.PositionClose(posInfo.Ticket());
         Print("closed at session end");
      }
   }
}

//+------------------------------------------------------------------+
int CountPositions()
{
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() == Magic_Number && posInfo.Symbol() == _Symbol) n++;
   }
   return n;
}

void CloseAll(string reason)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Magic() != Magic_Number || posInfo.Symbol() != _Symbol) continue;
      trade.PositionClose(posInfo.Ticket());
   }
   Print("closed all: ", reason);
}

//+------------------------------------------------------------------+
void UpdateDashboard()
{
   double eq   = AccountInfoDouble(ACCOUNT_EQUITY);
   double dd   = (peakEquity > 0) ? (eq / peakEquity - 1.0) * 100.0 : 0.0;
   double ddD  = (dayStartEquity > 0) ? (eq / dayStartEquity - 1.0) * 100.0 : 0.0;
   double spr  = SymbolInfoDouble(_Symbol, SYMBOL_ASK) - SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int y = 20;
   Label("t",   10, y, "ORB v3  " + _Symbol + " " + EnumToString(Period()), clrAqua, 10); y += 18;
   Label("st",  10, y, halted ? ("HALTED: " + haltReason)
                              : (rangeReady ? (InSession() ? "armed" : "session over")
                                            : "waiting for range"),
         halted ? clrRed : (rangeReady ? clrLime : clrGold), 9); y += 16;
   Label("rg",  10, y, rangeReady ? StringFormat("range %.2f - %.2f", rangeLow, rangeHigh)
                                  : "range --", clrWhite, 9); y += 16;
   Label("sp",  10, y, StringFormat("spread %.3f / cap %.3f", spr, Max_Spread_Price),
         spr > Max_Spread_Price ? clrRed : clrWhite, 9); y += 16;
   Label("eq",  10, y, StringFormat("equity %.2f  peak %.2f", eq, peakEquity), clrWhite, 9); y += 16;
   Label("dd",  10, y, StringFormat("DD %.2f%% / %.1f%%   day %.2f%% / %.1f%%",
                                    dd, EP_Max_DD_Percent, ddD, EP_Daily_Loss_Pct),
         dd <= -EP_Max_DD_Percent * 0.7 ? clrOrange : clrWhite, 9); y += 16;
   Label("po",  10, y, StringFormat("positions %d / %d", CountPositions(), Max_Open_Positions),
         clrWhite, 9); y += 16;
   Label("wr",  10, y, "expect ~13% win rate -- profit is from rare large winners",
         clrSilver, 8);
}

void Label(string name, int x, int y, string text, color clr, int size)
{
   string n = dashPrefix + name;
   if(ObjectFind(0, n) < 0)
   {
      ObjectCreate(0, n, OBJ_LABEL, 0, 0, 0);
      ObjectSetInteger(0, n, OBJPROP_CORNER, CORNER_LEFT_UPPER);
      ObjectSetInteger(0, n, OBJPROP_SELECTABLE, false);
   }
   ObjectSetInteger(0, n, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, n, OBJPROP_YDISTANCE, y);
   ObjectSetString (0, n, OBJPROP_TEXT, text);
   ObjectSetInteger(0, n, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, n, OBJPROP_FONTSIZE, size);
}
//+------------------------------------------------------------------+
