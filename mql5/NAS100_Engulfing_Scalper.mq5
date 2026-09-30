//+------------------------------------------------------------------+
//|                                     NAS100_Engulfing_Scalper.mq5 |
//|                                  Copyright 2026, Ronnie-Axle     |
//|                                             https://github.com   |
//+------------------------------------------------------------------+
#property copyright "Ronnie-Axle"
#property link      "https://github.com"
#property version   "1.00"
#property description "NAS100 5-Minute Engulfing Scalper EA"
#property description "Risks max 10% of account balance, 20% daily drawdown limit,"
#property description "opens 2 trades at start, scales up to 10 orders, 20% profit target per order."

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\AccountInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//--- Input parameters
input group "=== Risk Management ==="
input double   InpMaxTotalRiskPct      = 10.0;     // Max Total Risk (% of balance)
input double   InpProfitTargetPct      = 20.0;     // Profit Target per Order (% of balance)
input double   InpDailyDrawdownPct     = 20.0;     // Max Daily Drawdown Limit (% of start balance)
input int      InpInitialOrders        = 2;        // Initial Orders Count
input int      InpMaxActiveOrders      = 10;       // Max Concurrent Orders

input group "=== Strategy Parameters ==="
input ENUM_TIMEFRAMES InpTimeframe     = PERIOD_M5;// Scalping Timeframe (5-Minute)
input double   InpSLBufferPoints       = 5.0;      // SL Buffer Beyond Candle Extreme (Points)
input double   InpMinSLDistance        = 10.0;     // Minimum SL Distance (Points)
input ulong    InpMagicNumber          = 100500;   // EA Magic Number
input ulong    InpSlippage             = 20;       // Max Slippage (Points)

//--- Global Objects
CTrade         m_trade;
CPositionInfo  m_position;
CAccountInfo   m_account;
CSymbolInfo    m_symbol;

//--- State Tracking
datetime       g_lastBarTime           = 0;
datetime       g_currentDay            = 0;
double         g_dayStartBalance       = 0.0;
bool           g_circuitBreakerTripped = false;
string         g_circuitBreakerReason  = "";

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   if(!m_symbol.Name(_Symbol))
   {
      Print("Error initializing symbol info for ", _Symbol);
      return INIT_FAILED;
   }
   m_symbol.RefreshRates();

   m_trade.SetExpertMagicNumber(InpMagicNumber);
   m_trade.SetDeviationInPoints(InpSlippage);
   m_trade.SetTypeFillingBySymbol(_Symbol);

   // Set initial day baseline
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   g_currentDay = StructToTime(dt);
   g_dayStartBalance = m_account.Balance();
   g_circuitBreakerTripped = false;

   PrintFormat("NAS100 Engulfing Scalper initialized. Day Baseline Balance: $%.2f", g_dayStartBalance);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Comment("");
}

//+------------------------------------------------------------------+
//| Check and reset Daily Drawdown Baseline                          |
//+------------------------------------------------------------------+
void CheckDailyBaseline()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   datetime today = StructToTime(dt);

   if(today != g_currentDay)
   {
      g_currentDay = today;
      g_dayStartBalance = m_account.Balance();
      g_circuitBreakerTripped = false;
      g_circuitBreakerReason = "";
      PrintFormat("New Trading Day: Benchmark balance reset to $%.2f", g_dayStartBalance);
   }
   else if(g_dayStartBalance <= 0.0)
   {
      g_dayStartBalance = m_account.Balance();
   }
}

//+------------------------------------------------------------------+
//| Emergency Liquidate All Open Positions on Drawdown Breach        |
//+------------------------------------------------------------------+
void EmergencyCloseAll()
{
   int closed = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(m_position.SelectByIndex(i))
      {
         if(m_position.Magic() == InpMagicNumber && m_position.Symbol() == _Symbol)
         {
            if(m_trade.PositionClose(m_position.Ticket()))
               closed++;
         }
      }
   }
   PrintFormat("EMERGENCY CLOSE ALL: Liquidated %d positions due to 20%% daily drawdown limit.", closed);
}

//+------------------------------------------------------------------+
//| Check 20% Daily Drawdown Circuit Breaker                         |
//+------------------------------------------------------------------+
bool CheckDailyDrawdownCircuitBreaker()
{
   CheckDailyBaseline();

   double equity = m_account.Equity();
   if(g_dayStartBalance <= 0.0) return false;

   double ddDollars = g_dayStartBalance - equity;
   double ddPercent = (ddDollars / g_dayStartBalance) * 100.0;

   if(ddPercent >= InpDailyDrawdownPct)
   {
      if(!g_circuitBreakerTripped)
      {
         g_circuitBreakerTripped = true;
         g_circuitBreakerReason = StringFormat("Daily DD hit: %.2f%% >= %.1f%% (Start: $%.2f, Equity: $%.2f)",
                                               ddPercent, InpDailyDrawdownPct, g_dayStartBalance, equity);
         Alert("CIRCUIT BREAKER TRIGGERED: ", g_circuitBreakerReason);
         Print(g_circuitBreakerReason);
         EmergencyCloseAll();
      }
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Sum active risk of current open positions                        |
//+------------------------------------------------------------------+
double CalculateActiveRiskUSD()
{
   double totalRisk = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(m_position.SelectByIndex(i))
      {
         if(m_position.Magic() == InpMagicNumber && m_position.Symbol() == _Symbol)
         {
            double openPrice = m_position.PriceOpen();
            double sl = m_position.StopLoss();
            double volume = m_position.Volume();

            if(sl > 0.0)
            {
               double distPoints = MathAbs(openPrice - sl) / _Point;
               double tickValue = m_symbol.TickValue();
               double tickSize = m_symbol.TickSize();
               if(tickSize > 0.0)
                  totalRisk += (distPoints * _Point / tickSize) * tickValue * volume;
            }
            else
            {
               totalRisk += (InpMinSLDistance / m_symbol.TickSize()) * m_symbol.TickValue() * volume;
            }
         }
      }
   }
   return totalRisk;
}

//+------------------------------------------------------------------+
//| Count active bot positions                                       |
//+------------------------------------------------------------------+
int CountActivePositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(m_position.SelectByIndex(i))
      {
         if(m_position.Magic() == InpMagicNumber && m_position.Symbol() == _Symbol)
            count++;
      }
   }
   return count;
}

//+------------------------------------------------------------------+
//| Detect New 5-Minute Bar                                          |
//+------------------------------------------------------------------+
bool IsNewBar()
{
   datetime currentBarTime = (datetime)SeriesInfoInteger(_Symbol, InpTimeframe, SERIES_LASTBAR_DATE);
   if(currentBarTime != g_lastBarTime)
   {
      g_lastBarTime = currentBarTime;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| OnTick Event Handler                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Always check 20% drawdown limit first
   if(CheckDailyDrawdownCircuitBreaker())
   {
      Comment("=== NAS100 SCALPER CIRCUIT BREAKER ACTIVE ===\n" + g_circuitBreakerReason);
      return;
   }

   // Update chart dashboard
   double balance = m_account.Balance();
   double equity = m_account.Equity();
   double ddPct = (g_dayStartBalance > 0) ? ((g_dayStartBalance - equity) / g_dayStartBalance) * 100.0 : 0.0;
   int openCount = CountActivePositions();
   double activeRisk = CalculateActiveRiskUSD();
   double activeRiskPct = (balance > 0) ? (activeRisk / balance) * 100.0 : 0.0;

   string dash = StringFormat(
      "=== NAS100 5M ENGULFING SCALPER ===\n"
      "Balance: $%.2f | Equity: $%.2f\n"
      "Day Start Balance: $%.2f | Daily DD: %.2f%% (Limit: %.1f%%)\n"
      "Active Positions: %d / %d | Total Risk: $%.2f (%.2f%% / Max %.1f%%)\n"
      "Target Profit Per Order: 20%% of Account Balance ($%.2f)",
      balance, equity, g_dayStartBalance, ddPct, InpDailyDrawdownPct,
      openCount, InpMaxActiveOrders, activeRisk, activeRiskPct, InpMaxTotalRiskPct,
      balance * (InpProfitTargetPct / 100.0)
   );
   Comment(dash);

   // Only evaluate entry on a confirmed completed 5-minute candle
   if(!IsNewBar()) return;

   // Check max orders limit (up to 10 orders)
   if(openCount >= InpMaxActiveOrders) return;

   // Get completed candles: rates[1] is last closed bar, rates[2] is prior bar
   MqlRates rates[];
   ArraySetAsSeries(rates, true);
   if(CopyRates(_Symbol, InpTimeframe, 0, 4, rates) < 3) return;

   MqlRates curr = rates[1];
   MqlRates prev = rates[2];

   bool isBullishEngulfing = false;
   bool isBearishEngulfing = false;

   // Bullish Engulfing: prev is bearish, curr is bullish, curr body engulfs prev body
   if(prev.close < prev.open && curr.close > curr.open)
   {
      if(curr.open <= (prev.close + 0.1) && curr.close >= (prev.open - 0.1))
         isBullishEngulfing = true;
   }

   // Bearish Engulfing: prev is bullish, curr is bearish, curr body engulfs prev body
   if(prev.close > prev.open && curr.close < curr.open)
   {
      if(curr.open >= (prev.close - 0.1) && curr.close <= (prev.open + 0.1))
         isBearishEngulfing = true;
   }

   if(!isBullishEngulfing && !isBearishEngulfing) return;

   // Determine order count to open: if initial entry, open InpInitialOrders (2), else fill remaining up to max 10
   int availableSlots = InpMaxActiveOrders - openCount;
   int ordersToOpen = (openCount == 0) ? MathMin(InpInitialOrders, availableSlots) : MathMin(1, availableSlots);
   if(ordersToOpen <= 0) return;

   // Risk budget: Max 10% total risk across all active trades
   double maxAllowableRiskUSD = balance * (InpMaxTotalRiskPct / 100.0);
   double remainingRiskBudgetUSD = maxAllowableRiskUSD - activeRisk;
   if(remainingRiskBudgetUSD <= 0.0)
   {
      PrintFormat("Risk budget exhausted: Active $%.2f >= Max $%.2f", activeRisk, maxAllowableRiskUSD);
      return;
   }

   double riskBudgetPerOrderUSD = remainingRiskBudgetUSD / ordersToOpen;

   // Refresh Symbol info
   m_symbol.RefreshRates();
   double ask = m_symbol.Ask();
   double bid = m_symbol.Bid();
   double tickValue = m_symbol.TickValue();
   double tickSize = m_symbol.TickSize();
   double contractSize = m_symbol.ContractSize();
   double point = m_symbol.Point();

   double entryPrice = 0.0;
   double stopLoss = 0.0;
   double takeProfit = 0.0;
   ENUM_ORDER_TYPE orderType;

   if(isBullishEngulfing)
   {
      orderType = ORDER_TYPE_BUY;
      entryPrice = ask;
      double rawSL = MathMin(curr.low, prev.low) - (InpSLBufferPoints * point);
      double slDist = entryPrice - rawSL;
      if(slDist < InpMinSLDistance * point)
         rawSL = entryPrice - (InpMinSLDistance * point);
      stopLoss = NormalizeDouble(rawSL, _Digits);
   }
   else
   {
      orderType = ORDER_TYPE_SELL;
      entryPrice = bid;
      double rawSL = MathMax(curr.high, prev.high) + (InpSLBufferPoints * point);
      double slDist = rawSL - entryPrice;
      if(slDist < InpMinSLDistance * point)
         rawSL = entryPrice + (InpMinSLDistance * point);
      stopLoss = NormalizeDouble(rawSL, _Digits);
   }

   double slDistancePoints = MathAbs(entryPrice - stopLoss) / point;
   if(slDistancePoints <= 0.0) return;

   // Lot calculation: Risk = Lots * (SL_Distance_Points * Point / TickSize) * TickValue
   double pointCost = (point / tickSize) * tickValue;
   double rawLot = riskBudgetPerOrderUSD / (slDistancePoints * pointCost);

   double lotStep = m_symbol.LotsStep();
   double minLot = m_symbol.LotsMin();
   double maxLot = m_symbol.LotsMax();
   double lot = MathFloor(rawLot / lotStep) * lotStep;
   lot = MathMax(minLot, MathMin(lot, maxLot));

   // Verify total risk will not exceed 10%
   double totalNewRisk = ordersToOpen * (lot * slDistancePoints * pointCost);
   if(activeRisk + totalNewRisk > maxAllowableRiskUSD * 1.05)
   {
      PrintFormat("Calculated lot size %.2f exceeds 10%% risk ceiling. Trade aborted.", lot);
      return;
   }

   // Profit target: 20% of account balance per order
   double targetProfitDollars = balance * (InpProfitTargetPercent / 100.0);
   double tpDistancePoints = targetProfitDollars / (lot * pointCost);

   if(orderType == ORDER_TYPE_BUY)
      takeProfit = NormalizeDouble(entryPrice + (tpDistancePoints * point), _Digits);
   else
      takeProfit = NormalizeDouble(entryPrice - (tpDistancePoints * point), _Digits);

   // Execute the batch of orders (2 orders on initial entry)
   for(int i = 0; i < ordersToOpen; i++)
   {
      string comment = StringFormat("NAS100 #%d/%d %s", i + 1, ordersToOpen, (orderType == ORDER_TYPE_BUY ? "BUY" : "SELL"));
      if(orderType == ORDER_TYPE_BUY)
      {
         m_trade.Buy(lot, _Symbol, ask, stopLoss, takeProfit, comment);
      }
      else
      {
         m_trade.Sell(lot, _Symbol, bid, stopLoss, takeProfit, comment);
      }
   }

   PrintFormat("Executed %d %s orders @ %.2f (Lots: %.2f, SL: %.2f, TP: %.2f, Total Risk: $%.2f <= 10%% balance, TP Target: $%.2f = 20%% balance)",
               ordersToOpen, (orderType == ORDER_TYPE_BUY ? "BUY" : "SELL"), entryPrice, lot, stopLoss, takeProfit, totalNewRisk, targetProfitDollars);
}
//+------------------------------------------------------------------+
