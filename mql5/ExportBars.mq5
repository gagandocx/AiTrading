//+------------------------------------------------------------------+
//| ExportBars.mq5                                                   |
//| Fallback exporter for when the MetaTrader5 Python package is      |
//| inconvenient (e.g. you are not on Windows Python).                |
//|                                                                   |
//| INSTALL                                                           |
//|  1. In MT5: File -> Open Data Folder -> MQL5 -> Scripts           |
//|  2. Copy this file there.                                         |
//|  3. In MetaEditor press F7 to compile.                            |
//|  4. Open a XAUUSD chart on the timeframe you want.                |
//|  5. Press Home and hold it until the chart stops loading older    |
//|     bars -- this forces the terminal to download full history.     |
//|  6. Drag the script onto the chart.                               |
//|                                                                   |
//| OUTPUT: <DataFolder>/MQL5/Files/<SYMBOL>_<TF>.csv                 |
//| Columns: time,open,high,low,close  (exactly what the engine wants)|
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

input int MaxBars = 200000;   // upper bound on bars to export

void OnStart()
{
   string tf   = EnumToString((ENUM_TIMEFRAMES)Period());
   StringReplace(tf, "PERIOD_", "");
   string name = _Symbol + "_" + tf + ".csv";

   int available = Bars(_Symbol, Period());
   if(available <= 1)
   {
      Print("No bars available. Open the chart and press Home to load history.");
      return;
   }
   int count = MathMin(available, MaxBars);

   MqlRates rates[];
   ArraySetAsSeries(rates, false);              // oldest first, as the engine expects
   int copied = CopyRates(_Symbol, Period(), 0, count, rates);
   if(copied <= 0)
   {
      Print("CopyRates failed, error ", GetLastError());
      return;
   }

   int fh = FileOpen(name, FILE_WRITE | FILE_CSV | FILE_ANSI, ',');
   if(fh == INVALID_HANDLE)
   {
      Print("FileOpen failed for ", name, ", error ", GetLastError());
      return;
   }

   FileWrite(fh, "time", "open", "high", "low", "close");
   for(int i = 0; i < copied; i++)
   {
      // Skip malformed bars rather than exporting data that fails validation.
      if(rates[i].low <= 0 || rates[i].high < rates[i].low) continue;
      FileWrite(fh,
                TimeToString(rates[i].time, TIME_DATE | TIME_SECONDS),
                DoubleToString(rates[i].open,  _Digits),
                DoubleToString(rates[i].high,  _Digits),
                DoubleToString(rates[i].low,   _Digits),
                DoubleToString(rates[i].close, _Digits));
   }
   FileClose(fh);

   // Contract and cost details needed to calibrate the cost model.
   double spread_px = (SymbolInfoDouble(_Symbol, SYMBOL_ASK)
                       - SymbolInfoDouble(_Symbol, SYMBOL_BID));
   PrintFormat("Exported %d bars to MQL5/Files/%s", copied, name);
   PrintFormat("contract_size=%.2f digits=%d min_lot=%.2f lot_step=%.2f max_lot=%.2f",
               SymbolInfoDouble(_Symbol, SYMBOL_TRADE_CONTRACT_SIZE),
               (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS),
               SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN),
               SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP),
               SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX));
   PrintFormat("current_spread=%.5f  swap_long=%.4f  swap_short=%.4f",
               spread_px,
               SymbolInfoDouble(_Symbol, SYMBOL_SWAP_LONG),
               SymbolInfoDouble(_Symbol, SYMBOL_SWAP_SHORT));
   Print("Copy the numbers above into data/<SYMBOL>_costs.json");
}
//+------------------------------------------------------------------+
