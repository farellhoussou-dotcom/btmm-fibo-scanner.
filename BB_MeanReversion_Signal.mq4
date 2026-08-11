//+------------------------------------------------------------------+
//|            BB_MeanReversion_Signal.mq4                           |
//|                                                                    |
//| INDICATEUR (pas de trading auto). Scanne jusqu'a 20 paires et     |
//| envoie une alerte (fenetre MT4 + notification push + Telegram)    |
//| des qu'une paire declenche un signal de mean-reversion sur les    |
//| Bollinger Bands.                                                  |
//|                                                                    |
//| Parametres issus du backtest GBPUSD H4 2020-2022 :                |
//|   BB Period = 15, Deviation = 2.5, retour a la moyenne a 0.3 std  |
//|                                                                    |
//| Sur le graphique ou il est attache, il dessine aussi les bandes   |
//| de Bollinger pour reference visuelle.                             |
//|                                                                    |
//| Les SL/TP/Lot affiches dans l'alerte sont des SUGGESTIONS          |
//| calculees pour info (risque plafonne a InpMaxRiskUSD) -- aucun    |
//| ordre n'est jamais envoye par ce script.                          |
//+------------------------------------------------------------------+
#property strict
#property copyright "Custom Indicator"
#property version   "1.00"
#property indicator_chart_window
#property indicator_buffers 3
#property indicator_color1 clrDodgerBlue   // upper band
#property indicator_color2 clrGray         // middle band
#property indicator_color3 clrDodgerBlue   // lower band

//--------------------------- INPUTS ----------------------------------

input string InpSymbols =
   "EURUSD,GBPUSD,USDJPY,USDCHF,USDCAD,AUDUSD,NZDUSD,EURGBP,EURJPY,EURCHF,"
   "EURCAD,EURAUD,EURNZD,GBPJPY,GBPCHF,GBPCAD,GBPAUD,GBPNZD,AUDJPY,CHFJPY";
   // 20 paires par defaut. Adapte les noms si ton broker ajoute un suffixe.

input ENUM_TIMEFRAMES InpTimeframe   = PERIOD_H4;  // Timeframe du signal
input int    InpBBPeriod             = 15;         // Periode Bollinger
input double InpBBDeviation          = 2.5;        // Deviation Bollinger
input double InpExitZ                = 0.3;        // Seuil de retour a la moyenne (info, affiche dans l'alerte)

input int    InpScanIntervalSec      = 30;         // Frequence de scan (secondes)
input int    InpMaxSpreadPips        = 4;          // Ignore le signal si spread > ce seuil

input double InpSuggestedRiskUSD     = 140.0;      // Risque $ utilise pour calculer le lot SUGGERE (info only)
input int    InpSuggestedSL_Pips     = 40;         // SL suggere en pips (info only)
input double InpSuggestedRR          = 1.5;        // Ratio TP/SL suggere (info only)

input bool   InpUseTelegram          = true;
input string InpTelegramToken        = "";
input string InpTelegramChatID       = "";
input bool   InpUsePushNotification  = false;      // Notification push MT4 mobile (necessite MetaQuotes ID configure dans Options)
input bool   InpUsePopupAlert        = true;       // Alert() fenetre popup MT4

//--------------------------- BUFFERS ----------------------------------

double BufUpper[];
double BufMid[];
double BufLower[];

//--------------------------- GLOBALS ----------------------------------

string   g_symbols[];
int      g_totalSymbols = 0;
datetime g_lastAlertedBarTime[]; // dernier bar deja alerte, par symbole (evite les doublons)

//+------------------------------------------------------------------+
int OnInit()
{
   SetIndexBuffer(0, BufUpper); SetIndexStyle(0, DRAW_LINE);
   SetIndexBuffer(1, BufMid);   SetIndexStyle(1, DRAW_LINE);
   SetIndexBuffer(2, BufLower); SetIndexStyle(2, DRAW_LINE);
   IndicatorShortName("BB MeanRev Signal (" + IntegerToString(InpBBPeriod) + "," + DoubleToString(InpBBDeviation,1) + ")");

   g_totalSymbols = StringSplit(InpSymbols, ',', g_symbols);
   ArrayResize(g_lastAlertedBarTime, g_totalSymbols);
   for(int i=0; i<g_totalSymbols; i++)
   {
      StringTrimLeft(g_symbols[i]);
      StringTrimRight(g_symbols[i]);
      SymbolSelect(g_symbols[i], true);
      g_lastAlertedBarTime[i] = 0;
   }

   EventSetTimer(InpScanIntervalSec);

   Print("BB_MeanReversion_Signal actif : scan de ", g_totalSymbols, " paires toutes les ", InpScanIntervalSec, "s sur ", EnumToString(InpTimeframe));
   if(InpUseTelegram)
      SendTelegramMessage("Indicateur de signaux demarre : " + IntegerToString(g_totalSymbols) + " paires, scan toutes les " + IntegerToString(InpScanIntervalSec) + "s.");

   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
}

//+------------------------------------------------------------------+
//| Dessine les bandes sur le graphique courant (reference visuelle) |
//+------------------------------------------------------------------+
int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[],
                 const double &open[], const double &high[], const double &low[], const double &close[],
                 const long &tick_volume[], const long &volume[], const int &spread[])
{
   int start = (prev_calculated > 0) ? prev_calculated - 1 : InpBBPeriod;
   for(int i=start; i<rates_total; i++)
   {
      int shift = rates_total - 1 - i;
      BufUpper[i] = iBands(Symbol(), InpTimeframe, InpBBPeriod, InpBBDeviation, 0, PRICE_CLOSE, MODE_UPPER, shift);
      BufMid[i]   = iBands(Symbol(), InpTimeframe, InpBBPeriod, InpBBDeviation, 0, PRICE_CLOSE, MODE_MAIN,  shift);
      BufLower[i] = iBands(Symbol(), InpTimeframe, InpBBPeriod, InpBBDeviation, 0, PRICE_CLOSE, MODE_LOWER, shift);
   }
   return(rates_total);
}

//+------------------------------------------------------------------+
//| Scan periodique de toutes les paires -> alertes uniquement       |
//+------------------------------------------------------------------+
void OnTimer()
{
   for(int i=0; i<g_totalSymbols; i++)
      ScanSymbol(i);
}

//+------------------------------------------------------------------+
double PipSize(string sym)
{
   int digits = (int)MarketInfo(sym, MODE_DIGITS);
   double point = MarketInfo(sym, MODE_POINT);
   if(digits == 3 || digits == 5) return point * 10.0;
   return point;
}

//+------------------------------------------------------------------+
void ScanSymbol(int idx)
{
   string sym = g_symbols[idx];
   if(MarketInfo(sym, MODE_BID) == 0) return; // pas de donnees sur ce symbole

   if(iBars(sym, InpTimeframe) < InpBBPeriod + 5) return;

   datetime bar1Time = iTime(sym, InpTimeframe, 1);
   if(bar1Time == g_lastAlertedBarTime[idx]) return; // deja traite cette bougie -> pas de doublon

   double closeBar1 = iClose(sym, InpTimeframe, 1);
   double upper = iBands(sym, InpTimeframe, InpBBPeriod, InpBBDeviation, 0, PRICE_CLOSE, MODE_UPPER, 1);
   double lower = iBands(sym, InpTimeframe, InpBBPeriod, InpBBDeviation, 0, PRICE_CLOSE, MODE_LOWER, 1);
   double mid   = iBands(sym, InpTimeframe, InpBBPeriod, InpBBDeviation, 0, PRICE_CLOSE, MODE_MAIN,  1);

   double spreadPips = (MarketInfo(sym, MODE_ASK) - MarketInfo(sym, MODE_BID)) / PipSize(sym);

   string direction = "";
   if(closeBar1 < lower)      direction = "ACHAT (rebond attendu depuis la bande basse)";
   else if(closeBar1 > upper) direction = "VENTE (retour attendu depuis la bande haute)";
   else return; // pas de signal sur cette bougie

   g_lastAlertedBarTime[idx] = bar1Time; // marque cette bougie comme traitee, meme si spread filtre le signal

   if(spreadPips > InpMaxSpreadPips)
   {
      Print(sym, " : signal detecte mais spread trop large (", DoubleToString(spreadPips,1), " pips), alerte ignoree.");
      return;
   }

   int digits = (int)MarketInfo(sym, MODE_DIGITS);
   double pip  = PipSize(sym);
   bool isBuy  = (StringFind(direction, "ACHAT") >= 0);
   double entryPrice = isBuy ? MarketInfo(sym, MODE_ASK) : MarketInfo(sym, MODE_BID);
   double suggSL = isBuy ? entryPrice - InpSuggestedSL_Pips*pip : entryPrice + InpSuggestedSL_Pips*pip;
   double suggTP = isBuy ? entryPrice + InpSuggestedSL_Pips*InpSuggestedRR*pip : entryPrice - InpSuggestedSL_Pips*InpSuggestedRR*pip;
   double suggLot = SuggestedLot(sym, InpSuggestedSL_Pips);

   string msg = "SIGNAL " + sym + " (" + EnumToString(InpTimeframe) + ")\n"
              + direction + "\n"
              + "Prix: " + DoubleToString(entryPrice, digits) + "\n"
              + "Bande haute/basse: " + DoubleToString(upper,digits) + " / " + DoubleToString(lower,digits) + "\n"
              + "Moyenne (cible retour): " + DoubleToString(mid, digits) + "\n"
              + "--- suggestions (aucun ordre envoye) ---\n"
              + "SL suggere: " + DoubleToString(suggSL, digits) + " (" + IntegerToString(InpSuggestedSL_Pips) + " pips)\n"
              + "TP suggere: " + DoubleToString(suggTP, digits) + "\n"
              + "Lot suggere pour risque $" + DoubleToString(InpSuggestedRiskUSD,0) + ": " + DoubleToString(suggLot, 2);

   Print(msg);
   if(InpUsePopupAlert) Alert(msg);
   if(InpUsePushNotification) SendNotification(StringSubstr(msg, 0, 255)); // push MT4 limite a 255 caracteres
   if(InpUseTelegram) SendTelegramMessage(msg);
}

//+------------------------------------------------------------------+
//| Calcule un lot suggere pour un risque donne (INFO ONLY)          |
//+------------------------------------------------------------------+
double SuggestedLot(string sym, int slPips)
{
   double tickValue = MarketInfo(sym, MODE_TICKVALUE);
   double tickSize  = MarketInfo(sym, MODE_TICKSIZE);
   if(tickValue <= 0 || tickSize <= 0) return 0.0;

   double slPriceDistance = slPips * PipSize(sym);
   double slTicks = slPriceDistance / tickSize;
   double moneyPerLot = slTicks * tickValue;
   if(moneyPerLot <= 0) return 0.0;

   double lots = InpSuggestedRiskUSD / moneyPerLot;
   double minLot  = MarketInfo(sym, MODE_MINLOT);
   double maxLot  = MarketInfo(sym, MODE_MAXLOT);
   double lotStep = MarketInfo(sym, MODE_LOTSTEP);

   lots = MathFloor(lots / lotStep) * lotStep;
   if(lots < minLot) lots = minLot; // purement indicatif ici, pas d'ordre reel
   if(lots > maxLot) lots = maxLot;

   return NormalizeDouble(lots, 2);
}

//+------------------------------------------------------------------+
string UrlEncode(string text)
{
   string result = "";
   int len = StringLen(text);
   for(int i=0; i<len; i++)
   {
      ushort ch = StringGetCharacter(text, i);
      if((ch>='A'&&ch<='Z')||(ch>='a'&&ch<='z')||(ch>='0'&&ch<='9'))
         result += ShortToString(ch);
      else if(ch==' ')
         result += "%20";
      else if(ch=='\n')
         result += "%0A";
      else
         result += StringFormat("%%%02X", ch);
   }
   return result;
}

//+------------------------------------------------------------------+
int SendTelegramMessage(string message)
{
   if(!InpUseTelegram || InpTelegramToken=="" || InpTelegramChatID=="") return -1;

   string url = "https://api.telegram.org/bot" + InpTelegramToken + "/sendMessage";
   string headers = "Content-Type: application/x-www-form-urlencoded\r\n";
   string postData = "chat_id=" + InpTelegramChatID + "&text=" + UrlEncode(message);

   char post[];
   StringToCharArray(postData, post, 0, StringLen(postData));
   char result[];
   string resultHeaders;

   ResetLastError();
   int res = WebRequest("POST", url, headers, 5000, post, result, resultHeaders);
   if(res == -1)
   {
      int err = GetLastError();
      Print("Erreur Telegram WebRequest: ", err,
            ". Va dans Outils > Options > Expert Advisors et ajoute 'https://api.telegram.org' aux URL autorisees.");
      return -1;
   }
   return res;
}
//+------------------------------------------------------------------+
