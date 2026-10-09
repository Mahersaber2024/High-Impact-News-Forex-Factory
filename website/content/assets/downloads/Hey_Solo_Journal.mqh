#define JRN_SHOTDIR  "shots"
#define JRN_MAXLIVE  128
bool   JournalShots      = true;
string JournalStrategies = "";
string JournalStrategy   = "ICT";
int    JrnShotW = 1920;
int    JrnShotH = 1080;
struct JrnLive
{
   ulong    posId;
   ulong    ticket;
   string   symbol;
   int      type;
   double   volume;
   double   openPrice;
   double   initSL, initTP, curSL;
   datetime openTime;
   double   spreadPts;
   double   riskUsd, riskPct;
   double   plannedRR;
   string   strategy;
   int      trendDir;
   bool     slMoved, beDone, partialDone;
   string   shotOpen;
   string   openTags;
   ulong    magic;
   string   armed;
   string   done;
   double   volSeen;
};
JrnLive  g_jrnLive[];
datetime g_jrnLastPoll   = 0;
bool     g_jrnDirty      = true;
long     g_jrnLogin      = 0;
int      g_jrnStratIndex = 0;
int      g_jrnCount      = 0;
string JrnAccDir()      { return JRN_SHOTDIR + "\\" + IntegerToString(g_jrnLogin); }
string JrnStoreFile()   { return DASHBOARD_DIR + "\\jrn_" + IntegerToString(g_jrnLogin) + ".jsonl"; }
string JrnLiveFile()    { return DASHBOARD_DIR + "\\jrnlive_" + IntegerToString(g_jrnLogin) + ".jsonl"; }
string JrnJsFile()      { return DASHBOARD_DIR + "\\journal_" + IntegerToString(g_jrnLogin) + ".txt"; }
string JrnSetFile()     { return DASHBOARD_DIR + "\\jrnset_" + IntegerToString(g_jrnLogin) + ".txt"; }
string JrnEsc(string s)
{
   StringReplace(s, "\\", "/");
   StringReplace(s, "\"", "'");
   StringReplace(s, "\n", " ");
   StringReplace(s, "\r", " ");
   StringReplace(s, "|", "/");
   return s;
}
int JrnStratList(string &list[])
{
   string raw = JournalStrategies;
   if(StringLen(raw) == 0) raw = "ICT";
   int n = StringSplit(raw, (ushort)',', list);
   for(int i = 0; i < n; i++)
   {
      string one = list[i];
      StringTrimLeft(one); StringTrimRight(one);
      list[i] = JrnEsc(one);
   }
   if(n <= 0) { ArrayResize(list, 1); list[0] = "ICT"; n = 1; }
   return n;
}
int JrnNYMinutes(datetime t)
{
   MqlDateTime d; TimeToStruct(t, d);
   int m = d.hour * 60 + d.min - (TimeOffsetHours * 60);
   if(m < 0)     m += 1440;
   if(m >= 1440) m -= 1440;
   return m;
}
bool JrnInWindow(int m, int startMin, int endMin)
{
   if(startMin == endMin) return false;
   if(startMin <  endMin) return (m >= startMin && m <= endMin);
   return (m >= startMin || m <= endMin);
}
string JrnSessionOf(datetime t)
{
   int m   = JrnNYMinutes(t);
   bool inLN = JrnInWindow(m, StartHourLN * 60 + StartMinuteLN, EndHourLN * 60 + EndMinuteLN);
   bool inNY = JrnInWindow(m, StartHourNY * 60 + StartMinuteNY, EndHourNY * 60 + EndMinuteNY);
   if(inLN && inNY) return "overlap";
   if(inLN)         return "london";
   if(inNY)         return "newyork";
   return "out-of-session";
}
string JrnSessionTag(datetime t)
{
   if(!OutsessionLN && !OutsessionNY) return "";
   int m = JrnNYMinutes(t);
   bool inLN = OutsessionLN && JrnInWindow(m, StartHourLN * 60 + StartMinuteLN, EndHourLN * 60 + EndMinuteLN);
   bool inNY = OutsessionNY && JrnInWindow(m, StartHourNY * 60 + StartMinuteNY, EndHourNY * 60 + EndMinuteNY);
   if(inLN && inNY) return "overlap";
   if(inLN)         return "london";
   if(inNY)         return "newyork";
   return "out-of-session";
}
int JrnWindowLen(int startMin, int endMin)
{
   int d = endMin - startMin;
   if(d < 0) d += 1440;
   return d;
}
int JrnRevengeWindowMin()
{
   if(!TLimitation) return 0;
   if(CooldownMinutes > 0)      return CooldownMinutes;
   if(CloseCooldownMinutes > 0) return CloseCooldownMinutes;
   return 0;
}
int JrnRapidWindowMin()
{
   if(!TLimitation) return 0;
   if(CloseCooldownMinutes > 0) return CloseCooldownMinutes;
   if(CooldownMinutes > 0)      return CooldownMinutes;
   return 0;
}
double JrnPlannedRiskUsd()
{
   if(riskType == FIX_DOLLAR)      return RiskAmount;
   if(riskType == PERCENT_BALANCE)
   {
      double base = AccountInfoDouble(riskBase == RISK_BALANCE ? ACCOUNT_BALANCE : ACCOUNT_EQUITY);
      return (PercentRisk / 100.0) * base;
   }
   return 0.0;
}
int JrnLongHoldMin(datetime t)
{
   int m    = JrnNYMinutes(t);
   int lnS  = StartHourLN * 60 + StartMinuteLN, lnE = EndHourLN * 60 + EndMinuteLN;
   int nyS  = StartHourNY * 60 + StartMinuteNY, nyE = EndHourNY * 60 + EndMinuteNY;
   int best = 0;
   if(OutsessionLN && JrnInWindow(m, lnS, lnE)) best = MathMax(best, JrnWindowLen(lnS, lnE));
   if(OutsessionNY && JrnInWindow(m, nyS, nyE)) best = MathMax(best, JrnWindowLen(nyS, nyE));
   return best;
}
int JrnTrendDir(string symbol, double price)
{
   int h = iMA(symbol, PERIOD_H1, 50, 0, MODE_EMA, PRICE_CLOSE);
   if(h == INVALID_HANDLE) return 0;
   double buf[];
   int got = CopyBuffer(h, 0, 0, 1, buf);
   IndicatorRelease(h);
   if(got < 1) return 0;
   double ema = buf[0];
   if(ema <= 0) return 0;
   if(price > ema) return 1;
   if(price < ema) return -1;
   return 0;
}
bool JrnHasTag(string csv, string tag) { return (StringFind("," + csv + ",", "," + tag + ",") >= 0); }
string JrnAddTag(string csv, string tag)
{
   if(StringLen(tag) == 0) return csv;
   if(JrnHasTag(csv, tag)) return csv;
   return (StringLen(csv) == 0) ? tag : csv + "," + tag;
}
string JrnTagsJson(string csv)
{
   if(StringLen(csv) == 0) return "[]";
   string p[];
   int n = StringSplit(csv, (ushort)',', p);
   string s = "[";
   for(int i = 0; i < n; i++) { if(i > 0) s += ","; s += "\"" + p[i] + "\""; }
   return s + "]";
}
string JrnMergeTags(string a, string b)
{
   if(StringLen(b) == 0) return a;
   string p[];
   int n = StringSplit(b, (ushort)',', p);
   for(int i = 0; i < n; i++) a = JrnAddTag(a, p[i]);
   return a;
}
string JrnRuleTags(string done)
{
   string t = "";
   if(JrnHasTag(done, "tl.cut"))      t = JrnAddTag(t, "risk-cut");
   if(JrnHasTag(done, "tl.cut") || JrnHasTag(done, "tl.streak") || JrnHasTag(done, "tl.caps") ||
      JrnHasTag(done, "tl.session") || JrnHasTag(done, "tl.cooldown") || JrnHasTag(done, "tl.hedge"))
                                      t = JrnAddTag(t, "trade-limits");
   if(JrnHasTag(done, "lp.dloss") || JrnHasTag(done, "lp.wloss") || JrnHasTag(done, "lp.dprofit") ||
      JrnHasTag(done, "lp.target"))   t = JrnAddTag(t, "pnl-limits");
   if(JrnHasTag(done, "lp.close"))    t = JrnAddTag(t, "limit-close");
   if(JrnHasTag(done, "be"))          t = JrnAddTag(t, "break-even");
   if(JrnHasTag(done, "pe1"))         t = JrnAddTag(t, "partial-l1");
   if(JrnHasTag(done, "pe2"))         t = JrnAddTag(t, "partial-l2");
   if(JrnHasTag(done, "pe3"))         t = JrnAddTag(t, "partial-l3");
   if(JrnHasTag(done, "tr1"))         t = JrnAddTag(t, "trail-l1");
   if(JrnHasTag(done, "tr2"))         t = JrnAddTag(t, "trail-l2");
   if(JrnHasTag(done, "tr3"))         t = JrnAddTag(t, "trail-l3");
   if(JrnHasTag(done, "nf"))          t = JrnAddTag(t, "news-filter");
   return t;
}
void JrnSaveSettings()
{
   FolderCreate(DASHBOARD_DIR, FILE_COMMON);
   int h = FileOpen(JrnSetFile(), FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE) return;
   FileWriteString(h, "shots=" + (JournalShots ? "1" : "0") + "\n");
   FileWriteString(h, "strategies=" + JournalStrategies + "\n");
   FileWriteString(h, "strategy=" + JournalStrategy + "\n");
   FileClose(h);
}
void JrnLoadSettings()
{
   if(!FileIsExist(JrnSetFile(), FILE_COMMON)) return;
   int h = FileOpen(JrnSetFile(), FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE) return;
   bool wasOldList = false;
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      int eq = StringFind(line, "=");
      if(eq <= 0) continue;
      string k = StringSubstr(line, 0, eq);
      string v = StringSubstr(line, eq + 1);
      if(k == "shots")           JournalShots = (v == "1");
      else if(k == "strategies")
      {
         if(v == "Unassigned,ICT / Order Block,FVG,Trend Follow,Breakout,Reversal,Scalp,News") { v = "ICT"; wasOldList = true; }
         if(JrnHasTag(v, "Unassigned"))
         {
            string rest = "";
            string parts[];
            int np = StringSplit(v, (ushort)',', parts);
            for(int pi = 0; pi < np; pi++)
            {
               string one = parts[pi];
               StringTrimLeft(one); StringTrimRight(one);
               if(one == "Unassigned") continue;
               rest = JrnAddTag(rest, one);
            }
            v = rest;
         }
         JournalStrategies = v;
      }
      else if(k == "strategy")
      {
         if(wasOldList || v == "Unassigned") v = "ICT";
         JournalStrategy = v;
      }
   }
   FileClose(h);
}
bool JrnMoveToCommon(string src, string dst)
{
   int h = FileOpen(src, FILE_READ | FILE_BIN);
   if(h == INVALID_HANDLE) return false;
   int sz = (int)FileSize(h);
   uchar buf[];
   ArrayResize(buf, sz);
   FileReadArray(h, buf, 0, sz);
   FileClose(h);
   FileDelete(src);
   int h2 = FileOpen(dst, FILE_WRITE | FILE_BIN | FILE_COMMON);
   if(h2 == INVALID_HANDLE) return false;
   FileWriteArray(h2, buf, 0, sz);
   FileClose(h2);
   return true;
}
long JrnChartOf(string symbol)
{
   if(symbol == g_tradeSymbol)
      return ChartID();

   long id = ChartFirst();
   while(id >= 0)
   {
      if(ChartSymbol(id) == symbol) return id;
      id = ChartNext(id);
   }
   return ChartID();
}
string JrnShot(string symbol, ulong posId, string phase)
{
   if(!JournalShots) return "";
   FolderCreate(DASHBOARD_DIR, FILE_COMMON);
   FolderCreate(DASHBOARD_DIR + "\\" + JRN_SHOTDIR, FILE_COMMON);
   FolderCreate(DASHBOARD_DIR + "\\" + JrnAccDir(), FILE_COMMON);
   string rel0 = JrnAccDir() + "\\" + StringFormat("%I64u", posId) + "_" + phase + ".png";
   if(FileIsExist(DASHBOARD_DIR + "\\" + rel0, FILE_COMMON))
   { StringReplace(rel0, "\\", "/"); return rel0; }
   string tmp = "jrn_tmp_" + IntegerToString((int)GetTickCount()) + ".png";
   long   cid = JrnChartOf(symbol);
   ChartSetInteger(cid, CHART_BRING_TO_TOP, true);
   ChartRedraw(cid);
   Sleep(250);
   if(!ChartScreenShot(cid, tmp, JrnShotW, JrnShotH, ALIGN_RIGHT))
   {
      PrintFormat("📔 Journal: screenshot failed for %s (chart %I64d), error=%d", symbol, cid, GetLastError());
      return "";
   }
   string rel = JrnAccDir() + "\\" + StringFormat("%I64u", posId) + "_" + phase + ".png";
   if(!JrnMoveToCommon(tmp, DASHBOARD_DIR + "\\" + rel))
   {
      PrintFormat("📔 Journal: could not store the screenshot, error=%d", GetLastError());
      return "";
   }
   StringReplace(rel, "\\", "/");
   return rel;
}
void JrnLastClose(double &lastNet, datetime &lastTime, string &lastSymbol)
{
   lastNet = 0; lastTime = 0; lastSymbol = "";
   if(!HistorySelect(TimeCurrent() - 86400 * 3, TimeCurrent())) return;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong t = HistoryDealGetTicket(i);
      if(t == 0) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(t, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      int dt = (int)HistoryDealGetInteger(t, DEAL_TYPE);
      if(dt != DEAL_TYPE_BUY && dt != DEAL_TYPE_SELL) continue;
      lastNet    = HistoryDealGetDouble(t, DEAL_PROFIT) + HistoryDealGetDouble(t, DEAL_COMMISSION) + HistoryDealGetDouble(t, DEAL_SWAP);
      lastTime   = (datetime)HistoryDealGetInteger(t, DEAL_TIME);
      lastSymbol = HistoryDealGetString(t, DEAL_SYMBOL);
      return;
   }
}
int JrnLossStreak()
{
   if(!HistorySelect(TimeCurrent() - 86400 * 7, TimeCurrent())) return 0;
   int streak = 0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong t = HistoryDealGetTicket(i);
      if(t == 0) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(t, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      double net = HistoryDealGetDouble(t, DEAL_PROFIT) + HistoryDealGetDouble(t, DEAL_COMMISSION) + HistoryDealGetDouble(t, DEAL_SWAP);
      if(net < 0) streak++;
      else break;
   }
   return streak;
}
int JrnTradesToday()
{
   if(!HistorySelect(GetDayStart(), TimeCurrent())) return 0;
   int n = 0;
   for(int i = 0; i < HistoryDealsTotal(); i++)
   {
      ulong t = HistoryDealGetTicket(i);
      if(t == 0) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(t, DEAL_ENTRY) == DEAL_ENTRY_IN) n++;
   }
   return n;
}
int JrnEntriesWithin(int minutes)
{
   if(!HistorySelect(TimeCurrent() - minutes * 60, TimeCurrent())) return 0;
   int n = 0;
   for(int i = 0; i < HistoryDealsTotal(); i++)
   {
      ulong t = HistoryDealGetTicket(i);
      if(t == 0) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(t, DEAL_ENTRY) == DEAL_ENTRY_IN) n++;
   }
   return n;
}
double JrnAvgVolume(int lookback)
{
   if(!HistorySelect(TimeCurrent() - 86400 * 30, TimeCurrent())) return 0;
   double sum = 0; int n = 0;
   for(int i = HistoryDealsTotal() - 1; i >= 0 && n < lookback; i--)
   {
      ulong t = HistoryDealGetTicket(i);
      if(t == 0) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(t, DEAL_ENTRY) != DEAL_ENTRY_IN) continue;
      sum += HistoryDealGetDouble(t, DEAL_VOLUME);
      n++;
   }
   return (n > 0) ? sum / n : 0;
}
int JrnFindLive(ulong posId)
{
   for(int i = 0; i < ArraySize(g_jrnLive); i++) if(g_jrnLive[i].posId == posId) return i;
   return -1;
}
string JrnLiveToLine(int i)
{
   return StringFormat("%I64u|%I64u|%s|%d|%.2f|%.8f|%.8f|%.8f|%.8f|%I64d|%.1f|%.2f|%.2f|%.2f|%s|%d|%d|%d|%d|%s|%s|%I64u|%s|%s",
      g_jrnLive[i].posId, g_jrnLive[i].ticket, g_jrnLive[i].symbol, g_jrnLive[i].type, g_jrnLive[i].volume,
      g_jrnLive[i].openPrice, g_jrnLive[i].initSL, g_jrnLive[i].initTP, g_jrnLive[i].curSL,
      (long)g_jrnLive[i].openTime, g_jrnLive[i].spreadPts, g_jrnLive[i].riskUsd, g_jrnLive[i].riskPct,
      g_jrnLive[i].plannedRR, g_jrnLive[i].strategy, g_jrnLive[i].trendDir,
      (g_jrnLive[i].slMoved ? 1 : 0), (g_jrnLive[i].beDone ? 1 : 0), (g_jrnLive[i].partialDone ? 1 : 0),
      g_jrnLive[i].shotOpen, g_jrnLive[i].openTags,
      g_jrnLive[i].magic, g_jrnLive[i].armed, g_jrnLive[i].done);
}
void JrnSaveLive()
{
   int h = FileOpen(JrnLiveFile(), FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE) return;
   for(int i = 0; i < ArraySize(g_jrnLive); i++) FileWriteString(h, JrnLiveToLine(i) + "\n");
   FileClose(h);
}
void JrnLoadLive()
{
   ArrayResize(g_jrnLive, 0);
   if(!FileIsExist(JrnLiveFile(), FILE_COMMON)) return;
   int h = FileOpen(JrnLiveFile(), FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE) return;
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      if(StringLen(line) < 5) continue;
      string p[];
      int cnt = StringSplit(line, (ushort)'|', p);
      if(cnt < 21) continue;
      int idx = ArraySize(g_jrnLive);
      ArrayResize(g_jrnLive, idx + 1);
      g_jrnLive[idx].posId       = (ulong)StringToInteger(p[0]);
      g_jrnLive[idx].ticket      = (ulong)StringToInteger(p[1]);
      g_jrnLive[idx].symbol      = p[2];
      g_jrnLive[idx].type        = (int)StringToInteger(p[3]);
      g_jrnLive[idx].volume      = StringToDouble(p[4]);
      g_jrnLive[idx].openPrice   = StringToDouble(p[5]);
      g_jrnLive[idx].initSL      = StringToDouble(p[6]);
      g_jrnLive[idx].initTP      = StringToDouble(p[7]);
      g_jrnLive[idx].curSL       = StringToDouble(p[8]);
      g_jrnLive[idx].openTime    = (datetime)StringToInteger(p[9]);
      g_jrnLive[idx].spreadPts   = StringToDouble(p[10]);
      g_jrnLive[idx].riskUsd     = StringToDouble(p[11]);
      g_jrnLive[idx].riskPct     = StringToDouble(p[12]);
      g_jrnLive[idx].plannedRR   = StringToDouble(p[13]);
      g_jrnLive[idx].strategy    = p[14];
      g_jrnLive[idx].trendDir    = (int)StringToInteger(p[15]);
      g_jrnLive[idx].slMoved     = (StringToInteger(p[16]) == 1);
      g_jrnLive[idx].beDone      = (StringToInteger(p[17]) == 1);
      g_jrnLive[idx].partialDone = (StringToInteger(p[18]) == 1);
      g_jrnLive[idx].shotOpen    = p[19];
      g_jrnLive[idx].openTags    = p[20];
      g_jrnLive[idx].magic       = (cnt > 21) ? (ulong)StringToInteger(p[21]) : 0;
      g_jrnLive[idx].armed       = (cnt > 22) ? p[22] : "";
      g_jrnLive[idx].done        = (cnt > 23) ? p[23] : "";
      g_jrnLive[idx].volSeen     = g_jrnLive[idx].volume;
   }
   FileClose(h);
}
void JrnAppendRecord(string json)
{
   int h = FileOpen(JrnStoreFile(), FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE) { PrintFormat("📔 Journal: cannot open the store, error=%d", GetLastError()); return; }
   FileSeek(h, 0, SEEK_END);
   FileWriteString(h, json + "\n");
   FileClose(h);
   g_jrnDirty = true;
}
int JrnReadRecords(string &lines[])
{
   ArrayResize(lines, 0);
   if(!FileIsExist(JrnStoreFile(), FILE_COMMON)) return 0;
   int h = FileOpen(JrnStoreFile(), FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE) return 0;
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      if(StringLen(line) < 10) continue;
      int n = ArraySize(lines);
      ArrayResize(lines, n + 1);
      lines[n] = line;
   }
   FileClose(h);
   return ArraySize(lines);
}
bool JrnAlreadyLogged(ulong posId)
{
   string lines[];
   int n = JrnReadRecords(lines);
   string needle = "\"ticket\":" + StringFormat("%I64u", posId) + ",";
   for(int i = n - 1; i >= 0 && i >= n - 60; i--) if(StringFind(lines[i], needle) >= 0) return true;
   return false;
}
string JrnOpenJson()
{
   string rows = "";
   for(int i = 0; i < ArraySize(g_jrnLive); i++)
   {
      if(!PositionSelectByTicket(g_jrnLive[i].ticket)) continue;
      double profit = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      if(StringLen(rows) > 0) rows += ",\n";
      rows += StringFormat("    {\"ticket\":%I64u,\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.2f,\"openPrice\":%.5f,"
                           "\"sl\":%.5f,\"tp\":%.5f,\"openTime\":\"%s\",\"strategy\":\"%s\",\"riskUsd\":%.2f,\"riskPct\":%.2f,"
                           "\"plannedRR\":%.2f,\"floating\":%.2f,\"shotOpen\":\"%s\",\"tags\":%s,"
                           "\"rulesArmed\":%s,\"rulesDone\":%s}",
         g_jrnLive[i].posId, g_jrnLive[i].symbol, (g_jrnLive[i].type == 0 ? "BUY" : "SELL"), g_jrnLive[i].volume,
         g_jrnLive[i].openPrice, g_jrnLive[i].curSL, g_jrnLive[i].initTP,
         TimeToString(g_jrnLive[i].openTime, TIME_DATE | TIME_SECONDS), g_jrnLive[i].strategy,
         g_jrnLive[i].riskUsd, g_jrnLive[i].riskPct, g_jrnLive[i].plannedRR, profit,
         g_jrnLive[i].shotOpen, JrnTagsJson(JrnMergeTags(g_jrnLive[i].openTags, JrnRuleTags(g_jrnLive[i].done))),
         JrnTagsJson(g_jrnLive[i].armed), JrnTagsJson(g_jrnLive[i].done));
   }
   return "[\n" + rows + "\n  ]";
}
void JrnExportJs()
{
   FolderCreate(DASHBOARD_DIR, FILE_COMMON);
   string lines[];
   int n = JrnReadRecords(lines);
   g_jrnCount = n;
   int start = 0;
   string strat[];
   int sn = JrnStratList(strat);
   string stratJs = "[";
   for(int i = 0; i < sn; i++) { if(i > 0) stratJs += ","; stratJs += "\"" + strat[i] + "\""; }
   stratJs += "]";
   string js = "window.JOURNAL_DATA = {\n";
   js += StringFormat("  login:%I64d,\n", g_jrnLogin);
   js += "  lastUpdate:\"" + TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS) + "\",\n";
   js += "  strategies:" + stratJs + ",\n";
   js += "  activeStrategy:\"" + JrnEsc(JournalStrategy) + "\",\n";
   js += "  open:" + JrnOpenJson() + ",\n";
   js += "  trades:[\n";
   for(int i = n - 1; i >= start; i--)
   {
      js += "    " + lines[i];
      if(i > start) js += ",";
      js += "\n";
   }
   js += "  ]\n};\n";
   int h = FileOpen(JrnJsFile(), FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE) { PrintFormat("📔 Journal: cannot write %s, error=%d", JrnJsFile(), GetLastError()); return; }
   FileWriteString(h, js);
   FileClose(h);
   g_jrnDirty = false;
}
datetime g_jrnLimitAt = 0;
void JrnNoteLimit() { g_jrnLimitAt = TimeCurrent(); }
bool JrnPeLevelOn(int lv)
{
   if(lv == 1) return (PartialExitLevel1 > 0.0 && PartialExitPercent1 > 0.0);
   if(lv == 2) return (PartialExitLevel2 > 0.0 && PartialExitPercent2 > 0.0);
   if(lv == 3) return (PartialExitLevel3 > 0.0 && PartialExitPercent3 > 0.0);
   return false;
}
bool JrnTrLevelOn(int lv)
{
   if(lv == 1) return (TrailingLevel1 > 0.0 && TrailingPut1 > 0.0);
   if(lv == 2) return (TrailingLevel2 > 0.0 && TrailingPut2 > 0.0);
   if(lv == 3) return (TrailingLevel3 > 0.0 && TrailingPut3 > 0.0);
   return false;
}
void JrnRuleArm(string &armed, string &done, string key, bool tick)
{
   armed = JrnAddTag(armed, key);
   if(tick) done = JrnAddTag(done, key);
}
void JrnMarkDone(int idx, string key)
{
   g_jrnLive[idx].armed = JrnAddTag(g_jrnLive[idx].armed, key);
   g_jrnLive[idx].done  = JrnAddTag(g_jrnLive[idx].done, key);
}
void JrnRulesAtEntry(ulong magic, string symbol, datetime otime, string &armed, string &done)
{
   armed = "";
   done  = "";
   bool viaExpert = (magic != 0);
   if(TLimitation)
   {
      if(MaxlosingSL > 0 && CutRick > 0)
         JrnRuleArm(armed, done, "tl.cut", viaExpert && reduceRisk);
      if(Consecutivelosing > 0 || MaxDailySLCount > 0)
         JrnRuleArm(armed, done, "tl.streak", viaExpert && !noTradingAllowed);
      if(MaxOpenTrades > 0 || MaxOpenTradesPerSymbol > 0 || MaxDailyTrades > 0 || MaxTradesPerSymbol > 0)
         JrnRuleArm(armed, done, "tl.caps", viaExpert);
      if(AllowLN > 0 && AllowNY > 0)
         JrnRuleArm(armed, done, "tl.session", viaExpert);
      if(CooldownMinutes > 0 || CloseCooldownMinutes > 0)
         JrnRuleArm(armed, done, "tl.cooldown", viaExpert);
      if(DisableHedge)
         JrnRuleArm(armed, done, "tl.hedge", viaExpert);
   }
   if(Limitations)
   {
      if(MaxDailyLossValue > 0)    JrnRuleArm(armed, done, "lp.dloss",   viaExpert);
      if(MaxWeeklyLossValue > 0)   JrnRuleArm(armed, done, "lp.wloss",   viaExpert);
      if(MaxDailyProfitValue > 0)  JrnRuleArm(armed, done, "lp.dprofit", viaExpert);
      if(ChalChallengepassed > 0)  JrnRuleArm(armed, done, "lp.target",  viaExpert);
      if(AutoCloseOnLimit)         JrnRuleArm(armed, done, "lp.close",   false);
   }
   if(EnableBreakeven)
      JrnRuleArm(armed, done, "be", false);
   if(EnablePartialExit)
      for(int lv = 1; lv <= 3; lv++)
         if(JrnPeLevelOn(lv)) JrnRuleArm(armed, done, "pe" + IntegerToString(lv), false);
   if(Trailing)
      for(int lv = 1; lv <= 3; lv++)
         if(JrnTrLevelOn(lv)) JrnRuleArm(armed, done, "tr" + IntegerToString(lv), false);
   if(EnableNewsCheck)
      JrnRuleArm(armed, done, "nf", viaExpert && !IsNewsTradeTime(otime, symbol));
}
int JrnEaPartialDeals(ulong posId, bool closed)
{
   if(!HistorySelectByPosition((long)posId)) return 0;
   int  total = HistoryDealsTotal();
   int  outs = 0, ea = 0;
   bool lastIsEa = false;
   for(int i = 0; i < total; i++)
   {
      ulong t = HistoryDealGetTicket(i);
      if(t == 0) continue;
      if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(t, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      outs++;
      lastIsEa = ((ENUM_DEAL_REASON)HistoryDealGetInteger(t, DEAL_REASON) == DEAL_REASON_EXPERT);
      if(lastIsEa) ea++;
   }
   if(closed && outs > 0 && lastIsEa) ea--;
   return ea;
}
void JrnTickPartials(int idx, bool closed)
{
   if(!JrnHasTag(g_jrnLive[idx].armed, "pe1") && !JrnHasTag(g_jrnLive[idx].armed, "pe2") &&
      !JrnHasTag(g_jrnLive[idx].armed, "pe3")) return;
   int n = JrnEaPartialDeals(g_jrnLive[idx].posId, closed);
   int k = 0;
   for(int lv = 1; lv <= 3 && k < n; lv++)
   {
      if(!JrnHasTag(g_jrnLive[idx].armed, "pe" + IntegerToString(lv))) continue;
      JrnMarkDone(idx, "pe" + IntegerToString(lv));
      k++;
   }
}
bool JrnRulesTrack(int idx)
{
   string before = g_jrnLive[idx].done;
   ulong  magic  = g_jrnLive[idx].magic;
   if(JrnHasTag(g_jrnLive[idx].armed, "be") && g_jrnLive[idx].beDone)
   {
      int nb = MathMin(ArraySize(activeBreakevenStops), ArraySize(breakevenApplied));
      for(int i = 0; i < nb; i++)
         if(activeBreakevenStops[i] == magic)
         {
            if(breakevenApplied[i]) JrnMarkDone(idx, "be");
            break;
         }
   }
   double sl = g_jrnLive[idx].curSL, sl0 = g_jrnLive[idx].initSL;
   bool stopBetter = (sl > 0) && ((g_jrnLive[idx].type == 0) ? (sl > sl0) : (sl0 <= 0 || sl < sl0));
   if(stopBetter && (JrnHasTag(g_jrnLive[idx].armed, "tr1") || JrnHasTag(g_jrnLive[idx].armed, "tr2") ||
                     JrnHasTag(g_jrnLive[idx].armed, "tr3")))
   {
      int nt = ArraySize(activeTrailingStops);
      for(int i = 0; i < nt; i++)
      {
         if(activeTrailingStops[i] != magic) continue;
         if(i < ArraySize(trailingAppliedLevel1) && trailingAppliedLevel1[i] && JrnTrLevelOn(1)) JrnMarkDone(idx, "tr1");
         if(i < ArraySize(trailingAppliedLevel2) && trailingAppliedLevel2[i] && JrnTrLevelOn(2)) JrnMarkDone(idx, "tr2");
         if(i < ArraySize(trailingAppliedLevel3) && trailingAppliedLevel3[i] && JrnTrLevelOn(3)) JrnMarkDone(idx, "tr3");
         break;
      }
   }
   return (before != g_jrnLive[idx].done);
}
void JrnOnOpen(ulong ticket)
{
   if(!PositionSelectByTicket(ticket)) return;
   ulong posId = (ulong)PositionGetInteger(POSITION_IDENTIFIER);
   int idx = ArraySize(g_jrnLive);
   if(idx >= JRN_MAXLIVE) return;
   ArrayResize(g_jrnLive, idx + 1);
   string symbol  = PositionGetString(POSITION_SYMBOL);
   int    type    = (int)PositionGetInteger(POSITION_TYPE);
   double vol     = PositionGetDouble(POSITION_VOLUME);
   double price   = PositionGetDouble(POSITION_PRICE_OPEN);
   double sl      = PositionGetDouble(POSITION_SL);
   double tp      = PositionGetDouble(POSITION_TP);
   datetime otime = (datetime)PositionGetInteger(POSITION_TIME);
   ulong  magic   = (ulong)PositionGetInteger(POSITION_MAGIC);
   double point   = SymbolInfoDouble(symbol, SYMBOL_POINT);
   double spread  = (double)SymbolInfoInteger(symbol, SYMBOL_SPREAD);
   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double riskUsd = 0.0;
   if(sl > 0 && point > 0)
   {
      double tickVal = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_VALUE);
      double tickSz  = SymbolInfoDouble(symbol, SYMBOL_TRADE_TICK_SIZE);
      if(tickSz > 0) riskUsd = MathAbs(price - sl) / tickSz * tickVal * vol;
   }
   double riskPct = (balance > 0) ? (riskUsd / balance) * 100.0 : 0.0;
   double plannedRR = 0.0;
   if(sl > 0 && tp > 0 && MathAbs(price - sl) > 0) plannedRR = MathAbs(tp - price) / MathAbs(price - sl);
   string tags = JrnAddTag("", JrnSessionTag(otime));
   if(IsNewsTradeTime(otime, symbol)) tags = JrnAddTag(tags, "news");
   if(sl <= 0)                tags = JrnAddTag(tags, "no-sl");
   if(tp <= 0)                tags = JrnAddTag(tags, "no-tp");
   if(plannedRR > 0 && plannedRR < 1.0) tags = JrnAddTag(tags, "low-rr");
   if(plannedRR >= 2.0)                 tags = JrnAddTag(tags, "good-rr");
   double riskCap = JrnPlannedRiskUsd();
   double lossCap = (Limitations && MaxDailyLossValue > 0)
                    ? ((LimitationType == DOLLAR) ? MaxDailyLossValue
                                                  : (MaxDailyLossValue / 100.0) * balance)
                    : 0.0;
   if(riskCap > 0)
   {
      if(riskUsd > riskCap * 1.05) tags = JrnAddTag(tags, "over-risk");
   }
   else if(lossCap > 0)
   {
      if(riskUsd > lossCap) tags = JrnAddTag(tags, "over-risk");
   }
   if(sl > 0 && point > 0)
   {
      double slPts = MathAbs(price - sl) / point;
      if(slPts > 0 && spread / slPts > 0.10) tags = JrnAddTag(tags, "wide-spread");
   }
   MqlDateTime dt; TimeToStruct(otime, dt);
   if(dt.hour >= 22 || dt.hour < 3)         tags = JrnAddTag(tags, "late-night");
   if(dt.day_of_week == 5 && dt.hour >= 19) tags = JrnAddTag(tags, "friday-late");
   int trend = JrnTrendDir(symbol, price);
   if(trend != 0)
   {
      bool withTrend = ((type == 0 && trend > 0) || (type == 1 && trend < 0));
      if(!withTrend) tags = JrnAddTag(tags, "counter-trend");
   }
   int revWin   = JrnRevengeWindowMin();
   int rapidWin = JrnRapidWindowMin();
   bool afterLoss = false;
   if(revWin > 0)
   {
      double   lastNet; datetime lastTime; string lastSym;
      JrnLastClose(lastNet, lastTime, lastSym);
      if(lastNet < 0 && lastTime > 0 && (otime - lastTime) <= revWin * 60)
      {
         tags = JrnAddTag(tags, "revenge");
         afterLoss = true;
      }
   }
   if(rapidWin > 0)
   {
      if(JrnEntriesWithin(rapidWin) >= 3) tags = JrnAddTag(tags, "rapid-fire");
   }
   if(TLimitation && MaxDailyTrades > 0)
   {
      if(JrnTradesToday() > MaxDailyTrades) tags = JrnAddTag(tags, "overtrading");
   }
   if(JrnLossStreak() >= 3)               tags = JrnAddTag(tags, "tilt-streak");
   double avgVol = JrnAvgVolume(10);
   if(avgVol > 0 && vol >= avgVol * 1.8) tags = JrnAddTag(tags, "size-spike");
   for(int i = 0; i < ArraySize(g_jrnLive); i++)
   {
      if(g_jrnLive[i].ticket == ticket) continue;
      if(g_jrnLive[i].symbol != symbol) continue;
      if(!PositionSelectByTicket(g_jrnLive[i].ticket)) continue;
      double other = PositionGetDouble(POSITION_PROFIT);
      int    otype = (int)PositionGetInteger(POSITION_TYPE);
      if(otype != type)  tags = JrnAddTag(tags, "hedge");
      else if(other < 0) tags = JrnAddTag(tags, "add-to-loser");
   }
   if(JrnHasTag(tags, "revenge") || JrnHasTag(tags, "rapid-fire") ||
      JrnHasTag(tags, "tilt-streak") || (JrnHasTag(tags, "size-spike") && afterLoss) ||
      (JrnHasTag(tags, "no-sl") && JrnHasTag(tags, "over-risk")))
      tags = JrnAddTag(tags, "impulse");
   g_jrnLive[idx].posId       = posId;
   g_jrnLive[idx].ticket      = ticket;
   g_jrnLive[idx].symbol      = symbol;
   g_jrnLive[idx].type        = type;
   g_jrnLive[idx].volume      = vol;
   g_jrnLive[idx].openPrice   = price;
   g_jrnLive[idx].initSL      = sl;
   g_jrnLive[idx].initTP      = tp;
   g_jrnLive[idx].curSL       = sl;
   g_jrnLive[idx].openTime    = otime;
   g_jrnLive[idx].spreadPts   = spread;
   g_jrnLive[idx].riskUsd     = riskUsd;
   g_jrnLive[idx].riskPct     = riskPct;
   g_jrnLive[idx].plannedRR   = plannedRR;
   g_jrnLive[idx].strategy    = JrnEsc(JournalStrategy);
   g_jrnLive[idx].trendDir    = trend;
   g_jrnLive[idx].slMoved     = false;
   g_jrnLive[idx].beDone      = false;
   g_jrnLive[idx].partialDone = false;
   g_jrnLive[idx].openTags    = tags;
   g_jrnLive[idx].magic       = magic;
   g_jrnLive[idx].volSeen     = vol;
   string ruleArmed = "", ruleDone = "";
   JrnRulesAtEntry(magic, symbol, otime, ruleArmed, ruleDone);
   if(StringLen(ruleArmed) == 0) ruleArmed = "-";
   g_jrnLive[idx].armed       = ruleArmed;
   g_jrnLive[idx].done        = ruleDone;
   g_jrnLive[idx].openTags    = JrnMergeTags(g_jrnLive[idx].openTags, JrnRuleTags(ruleDone));
   g_jrnLive[idx].shotOpen    = JrnShot(symbol, posId, "open");
   JrnSaveLive();
   g_jrnDirty = true;
}
void JrnOnClose(int liveIdx)
{
   ulong  posId  = g_jrnLive[liveIdx].posId;
   string symbol = g_jrnLive[liveIdx].symbol;
   double net = 0, commission = 0, swap = 0, closePrice = 0;
   datetime closeTime = 0;
   int outDeals = 0;
   string closeMethod = "manual";
   if(HistorySelect(g_jrnLive[liveIdx].openTime - 60, TimeCurrent() + 60))
   {
      for(int i = 0; i < HistoryDealsTotal(); i++)
      {
         ulong t = HistoryDealGetTicket(i);
         if(t == 0) continue;
         if((long)HistoryDealGetInteger(t, DEAL_POSITION_ID) != (long)posId) continue;
         if((ENUM_DEAL_ENTRY)HistoryDealGetInteger(t, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
         net        += HistoryDealGetDouble(t, DEAL_PROFIT);
         commission += HistoryDealGetDouble(t, DEAL_COMMISSION);
         swap       += HistoryDealGetDouble(t, DEAL_SWAP);
         closePrice  = HistoryDealGetDouble(t, DEAL_PRICE);
         closeTime   = (datetime)HistoryDealGetInteger(t, DEAL_TIME);
         ulong mg    = (ulong)HistoryDealGetInteger(t, DEAL_MAGIC);
         int   rs    = (int)HistoryDealGetInteger(t, DEAL_REASON);
         closeMethod = OpenMethodKey(rs, mg);
         outDeals++;
      }
   }
   if(closeTime == 0) closeTime = TimeCurrent();
   double netTotal = net + commission + swap;
   JrnTickPartials(liveIdx, true);
   JrnRulesTrack(liveIdx);
   if(JrnHasTag(g_jrnLive[liveIdx].armed, "lp.close") && g_jrnLimitAt > 0 &&
      MathAbs((long)closeTime - (long)g_jrnLimitAt) <= 30)
      JrnMarkDone(liveIdx, "lp.close");
   string shotClose = JrnShot(symbol, posId, "close");
   string tags = JrnMergeTags(g_jrnLive[liveIdx].openTags, JrnRuleTags(g_jrnLive[liveIdx].done));
   tags = JrnAddTag(tags, (netTotal > 0.10 ? "win" : (netTotal < -0.10 ? "loss" : "breakeven")));
   int durMin = (int)((closeTime - g_jrnLive[liveIdx].openTime) / 60);
   if(durMin < 1)                   tags = JrnAddTag(tags, "scalp");
   else if(durMin < 5)              tags = JrnAddTag(tags, "quick");
   int holdLimit = JrnLongHoldMin(g_jrnLive[liveIdx].openTime);
   if(holdLimit > 0 && durMin > holdLimit) tags = JrnAddTag(tags, "long-hold");
   MqlDateTime dOpen, dClose;
   TimeToStruct(g_jrnLive[liveIdx].openTime, dOpen);
   TimeToStruct(closeTime, dClose);
   if(dOpen.day != dClose.day) tags = JrnAddTag(tags, "overnight");
   if(outDeals > 1 || g_jrnLive[liveIdx].partialDone) tags = JrnAddTag(tags, "partial");
   if(g_jrnLive[liveIdx].slMoved)                     tags = JrnAddTag(tags, "sl-moved");
   if(g_jrnLive[liveIdx].beDone)                      tags = JrnAddTag(tags, "moved-to-be");
   double dg = SymbolInfoDouble(symbol, SYMBOL_POINT) * 12;
   string exitReason = "manual-exit";
   if(g_jrnLive[liveIdx].initTP > 0 && MathAbs(closePrice - g_jrnLive[liveIdx].initTP) <= dg) exitReason = "tp-hit";
   else if(g_jrnLive[liveIdx].curSL > 0 && MathAbs(closePrice - g_jrnLive[liveIdx].curSL) <= dg)
      exitReason = (netTotal > 0 ? "trailing-exit" : (g_jrnLive[liveIdx].beDone ? "be-exit" : "sl-hit"));
   else if(closeMethod == "expert") exitReason = "auto-exit";
   tags = JrnAddTag(tags, exitReason);
   double r = (g_jrnLive[liveIdx].riskUsd > 0) ? netTotal / g_jrnLive[liveIdx].riskUsd : 0.0;
   if(g_jrnLive[liveIdx].riskUsd > 0)
   {
      if(r >= 2.0)               tags = JrnAddTag(tags, "big-win");
      if(r <= -0.95 && r > -1.3) tags = JrnAddTag(tags, "full-loss");
      if(r < -1.3)               tags = JrnAddTag(tags, "beyond-sl");
      if(r > 0 && r < 0.3 && exitReason == "manual-exit") tags = JrnAddTag(tags, "cut-early");
      if(r >= 1.0 && exitReason == "tp-hit")              tags = JrnAddTag(tags, "plan-followed");
   }
   string json = StringFormat(
      "{\"ticket\":%I64u,\"symbol\":\"%s\",\"type\":\"%s\",\"volume\":%.2f,\"openPrice\":%.5f,\"closePrice\":%.5f,"
      "\"sl\":%.5f,\"tp\":%.5f,\"slFinal\":%.5f,\"openTime\":\"%s\",\"closeTime\":\"%s\",\"durationMin\":%d,"
      "\"net\":%.2f,\"commission\":%.2f,\"swap\":%.2f,\"riskUsd\":%.2f,\"riskPct\":%.2f,\"r\":%.2f,\"plannedRR\":%.2f,"
      "\"spreadPts\":%.1f,\"strategy\":\"%s\",\"session\":\"%s\",\"exit\":\"%s\",\"closedBy\":\"%s\","
      "\"shotOpen\":\"%s\",\"shotClose\":\"%s\",\"tags\":%s,"
      "\"rulesArmed\":%s,\"rulesDone\":%s}",
      posId, symbol, (g_jrnLive[liveIdx].type == 0 ? "BUY" : "SELL"), g_jrnLive[liveIdx].volume,
      g_jrnLive[liveIdx].openPrice, closePrice,
      g_jrnLive[liveIdx].initSL, g_jrnLive[liveIdx].initTP, g_jrnLive[liveIdx].curSL,
      TimeToString(g_jrnLive[liveIdx].openTime, TIME_DATE | TIME_SECONDS),
      TimeToString(closeTime, TIME_DATE | TIME_SECONDS), durMin,
      netTotal, commission, swap, g_jrnLive[liveIdx].riskUsd, g_jrnLive[liveIdx].riskPct, r,
      g_jrnLive[liveIdx].plannedRR, g_jrnLive[liveIdx].spreadPts,
      g_jrnLive[liveIdx].strategy, JrnSessionOf(g_jrnLive[liveIdx].openTime), exitReason, closeMethod,
      g_jrnLive[liveIdx].shotOpen, shotClose, JrnTagsJson(tags),
      JrnTagsJson(g_jrnLive[liveIdx].armed), JrnTagsJson(g_jrnLive[liveIdx].done));
   if(!JrnAlreadyLogged(posId)) JrnAppendRecord(json);
}
void JrnPoll()
{
   if(!JournalEnable) return;
   if(TimeCurrent() - g_jrnLastPoll < 2) return;
   g_jrnLastPoll = TimeCurrent();
   bool liveChanged = false;
   int total = PositionsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(!PositionSelectByTicket(ticket)) continue;
      ulong posId = (ulong)PositionGetInteger(POSITION_IDENTIFIER);
      int idx = JrnFindLive(posId);
      if(idx < 0) { JrnOnOpen(ticket); liveChanged = true; continue; }
      double sl  = PositionGetDouble(POSITION_SL);
      double vol = PositionGetDouble(POSITION_VOLUME);
      if(MathAbs(sl - g_jrnLive[idx].curSL) > SymbolInfoDouble(g_jrnLive[idx].symbol, SYMBOL_POINT))
      {
         g_jrnLive[idx].curSL   = sl;
         g_jrnLive[idx].slMoved = true;
         double entry = g_jrnLive[idx].openPrice;
         double tol   = SymbolInfoDouble(g_jrnLive[idx].symbol, SYMBOL_POINT) * 30;
         bool profitSide = (g_jrnLive[idx].type == 0) ? (sl >= entry - tol) : (sl <= entry + tol);
         if(sl > 0 && profitSide) g_jrnLive[idx].beDone = true;
         liveChanged = true;
      }
      if(vol < g_jrnLive[idx].volume - 0.000001 && !g_jrnLive[idx].partialDone)
      {
         g_jrnLive[idx].partialDone = true;
         liveChanged = true;
      }
      if(vol < g_jrnLive[idx].volSeen - 0.000001)
      {
         g_jrnLive[idx].volSeen = vol;
         string doneBefore = g_jrnLive[idx].done;
         JrnTickPartials(idx, false);
         if(doneBefore != g_jrnLive[idx].done) liveChanged = true;
      }
      if(JrnRulesTrack(idx)) liveChanged = true;
   }
   for(int i = ArraySize(g_jrnLive) - 1; i >= 0; i--)
   {
      if(PositionSelectByTicket(g_jrnLive[i].ticket)) continue;
      JrnOnClose(i);
      for(int j = i; j < ArraySize(g_jrnLive) - 1; j++) g_jrnLive[j] = g_jrnLive[j + 1];
      ArrayResize(g_jrnLive, ArraySize(g_jrnLive) - 1);
      liveChanged = true;
   }
   if(liveChanged) JrnSaveLive();
   if(liveChanged || g_jrnDirty) { JrnExportJs(); JrnPanelRefresh(); }
}
void JrnInit()
{
   g_jrnLogin = AccountInfoInteger(ACCOUNT_LOGIN);
   JrnLoadSettings();
   JournalStrategies = JrnAddTag(JournalStrategies, "ICT");
   string list[];
   int n = JrnStratList(list);
   if(StringLen(JournalStrategy) == 0) JournalStrategy = list[0];
   g_jrnStratIndex = 0;
   for(int i = 0; i < n; i++) if(list[i] == JournalStrategy) { g_jrnStratIndex = i; break; }
   if(!JournalEnable) return;
   FolderCreate(DASHBOARD_DIR, FILE_COMMON);
   FolderCreate(DASHBOARD_DIR + "\\" + JRN_SHOTDIR, FILE_COMMON);
   FolderCreate(DASHBOARD_DIR + "\\" + JrnAccDir(), FILE_COMMON);
   JrnLoadLive();
   JrnExportJs();
}
void JrnOnEnableChanged()
{
   if(JournalEnable)
   {
      FolderCreate(DASHBOARD_DIR, FILE_COMMON);
      FolderCreate(DASHBOARD_DIR + "\\" + JRN_SHOTDIR, FILE_COMMON);
      FolderCreate(DASHBOARD_DIR + "\\" + JrnAccDir(), FILE_COMMON);
      JrnLoadLive();
      JrnExportJs();
   }
   ChartRedraw();
}