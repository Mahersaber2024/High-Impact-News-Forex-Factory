#ifndef REPLAY_BROKER_MQH
#define REPLAY_BROKER_MQH
#ifndef VB_SUFFIX
   #define VB_SUFFIX ".rp"
#endif
#define VB_FILE_VER   20260926
#define VB_ORD_BASE   1000000
#define VB_DEAL_BASE  5000000
struct VBPos
{
   ulong    ticket;  long ident;  int type;
   double   vol;     double open; double sl; double tp; double margin; double swap;
   datetime time;    long tmsc;   datetime tupd;
   long     magic;   int reason;  string comment;
};
struct VBOrd
{
   ulong    ticket;  int type;    int state;
   double   vinit;   double vcur; double price; double stoplimit; double sl; double tp;
   datetime setup;   long smsc;   datetime done;  long dmsc;
   int      ttime;   datetime exp; int filling;
   long     magic;   int reason;  long pos_id; long pos_by;
   string   comment;
};
struct VBDeal
{
   ulong    ticket;  ulong order; long pos_id;
   datetime time;    long tmsc;
   int      type;    int entry;
   double   vol;     double price; double comm; double swap; double profit; double sl; double tp;
   long     magic;   int reason;  string comment; string symbol;
};
struct VBEvt { MqlTradeTransaction t; MqlTradeRequest rq; MqlTradeResult rs; };
int      vb_on=-1;
string   vb_rp="", vb_src="";
VBPos    vb_pos[];
VBOrd    vb_ord[];
VBOrd    vb_hord[];
VBDeal   vb_deal[];
VBEvt    vb_evq[];
int      vb_hsD[], vb_hsO[];
VBPos    vb_sp;  bool vb_spOk=false;
VBOrd    vb_so;  bool vb_soOk=false;
double   vb_bal=10000, vb_comm=0;
int      vb_commSides=2;
double VB_Cents(double v){ return MathRound(v*100.0+1e-7)/100.0; }
ulong    vb_nOrd=VB_ORD_BASE, vb_nDeal=VB_DEAL_BASE;
uint     vb_reqId=1;
long     vb_session=0;
datetime vb_proc=0, vb_lastT=0;
datetime vb_fBar=0;
double   vb_fHi=0, vb_fLo=0, vb_fPx=0;
double   vb_lastBid=0, vb_lastAsk=0;
bool     vb_loaded=false, vb_dirty=false, vb_busy=false, vb_dispatching=false;
datetime vb_seenT=0;
uint     vb_lastCmd=0, vb_lastPub=0;
double   vb_epoch=0;
long     vb_rev=0;
long     vb_flRev=-1; datetime vb_flT=0; double vb_flVal=0;
bool VB_On()
{
   if(vb_on<0)
   {
      vb_on=0;
      string s=_Symbol, suf=VB_SUFFIX;
      int a=StringLen(s), b=StringLen(suf);
      if((bool)SymbolInfoInteger(s,SYMBOL_CUSTOM) && a>b && StringSubstr(s,a-b)==suf)
      {
         vb_rp=s; vb_src=StringSubstr(s,0,a-b);
         bool c=false;
         if(SymbolExist(vb_src,c)){ SymbolSelect(vb_src,true); vb_on=1; }
      }
   }
   return (vb_on==1);
}
string VB_GV(string k)     { return "RPL_"+vb_rp+"_"+k; }
double VB_Pt()             { double p=SymbolInfoDouble(vb_src,SYMBOL_POINT); return (p>0?p:_Point); }
int    VB_Dg()             { return (int)SymbolInfoInteger(vb_src,SYMBOL_DIGITS); }
double VB_N(double p)      { return NormalizeDouble(p,VB_Dg()); }
bool   VB_Sym(string s)    { return (s==vb_rp || s==vb_src || s=="" ); }
datetime VB_Now()
{
   datetime t=(datetime)SymbolInfoInteger(vb_rp,SYMBOL_TIME);
   return (t>0?t:vb_lastT);
}
double VB_Bid(){ double b=SymbolInfoDouble(vb_rp,SYMBOL_BID); return (b>0?b:vb_lastBid); }
double VB_Ask(){ double a=SymbolInfoDouble(vb_rp,SYMBOL_ASK); return (a>0?a:vb_lastAsk); }
bool   VB_IsBuy(int t){ return (t==ORDER_TYPE_BUY||t==ORDER_TYPE_BUY_LIMIT||t==ORDER_TYPE_BUY_STOP||t==ORDER_TYPE_BUY_STOP_LIMIT); }
double VB_Profit(int ptype,double vol,double open,double close)
{
   double p=0;
   if(OrderCalcProfit(ptype==0?ORDER_TYPE_BUY:ORDER_TYPE_SELL,vb_src,vol,open,close,p)) return p;
   double ts=SymbolInfoDouble(vb_src,SYMBOL_TRADE_TICK_SIZE), tv=SymbolInfoDouble(vb_src,SYMBOL_TRADE_TICK_VALUE);
   if(ts<=0) return 0;
   return (ptype==0?close-open:open-close)/ts*tv*vol;
}
double VB_MarginFor(int ptype,double vol,double price)
{
   double m=0;
   if(OrderCalcMargin(ptype==0?ORDER_TYPE_BUY:ORDER_TYPE_SELL,vb_src,vol,price,m)) return m;
   return 0;
}
double VB_PosCur(const VBPos &p){ return (p.type==0?VB_Bid():VB_Ask()); }
double VB_PosProfit(const VBPos &p){ return VB_Profit(p.type,p.vol,p.open,VB_PosCur(p)); }
double VB_Floating()
{
   datetime t=VB_Now();
   if(vb_flRev==vb_rev && vb_flT==t) return vb_flVal;
   double f=0; for(int i=0;i<ArraySize(vb_pos);i++) f+=VB_PosProfit(vb_pos[i])+vb_pos[i].swap;
   vb_flRev=vb_rev; vb_flT=t; vb_flVal=f;
   return f;
}
double VB_UsedMargin(){ double m=0; for(int i=0;i<ArraySize(vb_pos);i++) m+=vb_pos[i].margin; return m; }
int VB_FindPos(ulong t){ for(int i=0;i<ArraySize(vb_pos);i++) if(vb_pos[i].ticket==t) return i; return -1; }
int VB_FindOrd(ulong t){ for(int i=0;i<ArraySize(vb_ord);i++) if(vb_ord[i].ticket==t) return i; return -1; }
int VB_FindHOrd(ulong t){ for(int i=ArraySize(vb_hord)-1;i>=0;i--) if(vb_hord[i].ticket==t) return i; return -1; }
int VB_FindDeal(ulong t){ for(int i=ArraySize(vb_deal)-1;i>=0;i--) if(vb_deal[i].ticket==t) return i; return -1; }
void VB_DelPos(int k){ int n=ArraySize(vb_pos); for(int i=k;i<n-1;i++) vb_pos[i]=vb_pos[i+1]; ArrayResize(vb_pos,n-1); }
void VB_DelOrd(int k){ int n=ArraySize(vb_ord); for(int i=k;i<n-1;i++) vb_ord[i]=vb_ord[i+1]; ArrayResize(vb_ord,n-1); }
void VB_Evt(ENUM_TRADE_TRANSACTION_TYPE tt,ulong deal,ulong order,ulong pos,int otype,int dtype,
            double price,double vol,double sl,double tp,int ostate=0)
{
   vb_rev++;
   VBEvt e; ZeroMemory(e);
   e.t.type=tt; e.t.deal=deal; e.t.order=order; e.t.position=pos; e.t.symbol=vb_rp;
   e.t.order_type=(ENUM_ORDER_TYPE)otype; e.t.deal_type=(ENUM_DEAL_TYPE)dtype;
   e.t.order_state=(ENUM_ORDER_STATE)ostate;
   e.t.price=price; e.t.volume=vol; e.t.price_sl=sl; e.t.price_tp=tp;
   int n=ArraySize(vb_evq); ArrayResize(vb_evq,n+1); vb_evq[n]=e;
}
void VB_EvtReq(const MqlTradeRequest &rq,const MqlTradeResult &rs)
{
   VBEvt e; ZeroMemory(e);
   e.t.type=TRADE_TRANSACTION_REQUEST; e.t.symbol=vb_rp; e.t.order=rs.order; e.t.deal=rs.deal;
   e.rq=rq; e.rs=rs;
   int n=ArraySize(vb_evq); ArrayResize(vb_evq,n+1); vb_evq[n]=e;
}
ulong VB_AddDeal(ulong order,long pos_id,datetime t,int dtype,int entry,double vol,double price,
                 double profit,double comm,long magic,int reason,string cmt,double sl,double tp)
{
   VBDeal d; ZeroMemory(d);
   d.ticket=++vb_nDeal; d.order=order; d.pos_id=pos_id; d.time=t; d.tmsc=(long)t*1000;
   d.type=dtype; d.entry=entry; d.vol=vol; d.price=price; d.profit=profit; d.comm=comm;
   d.magic=magic; d.reason=reason; d.comment=cmt; d.symbol=vb_rp; d.sl=sl; d.tp=tp;
   int n=ArraySize(vb_deal); ArrayResize(vb_deal,n+1); vb_deal[n]=d;
   vb_bal+=profit+comm;
   VB_Evt(TRADE_TRANSACTION_DEAL_ADD,d.ticket,order,(ulong)pos_id,0,dtype,price,vol,sl,tp);
   vb_dirty=true;
   return d.ticket;
}
void VB_AddHistOrder(const VBOrd &o)
{
   int n=ArraySize(vb_hord); ArrayResize(vb_hord,n+1); vb_hord[n]=o;
   VB_Evt(TRADE_TRANSACTION_HISTORY_ADD,0,o.ticket,(ulong)o.pos_id,o.type,0,o.price,o.vinit,o.sl,o.tp,o.state);
}
void VB_NewOrder(VBOrd &o,int type,double vol,double price,double sl,double tp,long magic,string cmt,int reason,datetime t)
{
   ZeroMemory(o);
   o.ticket=++vb_nOrd; o.type=type; o.state=ORDER_STATE_STARTED; o.vinit=vol; o.vcur=vol;
   o.price=price; o.sl=sl; o.tp=tp; o.setup=t; o.smsc=(long)t*1000;
   o.ttime=ORDER_TIME_GTC; o.filling=ORDER_FILLING_FOK; o.magic=magic; o.reason=reason; o.comment=cmt;
}
ulong VB_Open(ulong orderTicket,int ptype,double vol,double price,double sl,double tp,long magic,
              string cmt,int reason,datetime t)
{
   VBPos p; ZeroMemory(p);
   p.ticket=orderTicket; p.ident=(long)orderTicket; p.type=ptype; p.vol=vol; p.open=price;
   p.sl=sl; p.tp=tp; p.time=t; p.tmsc=(long)t*1000; p.tupd=t; p.magic=magic; p.reason=reason;
   p.comment=cmt; p.margin=VB_MarginFor(ptype,vol,price);
   int n=ArraySize(vb_pos); ArrayResize(vb_pos,n+1); vb_pos[n]=p;
   VB_AddDeal(orderTicket,p.ident,t,(ptype==0?DEAL_TYPE_BUY:DEAL_TYPE_SELL),DEAL_ENTRY_IN,vol,price,0,
              -VB_Cents(vb_comm*vol),magic,reason,cmt,sl,tp);
   VB_Evt(TRADE_TRANSACTION_POSITION,0,0,orderTicket,0,0,price,vol,sl,tp);
   return orderTicket;
}
ulong VB_Close(int k,double vol,double price,int reason,datetime t,string cmt,int entry=DEAL_ENTRY_OUT,
               long magic=-1,ulong byTicket=0)
{
   VBPos p=vb_pos[k];
   if(vol<=0 || vol>p.vol) vol=p.vol;
   int otype=(p.type==0?ORDER_TYPE_SELL:ORDER_TYPE_BUY);
   VBOrd o;
   VB_NewOrder(o,(entry==DEAL_ENTRY_OUT_BY?(int)ORDER_TYPE_CLOSE_BY:otype),vol,price,p.sl,p.tp,
               (magic<0?p.magic:magic),cmt,reason,t);
   o.state=ORDER_STATE_FILLED; o.vcur=0; o.done=t; o.dmsc=(long)t*1000; o.pos_id=p.ident; o.pos_by=(long)byTicket;
   VB_Evt(TRADE_TRANSACTION_ORDER_ADD,0,o.ticket,p.ticket,o.type,0,price,vol,0,0,ORDER_STATE_STARTED);
   VB_AddHistOrder(o);
   double pr=VB_Profit(p.type,vol,p.open,price);
   double sw=(vol>=p.vol?p.swap:0);
   ulong d=VB_AddDeal(o.ticket,p.ident,t,(p.type==0?DEAL_TYPE_SELL:DEAL_TYPE_BUY),entry,vol,price,pr,
                      (entry==DEAL_ENTRY_OUT_BY || vb_commSides==1 ? 0.0 : -VB_Cents(vb_comm*vol)),p.magic,reason,cmt,p.sl,p.tp);
   int dk=VB_FindDeal(d); if(dk>=0){ vb_deal[dk].swap=sw; }
   vb_bal+=sw;
   if(vol>=p.vol-1e-9) VB_DelPos(k);
   else
   {
      vb_pos[k].vol=NormalizeDouble(p.vol-vol,8);
      vb_pos[k].margin=VB_MarginFor(p.type,vb_pos[k].vol,p.open);
      vb_pos[k].tupd=t;
   }
   VB_Evt(TRADE_TRANSACTION_POSITION,0,0,p.ticket,0,0,price,vol,0,0);
   return d;
}
void VB_FinishOrder(int k,int state,datetime t)
{
   VBOrd o=vb_ord[k];
   o.state=state; o.done=t; o.dmsc=(long)t*1000;
   if(state==ORDER_STATE_FILLED) o.vcur=0;
   VB_DelOrd(k);
   VB_Evt(TRADE_TRANSACTION_ORDER_DELETE,0,o.ticket,0,o.type,0,o.price,o.vinit,o.sl,o.tp,state);
   VB_AddHistOrder(o);
   vb_dirty=true;
}
void VB_Trigger(int k,double price,datetime t)
{
   VBOrd o=vb_ord[k];
   if(o.type==ORDER_TYPE_BUY_STOP_LIMIT || o.type==ORDER_TYPE_SELL_STOP_LIMIT)
   {
      vb_ord[k].type =(o.type==ORDER_TYPE_BUY_STOP_LIMIT?ORDER_TYPE_BUY_LIMIT:ORDER_TYPE_SELL_LIMIT);
      vb_ord[k].price=o.stoplimit; vb_ord[k].stoplimit=0;
      VB_Evt(TRADE_TRANSACTION_ORDER_UPDATE,0,o.ticket,0,vb_ord[k].type,0,o.stoplimit,o.vcur,o.sl,o.tp,ORDER_STATE_PLACED);
      vb_dirty=true;
      return;
   }
   int ptype=(VB_IsBuy(o.type)?0:1);
   vb_ord[k].pos_id=(long)o.ticket;
   VB_FinishOrder(k,ORDER_STATE_FILLED,t);
   VB_Open(o.ticket,ptype,o.vcur,VB_N(price),o.sl,o.tp,o.magic,o.comment,o.reason,t);
}
bool VB_Cand(double lvl,bool up,double cur,double to,double &dist)
{
   if(lvl<=0) return false;
   if(up)
   {
      if(cur>=lvl-1e-10){ dist=0; return true; }
      if(to>cur && lvl<=to+1e-10){ dist=lvl-cur; return true; }
   }
   else
   {
      if(cur<=lvl+1e-10){ dist=0; return true; }
      if(to<cur && lvl>=to-1e-10){ dist=cur-lvl; return true; }
   }
   return false;
}
void VB_Segment(double from,double to,double spr,datetime t)
{
   double cur=from;
   for(int guard=0;guard<500;guard++)
   {
      double best=DBL_MAX, bl=0; int bkind=-1, bidx=-1; bool bAsk=false;
      double d=0;
      for(int i=0;i<ArraySize(vb_pos);i++)
      {
         VBPos p=vb_pos[i];
         if(p.type==0)
         {
            if(p.sl>0 && VB_Cand(p.sl,false,cur,to,d) && d<best){ best=d; bkind=0; bidx=i; bl=p.sl; bAsk=false; }
            if(p.tp>0 && VB_Cand(p.tp,true ,cur,to,d) && d<best){ best=d; bkind=1; bidx=i; bl=p.tp; bAsk=false; }
         }
         else
         {
            if(p.sl>0 && VB_Cand(p.sl-spr,true ,cur,to,d) && d<best){ best=d; bkind=0; bidx=i; bl=p.sl; bAsk=true; }
            if(p.tp>0 && VB_Cand(p.tp-spr,false,cur,to,d) && d<best){ best=d; bkind=1; bidx=i; bl=p.tp; bAsk=true; }
         }
      }
      for(int i=0;i<ArraySize(vb_ord);i++)
      {
         VBOrd o=vb_ord[i]; bool ok=false, ask=false;
         switch(o.type)
         {
            case ORDER_TYPE_BUY_LIMIT:       ok=VB_Cand(o.price-spr,false,cur,to,d); ask=true;  break;
            case ORDER_TYPE_BUY_STOP:
            case ORDER_TYPE_BUY_STOP_LIMIT:  ok=VB_Cand(o.price-spr,true ,cur,to,d); ask=true;  break;
            case ORDER_TYPE_SELL_LIMIT:      ok=VB_Cand(o.price,true ,cur,to,d);                break;
            case ORDER_TYPE_SELL_STOP:
            case ORDER_TYPE_SELL_STOP_LIMIT: ok=VB_Cand(o.price,false,cur,to,d);                break;
         }
         if(ok && d<best){ best=d; bkind=2; bidx=i; bl=o.price; bAsk=ask; }
      }
      if(bkind<0) break;
      double bidAt = (best==0 ? cur : (bAsk ? bl-spr : bl));
      double fill  = (best==0 ? (bAsk ? cur+spr : cur) : bl);
      if(bkind==2) VB_Trigger(bidx,fill,t);
      else VB_Close(bidx,0,VB_N(fill),(bkind==0?DEAL_REASON_SL:DEAL_REASON_TP),t,
                    (bkind==0?"[sl ":"[tp ")+DoubleToString(fill,VB_Dg())+"]");
      cur=bidAt;
   }
}
void VB_StopOut(double bid,double spr,datetime t)
{
   double so=AccountInfoDouble(ACCOUNT_MARGIN_SO_SO);
   if(so<=0) return;
   for(int g=0;g<100 && ArraySize(vb_pos)>0;g++)
   {
      double m=VB_UsedMargin(); if(m<=0) return;
      double eq=vb_bal;
      int worst=-1; double wp=DBL_MAX;
      for(int i=0;i<ArraySize(vb_pos);i++)
      {
         double pr=VB_Profit(vb_pos[i].type,vb_pos[i].vol,vb_pos[i].open,vb_pos[i].type==0?bid:bid+spr);
         eq+=pr; if(pr<wp){ wp=pr; worst=i; }
      }
      if(eq/m*100.0>so || worst<0) return;
      VB_Close(worst,0,VB_N(vb_pos[worst].type==0?bid:bid+spr),DEAL_REASON_SO,t,"[so]");
   }
}
void VB_Expire(datetime t)
{
   for(int i=ArraySize(vb_ord)-1;i>=0;i--)
   {
      VBOrd o=vb_ord[i]; bool ex=false;
      if((o.ttime==ORDER_TIME_SPECIFIED || o.ttime==ORDER_TIME_SPECIFIED_DAY) && o.exp>0 && t>=o.exp) ex=true;
      if(o.ttime==ORDER_TIME_DAY && (t/86400)!=(o.setup/86400)) ex=true;
      if(ex) VB_FinishOrder(i,ORDER_STATE_EXPIRED,t);
   }
}
void VB_ProcessBar(const MqlRates &r)
{
   double spr=r.spread*VB_Pt();
   VB_Expire(r.time);
   if(ArraySize(vb_pos)==0 && ArraySize(vb_ord)==0) return;
   double x1=(r.close>=r.open?r.low:r.high), x2=(r.close>=r.open?r.high:r.low);
   VB_Segment(r.open,r.open,spr,r.time);
   VB_Segment(r.open,x1,spr,r.time+15);     VB_StopOut(x1,spr,r.time+15);
   VB_Segment(x1,x2,spr,r.time+30);         VB_StopOut(x2,spr,r.time+30);
   VB_Segment(x2,r.close,spr,r.time+45);    VB_StopOut(r.close,spr,r.time+45);
}
void VB_TrackMove(const MqlRates &r)
{
   if(ArraySize(vb_pos)==0 && ArraySize(vb_ord)==0){ vb_fHi=MathMax(vb_fHi,r.high); vb_fLo=MathMin(vb_fLo,r.low); vb_fPx=r.close; return; }
   double spr=r.spread*VB_Pt(), px=vb_fPx;
   datetime t=VB_Now();
   bool nh=(r.high>vb_fHi+1e-10), nl=(r.low<vb_fLo-1e-10);
   if(nh && nl)
   {
      if(MathAbs(px-r.high)<=MathAbs(px-r.low)){ VB_Segment(px,r.high,spr,t); VB_Segment(r.high,r.low,spr,t); px=r.low; }
      else                                      { VB_Segment(px,r.low,spr,t);  VB_Segment(r.low,r.high,spr,t); px=r.high; }
   }
   else if(nh){ VB_Segment(px,r.high,spr,t); px=r.high; }
   else if(nl){ VB_Segment(px,r.low,spr,t);  px=r.low; }
   VB_Segment(px,r.close,spr,t);
   VB_StopOut(r.close,spr,t);
   vb_fHi=MathMax(vb_fHi,r.high); vb_fLo=MathMin(vb_fLo,r.low); vb_fPx=r.close;
}
void VB_Rewind(datetime T)
{
   VBDeal keep[], gone[];
   for(int i=0;i<ArraySize(vb_deal);i++)
   {
      if(vb_deal[i].time<=T || vb_deal[i].type==DEAL_TYPE_BALANCE){ int n=ArraySize(keep); ArrayResize(keep,n+1); keep[n]=vb_deal[i]; }
      else { int n=ArraySize(gone); ArrayResize(gone,n+1); gone[n]=vb_deal[i]; }
   }
   if(ArraySize(gone)==0 && ArraySize(vb_ord)==0 && ArraySize(vb_pos)==0) return;
   VBPos np[];
   for(int i=0;i<ArraySize(keep);i++)
   {
      VBDeal d=keep[i];
      if(d.entry!=DEAL_ENTRY_IN || (d.type!=DEAL_TYPE_BUY && d.type!=DEAL_TYPE_SELL)) continue;
      double v=d.vol;
      for(int j=0;j<ArraySize(keep);j++)
         if(keep[j].pos_id==d.pos_id && (keep[j].entry==DEAL_ENTRY_OUT || keep[j].entry==DEAL_ENTRY_OUT_BY)) v-=keep[j].vol;
      if(v<=1e-9) continue;
      VBPos p;
      int k=VB_FindPos((ulong)d.pos_id);
      if(k>=0) p=vb_pos[k];
      else
      {
         ZeroMemory(p);
         p.ticket=(ulong)d.pos_id; p.ident=d.pos_id; p.type=(d.type==DEAL_TYPE_BUY?0:1);
         p.open=d.price; p.time=d.time; p.tmsc=d.tmsc; p.magic=d.magic; p.reason=d.reason;
         p.comment=d.comment; p.sl=d.sl; p.tp=d.tp;
         for(int j=0;j<ArraySize(gone);j++) if(gone[j].pos_id==d.pos_id){ p.sl=gone[j].sl; p.tp=gone[j].tp; break; }
      }
      p.vol=NormalizeDouble(v,8); p.tupd=T; p.swap=0; p.margin=VB_MarginFor(p.type,p.vol,p.open);
      int n=ArraySize(np); ArrayResize(np,n+1); np[n]=p;
   }
   VBOrd no[], nh[];
   for(int i=0;i<ArraySize(vb_ord);i++) if(vb_ord[i].setup<=T){ int n=ArraySize(no); ArrayResize(no,n+1); no[n]=vb_ord[i]; }
   for(int i=0;i<ArraySize(vb_hord);i++)
   {
      VBOrd o=vb_hord[i];
      if(o.setup>T) continue;
      if(o.done>T)
      {
         if(o.type<=ORDER_TYPE_SELL || o.type==ORDER_TYPE_CLOSE_BY) continue;
         o.state=ORDER_STATE_PLACED; o.vcur=o.vinit; o.done=0; o.dmsc=0; o.pos_id=0;
         int n=ArraySize(no); ArrayResize(no,n+1); no[n]=o;
         continue;
      }
      int n=ArraySize(nh); ArrayResize(nh,n+1); nh[n]=o;
   }
   ArrayResize(vb_deal,ArraySize(keep)); for(int i=0;i<ArraySize(keep);i++) vb_deal[i]=keep[i];
   ArrayResize(vb_pos, ArraySize(np));   for(int i=0;i<ArraySize(np);i++)   vb_pos[i]=np[i];
   ArrayResize(vb_ord, ArraySize(no));   for(int i=0;i<ArraySize(no);i++)   vb_ord[i]=no[i];
   ArrayResize(vb_hord,ArraySize(nh));   for(int i=0;i<ArraySize(nh);i++)   vb_hord[i]=nh[i];
   ArrayFree(vb_hsD); ArrayFree(vb_hsO); vb_spOk=false; vb_soOk=false;
   vb_bal=0;
   for(int i=0;i<ArraySize(vb_deal);i++) vb_bal+=vb_deal[i].profit+vb_deal[i].comm+vb_deal[i].swap;
   for(int i=0;i<ArraySize(gone);i++)
      VB_Evt(TRADE_TRANSACTION_DEAL_DELETE,gone[i].ticket,gone[i].order,(ulong)gone[i].pos_id,0,gone[i].type,gone[i].price,gone[i].vol,0,0);
   for(int i=0;i<ArraySize(vb_pos);i++)
      VB_Evt(TRADE_TRANSACTION_POSITION,0,0,vb_pos[i].ticket,0,0,vb_pos[i].open,vb_pos[i].vol,vb_pos[i].sl,vb_pos[i].tp);
   VB_Evt(TRADE_TRANSACTION_DEAL_ADD,0,0,0,0,0,0,0,0,0);
   vb_dirty=true;
}
string VB_File(){ return "RB_"+vb_rp+".bin"; }
void VB_WS(int h,string s){ FileWriteInteger(h,StringLen(s)); if(StringLen(s)>0) FileWriteString(h,s); }
string VB_RS(int h){ int n=FileReadInteger(h); return (n>0?FileReadString(h,n):""); }
void VB_WPos(int h,const VBPos &p)
{
   FileWriteLong(h,(long)p.ticket); FileWriteLong(h,p.ident); FileWriteInteger(h,p.type);
   FileWriteDouble(h,p.vol); FileWriteDouble(h,p.open); FileWriteDouble(h,p.sl); FileWriteDouble(h,p.tp);
   FileWriteDouble(h,p.margin); FileWriteDouble(h,p.swap);
   FileWriteLong(h,(long)p.time); FileWriteLong(h,p.tmsc); FileWriteLong(h,(long)p.tupd);
   FileWriteLong(h,p.magic); FileWriteInteger(h,p.reason); VB_WS(h,p.comment);
}
void VB_RPos(int h,VBPos &p)
{
   p.ticket=(ulong)FileReadLong(h); p.ident=FileReadLong(h); p.type=FileReadInteger(h);
   p.vol=FileReadDouble(h); p.open=FileReadDouble(h); p.sl=FileReadDouble(h); p.tp=FileReadDouble(h);
   p.margin=FileReadDouble(h); p.swap=FileReadDouble(h);
   p.time=(datetime)FileReadLong(h); p.tmsc=FileReadLong(h); p.tupd=(datetime)FileReadLong(h);
   p.magic=FileReadLong(h); p.reason=FileReadInteger(h); p.comment=VB_RS(h);
}
void VB_WOrd(int h,const VBOrd &o)
{
   FileWriteLong(h,(long)o.ticket); FileWriteInteger(h,o.type); FileWriteInteger(h,o.state);
   FileWriteDouble(h,o.vinit); FileWriteDouble(h,o.vcur); FileWriteDouble(h,o.price); FileWriteDouble(h,o.stoplimit);
   FileWriteDouble(h,o.sl); FileWriteDouble(h,o.tp);
   FileWriteLong(h,(long)o.setup); FileWriteLong(h,o.smsc); FileWriteLong(h,(long)o.done); FileWriteLong(h,o.dmsc);
   FileWriteInteger(h,o.ttime); FileWriteLong(h,(long)o.exp); FileWriteInteger(h,o.filling);
   FileWriteLong(h,o.magic); FileWriteInteger(h,o.reason); FileWriteLong(h,o.pos_id); FileWriteLong(h,o.pos_by);
   VB_WS(h,o.comment);
}
void VB_ROrd(int h,VBOrd &o)
{
   o.ticket=(ulong)FileReadLong(h); o.type=FileReadInteger(h); o.state=FileReadInteger(h);
   o.vinit=FileReadDouble(h); o.vcur=FileReadDouble(h); o.price=FileReadDouble(h); o.stoplimit=FileReadDouble(h);
   o.sl=FileReadDouble(h); o.tp=FileReadDouble(h);
   o.setup=(datetime)FileReadLong(h); o.smsc=FileReadLong(h); o.done=(datetime)FileReadLong(h); o.dmsc=FileReadLong(h);
   o.ttime=FileReadInteger(h); o.exp=(datetime)FileReadLong(h); o.filling=FileReadInteger(h);
   o.magic=FileReadLong(h); o.reason=FileReadInteger(h); o.pos_id=FileReadLong(h); o.pos_by=FileReadLong(h);
   o.comment=VB_RS(h);
}
void VB_WDeal(int h,const VBDeal &d)
{
   FileWriteLong(h,(long)d.ticket); FileWriteLong(h,(long)d.order); FileWriteLong(h,d.pos_id);
   FileWriteLong(h,(long)d.time); FileWriteLong(h,d.tmsc); FileWriteInteger(h,d.type); FileWriteInteger(h,d.entry);
   FileWriteDouble(h,d.vol); FileWriteDouble(h,d.price); FileWriteDouble(h,d.comm); FileWriteDouble(h,d.swap);
   FileWriteDouble(h,d.profit); FileWriteDouble(h,d.sl); FileWriteDouble(h,d.tp);
   FileWriteLong(h,d.magic); FileWriteInteger(h,d.reason); VB_WS(h,d.comment); VB_WS(h,d.symbol);
}
void VB_RDeal(int h,VBDeal &d)
{
   d.ticket=(ulong)FileReadLong(h); d.order=(ulong)FileReadLong(h); d.pos_id=FileReadLong(h);
   d.time=(datetime)FileReadLong(h); d.tmsc=FileReadLong(h); d.type=FileReadInteger(h); d.entry=FileReadInteger(h);
   d.vol=FileReadDouble(h); d.price=FileReadDouble(h); d.comm=FileReadDouble(h); d.swap=FileReadDouble(h);
   d.profit=FileReadDouble(h); d.sl=FileReadDouble(h); d.tp=FileReadDouble(h);
   d.magic=FileReadLong(h); d.reason=FileReadInteger(h); d.comment=VB_RS(h); d.symbol=VB_RS(h);
}
bool VB_WriteFile(string f)
{
   int h=FileOpen(f,FILE_WRITE|FILE_BIN|FILE_SHARE_READ);
   if(h==INVALID_HANDLE) return false;
   FileWriteInteger(h,VB_FILE_VER);
   FileWriteDouble(h,vb_bal); FileWriteLong(h,(long)vb_nOrd); FileWriteLong(h,(long)vb_nDeal);
   FileWriteLong(h,vb_session); FileWriteLong(h,(long)vb_proc); FileWriteLong(h,(long)vb_lastT);
   FileWriteDouble(h,vb_lastBid); FileWriteDouble(h,vb_lastAsk);
   FileWriteDouble(h,vb_epoch);
   int n;
   n=ArraySize(vb_pos);  FileWriteInteger(h,n); for(int i=0;i<n;i++) VB_WPos(h,vb_pos[i]);
   n=ArraySize(vb_ord);  FileWriteInteger(h,n); for(int i=0;i<n;i++) VB_WOrd(h,vb_ord[i]);
   n=ArraySize(vb_hord); FileWriteInteger(h,n); for(int i=0;i<n;i++) VB_WOrd(h,vb_hord[i]);
   n=ArraySize(vb_deal); FileWriteInteger(h,n); for(int i=0;i<n;i++) VB_WDeal(h,vb_deal[i]);
   FileClose(h);
   return true;
}
void VB_Save()
{
   string tmp="RB_"+vb_rp+".tmp";
   bool ok=(VB_WriteFile(tmp) && FileMove(tmp,0,VB_File(),FILE_REWRITE));
   if(!ok){ FileDelete(tmp); ok=VB_WriteFile(VB_File()); }
   if(ok) vb_dirty=false;
}
bool VB_Load()
{
   int h=FileOpen(VB_File(),FILE_READ|FILE_BIN);
   if(h==INVALID_HANDLE) return false;
   if(FileReadInteger(h)!=VB_FILE_VER){ FileClose(h); return false; }
   vb_bal=FileReadDouble(h); vb_nOrd=(ulong)FileReadLong(h); vb_nDeal=(ulong)FileReadLong(h);
   vb_session=FileReadLong(h); vb_proc=(datetime)FileReadLong(h); vb_lastT=(datetime)FileReadLong(h);
   vb_lastBid=FileReadDouble(h); vb_lastAsk=FileReadDouble(h);
   vb_epoch=FileReadDouble(h);
   int n;
   n=FileReadInteger(h); ArrayResize(vb_pos,n);  for(int i=0;i<n;i++) VB_RPos(h,vb_pos[i]);
   n=FileReadInteger(h); ArrayResize(vb_ord,n);  for(int i=0;i<n;i++) VB_ROrd(h,vb_ord[i]);
   n=FileReadInteger(h); ArrayResize(vb_hord,n); for(int i=0;i<n;i++) VB_ROrd(h,vb_hord[i]);
   n=FileReadInteger(h); ArrayResize(vb_deal,n); for(int i=0;i<n;i++) VB_RDeal(h,vb_deal[i]);
   FileClose(h);
   return true;
}
void VB_DrawOrders()
{
   string pfx="VB_ORD_";
   for(int i=ObjectsTotal(0,0,OBJ_HLINE)-1;i>=0;i--)
   {
      string n=ObjectName(0,i,0,OBJ_HLINE);
      if(StringFind(n,pfx)!=0) continue;
      ObjectDelete(0,n);
   }
}
datetime VB_LastBarTime(){ datetime t=iTime(vb_rp,PERIOD_M1,0); return (t>0?t:VB_Now()); }
void VB_ResetAccount(double balance)
{
   ArrayFree(vb_pos); ArrayFree(vb_ord); ArrayFree(vb_hord); ArrayFree(vb_deal);
   ArrayFree(vb_hsD); ArrayFree(vb_hsO); vb_spOk=false; vb_soOk=false;
   vb_bal=0;
   VB_AddDeal(0,0,(datetime)1,DEAL_TYPE_BALANCE,DEAL_ENTRY_IN,0,0,balance,0,0,DEAL_REASON_CLIENT,"Replay deposit",0,0);
   vb_deal[ArraySize(vb_deal)-1].symbol="";
   vb_dirty=true;
}
void VB_NewSession(long ses)
{
   for(int i=ArraySize(vb_pos)-1;i>=0;i--)
      VB_Close(i,0,(vb_pos[i].type==0?vb_lastBid:vb_lastAsk),DEAL_REASON_CLIENT,vb_lastT,"[replay restart]");
   double b=vb_bal;
   VB_ResetAccount(b);
   vb_session=ses;
   vb_proc=VB_LastBarTime(); vb_fBar=0;
   vb_lastT=VB_Now(); vb_lastBid=VB_Bid(); vb_lastAsk=VB_Ask();
   Print("[ReplayBroker] New replay session: open trades closed, balance ",DoubleToString(vb_bal,2));
}
void VB_Publish(bool force=false)
{
   if(!force && GetTickCount()-vb_lastPub<250) return;
   vb_lastPub=GetTickCount();
   double fl=VB_Floating(), m=VB_UsedMargin();
   int w=0,l=0; double net=0;
   long pid[]; double pnl[];
   for(int i=0;i<ArraySize(vb_deal);i++)
      if(vb_deal[i].entry==DEAL_ENTRY_OUT || vb_deal[i].entry==DEAL_ENTRY_OUT_BY)
      {
         double r=vb_deal[i].profit+vb_deal[i].comm+vb_deal[i].swap;
         net+=r;
         if(VB_FindPos((ulong)vb_deal[i].pos_id)>=0) continue;
         int k=-1; for(int j=0;j<ArraySize(pid);j++) if(pid[j]==vb_deal[i].pos_id){ k=j; break; }
         if(k<0){ k=ArraySize(pid); ArrayResize(pid,k+1); ArrayResize(pnl,k+1); pid[k]=vb_deal[i].pos_id; pnl[k]=0; }
         pnl[k]+=r;
      }
   for(int j=0;j<ArraySize(pnl);j++){ if(pnl[j]>=0) w++; else l++; }
   GlobalVariableSet(VB_GV("vb_bal"),vb_bal);
   GlobalVariableSet(VB_GV("vb_eq"),vb_bal+fl);
   GlobalVariableSet(VB_GV("vb_fl"),fl);
   GlobalVariableSet(VB_GV("vb_mrg"),m);
   GlobalVariableSet(VB_GV("vb_pos"),ArraySize(vb_pos));
   GlobalVariableSet(VB_GV("vb_ord"),ArraySize(vb_ord));
   GlobalVariableSet(VB_GV("vb_w"),w);
   GlobalVariableSet(VB_GV("vb_l"),l);
   GlobalVariableSet(VB_GV("vb_net"),net);
   GlobalVariableSet(VB_GV("vb_hb"),(double)TimeLocal());
   GlobalVariableSet(VB_GV("vb_tf"),(double)(int)Period());
}
double VB_GVEpoch(){ return GlobalVariableCheck(VB_GV("epoch"))?GlobalVariableGet(VB_GV("epoch")):0.0; }
void VB_Fresh()
{
   double b=GlobalVariableCheck(VB_GV("initbal"))?GlobalVariableGet(VB_GV("initbal")):10000.0;
   VB_ResetAccount(b);
   vb_epoch=VB_GVEpoch();
   vb_session=(long)(GlobalVariableCheck(VB_GV("session"))?GlobalVariableGet(VB_GV("session")):0.0);
   vb_proc=VB_LastBarTime(); vb_fBar=0; vb_seenT=0;
   vb_lastT=VB_Now(); vb_lastBid=VB_Bid(); vb_lastAsk=VB_Ask();
   ArrayFree(vb_evq);
   VB_Save();
}
void VB_Init()
{
   if(vb_loaded) return;
   vb_loaded=true;
   SymbolSelect(vb_rp,true);
   if(!VB_Load() || vb_epoch!=VB_GVEpoch()) VB_Fresh();
   VB_DrawOrders();
   Print("[ReplayBroker] Virtual account active on ",vb_rp," (source ",vb_src,")  balance ",DoubleToString(vb_bal,2));
}
void VB_Sync()
{
   if(vb_busy) return;
   vb_busy=true;
   VB_Init();
   if(GetTickCount()-vb_lastCmd>200)
   {
      vb_lastCmd=GetTickCount();
      vb_comm=GlobalVariableCheck(VB_GV("comm"))?GlobalVariableGet(VB_GV("comm")):0.0;
      vb_commSides=(int)(GlobalVariableCheck(VB_GV("commsides"))?GlobalVariableGet(VB_GV("commsides")):2.0);
      if(VB_GVEpoch()!=vb_epoch)
      {
         VB_Fresh(); VB_DrawOrders();
         Print("[ReplayBroker] Replay was reset: virtual account back to ",DoubleToString(vb_bal,2));
      }
      if(GlobalVariableCheck(VB_GV("cmdbal")))
      {
         double b=GlobalVariableGet(VB_GV("cmdbal"));
         GlobalVariableDel(VB_GV("cmdbal"));
         VB_ResetAccount(b);
         vb_proc=VB_LastBarTime(); vb_fBar=0;
         Print("[ReplayBroker] Account reset, balance ",DoubleToString(b,2));
      }
   }
   datetime now=VB_Now();
   if(now!=vb_seenT)
   {
      vb_seenT=now;
      long ses=(long)(GlobalVariableCheck(VB_GV("session"))?GlobalVariableGet(VB_GV("session")):(double)vb_session);
      if(ses!=vb_session) VB_NewSession(ses);
      if(now<vb_lastT || now<vb_proc)
      {
         VB_Rewind(now);
         datetime lb=iTime(vb_rp,PERIOD_M1,0);
         vb_proc=(lb>0 && lb<=now ? lb : now);
         vb_fBar=0;
      }
      else
      {
         datetime b0=now-now%60;
         if(vb_fBar>0 && vb_fBar<b0)
         {
            MqlRates fr[];
            if(CopyRates(vb_rp,PERIOD_M1,vb_fBar,1,fr)==1 && fr[0].time==vb_fBar) VB_TrackMove(fr[0]);
            if(vb_fBar>vb_proc) vb_proc=vb_fBar;
            vb_fBar=0;
         }
         datetime lastFull=(now-b0>=59 ? b0 : b0-60);
         if(lastFull>vb_proc)
         {
            MqlRates r[];
            int n=CopyRates(vb_rp,PERIOD_M1,vb_proc+1,lastFull,r);
            for(int i=0;i<n;i++) if(r[i].time>vb_proc && r[i].time<=lastFull){ VB_ProcessBar(r[i]); vb_proc=r[i].time; }
            if(n>0) vb_dirty=true;
         }
         if(now-b0<59)
         {
            MqlRates cr[];
            if(CopyRates(vb_rp,PERIOD_M1,b0,1,cr)==1 && cr[0].time==b0)
            {
               if(vb_fBar!=b0)
               {
                  if(vb_proc<b0){ VB_ProcessBar(cr[0]); vb_proc=b0; vb_dirty=true; }
                  vb_fBar=b0; vb_fHi=cr[0].high; vb_fLo=cr[0].low; vb_fPx=cr[0].close;
               }
               else VB_TrackMove(cr[0]);
            }
         }
      }
      vb_lastT=now; vb_lastBid=VB_Bid(); vb_lastAsk=VB_Ask();
   }
   if(vb_dirty){ VB_Save(); VB_Publish(true); VB_DrawOrders(); }
   else VB_Publish();
   vb_busy=false;
}
bool VB_StopsOk(bool buy,double ref,double sl,double tp)
{
   double lvl=SymbolInfoInteger(vb_src,SYMBOL_TRADE_STOPS_LEVEL)*VB_Pt();
   if(buy){ if(sl>0 && sl>ref-lvl) return false; if(tp>0 && tp<ref+lvl) return false; }
   else   { if(sl>0 && sl<ref+lvl) return false; if(tp>0 && tp>ref-lvl) return false; }
   return true;
}
bool VB_VolOk(double v)
{
   double mn=SymbolInfoDouble(vb_src,SYMBOL_VOLUME_MIN), mx=SymbolInfoDouble(vb_src,SYMBOL_VOLUME_MAX), st=SymbolInfoDouble(vb_src,SYMBOL_VOLUME_STEP);
   if(v<mn-1e-9 || (mx>0 && v>mx+1e-9)) return false;
   if(st>0 && MathAbs(v/st-MathRound(v/st))>1e-6) return false;
   return true;
}
uint VB_Exec(const MqlTradeRequest &rq,MqlTradeResult &rs)
{
   datetime t=VB_Now();
   double bid=VB_Bid(), ask=VB_Ask();
   rs.bid=bid; rs.ask=ask; rs.request_id=vb_reqId++;
   if(bid<=0) return TRADE_RETCODE_PRICE_OFF;
   switch(rq.action)
   {
      case TRADE_ACTION_DEAL:
      {
         if(!VB_Sym(rq.symbol)) return TRADE_RETCODE_INVALID;
         if(rq.type!=ORDER_TYPE_BUY && rq.type!=ORDER_TYPE_SELL) return TRADE_RETCODE_INVALID_ORDER;
         double price=(rq.type==ORDER_TYPE_BUY?ask:bid);
         if(rq.position>0)
         {
            int k=VB_FindPos(rq.position);
            if(k<0) return TRADE_RETCODE_POSITION_CLOSED;
            if((vb_pos[k].type==0)==(rq.type==ORDER_TYPE_BUY)) return TRADE_RETCODE_INVALID_ORDER;
            if(rq.volume<=0 || rq.volume>vb_pos[k].vol+1e-9) return TRADE_RETCODE_INVALID_VOLUME;
            rs.order=0; rs.volume=rq.volume; rs.price=price;
            PrintFormat("[ReplayBroker] CLOSE by EA request: position #%I64u  %.2f of %.2f lots at %s  magic=%I64d  comment=\"%s\"",
                        rq.position,rq.volume,vb_pos[k].vol,DoubleToString(price,VB_Dg()),(long)rq.magic,rq.comment);
            rs.deal=VB_Close(k,rq.volume,price,DEAL_REASON_EXPERT,t,rq.comment,DEAL_ENTRY_OUT,(long)rq.magic);
            rs.order=vb_hord[ArraySize(vb_hord)-1].ticket;
            return TRADE_RETCODE_DONE;
         }
         if(!VB_VolOk(rq.volume)) return TRADE_RETCODE_INVALID_VOLUME;
         bool buy=(rq.type==ORDER_TYPE_BUY);
         double sl=VB_N(rq.sl), tp=VB_N(rq.tp);
         if(!VB_StopsOk(buy,buy?bid:ask,sl,tp)) return TRADE_RETCODE_INVALID_STOPS;
         double need=VB_MarginFor(buy?0:1,rq.volume,price);
         if(need>(vb_bal+VB_Floating()-VB_UsedMargin())) return TRADE_RETCODE_NO_MONEY;
         VBOrd o; VB_NewOrder(o,rq.type,rq.volume,price,sl,tp,(long)rq.magic,rq.comment,ORDER_REASON_EXPERT,t);
         o.state=ORDER_STATE_FILLED; o.vcur=0; o.done=t; o.dmsc=(long)t*1000; o.pos_id=(long)o.ticket; o.filling=rq.type_filling;
         VB_Evt(TRADE_TRANSACTION_ORDER_ADD,0,o.ticket,0,o.type,0,price,rq.volume,sl,tp,ORDER_STATE_STARTED);
         VB_AddHistOrder(o);
         VB_Open(o.ticket,buy?0:1,rq.volume,price,sl,tp,(long)rq.magic,rq.comment,DEAL_REASON_EXPERT,t);
         PrintFormat("[ReplayBroker] OPEN %s %.2f lots at %s  sl=%s tp=%s  position #%I64u  magic=%I64d  comment=\"%s\"",
                     buy?"buy":"sell",rq.volume,DoubleToString(price,VB_Dg()),DoubleToString(sl,VB_Dg()),DoubleToString(tp,VB_Dg()),
                     o.ticket,(long)rq.magic,rq.comment);
         rs.order=o.ticket; rs.deal=vb_nDeal; rs.volume=rq.volume; rs.price=price;
         return TRADE_RETCODE_DONE;
      }
      case TRADE_ACTION_PENDING:
      {
         if(!VB_Sym(rq.symbol)) return TRADE_RETCODE_INVALID;
         int ty=rq.type;
         if(ty<ORDER_TYPE_BUY_LIMIT || ty>ORDER_TYPE_SELL_STOP_LIMIT) return TRADE_RETCODE_INVALID_ORDER;
         if(!VB_VolOk(rq.volume)) return TRADE_RETCODE_INVALID_VOLUME;
         double p=VB_N(rq.price), sl=VB_N(rq.sl), tp=VB_N(rq.tp), spl=VB_N(rq.stoplimit);
         double lvl=SymbolInfoInteger(vb_src,SYMBOL_TRADE_STOPS_LEVEL)*VB_Pt();
         bool okp=true;
         if(ty==ORDER_TYPE_BUY_LIMIT)       okp=(p<=ask-lvl);
         if(ty==ORDER_TYPE_BUY_STOP)        okp=(p>=ask+lvl);
         if(ty==ORDER_TYPE_SELL_LIMIT)      okp=(p>=bid+lvl);
         if(ty==ORDER_TYPE_SELL_STOP)       okp=(p<=bid-lvl);
         if(ty==ORDER_TYPE_BUY_STOP_LIMIT)  okp=(p>=ask+lvl && spl>0 && spl<=p);
         if(ty==ORDER_TYPE_SELL_STOP_LIMIT) okp=(p<=bid-lvl && spl>=p);
         if(p<=0 || !okp) return TRADE_RETCODE_INVALID_PRICE;
         double ref=(ty>=ORDER_TYPE_BUY_STOP_LIMIT?spl:p);
         if(!VB_StopsOk(VB_IsBuy(ty),ref,sl,tp)) return TRADE_RETCODE_INVALID_STOPS;
         VBOrd o; VB_NewOrder(o,ty,rq.volume,p,sl,tp,(long)rq.magic,rq.comment,ORDER_REASON_EXPERT,t);
         o.state=ORDER_STATE_PLACED; o.stoplimit=spl; o.ttime=rq.type_time; o.exp=rq.expiration; o.filling=rq.type_filling;
         int n=ArraySize(vb_ord); ArrayResize(vb_ord,n+1); vb_ord[n]=o;
         VB_Evt(TRADE_TRANSACTION_ORDER_ADD,0,o.ticket,0,ty,0,p,rq.volume,sl,tp,ORDER_STATE_PLACED);
         rs.order=o.ticket; rs.volume=rq.volume; rs.price=p; vb_dirty=true;
         return TRADE_RETCODE_DONE;
      }
      case TRADE_ACTION_SLTP:
      {
         int k=VB_FindPos(rq.position);
         if(k<0 && rq.position==0) for(int i=0;i<ArraySize(vb_pos);i++){ k=i; break; }
         if(k<0) return TRADE_RETCODE_POSITION_CLOSED;
         double sl=VB_N(rq.sl), tp=VB_N(rq.tp);
         if(MathAbs(sl-vb_pos[k].sl)<VB_Pt()/2 && MathAbs(tp-vb_pos[k].tp)<VB_Pt()/2) return TRADE_RETCODE_NO_CHANGES;
         bool buy=(vb_pos[k].type==0);
         if(!VB_StopsOk(buy,buy?bid:ask,sl,tp)) return TRADE_RETCODE_INVALID_STOPS;
         vb_pos[k].sl=sl; vb_pos[k].tp=tp; vb_pos[k].tupd=t;
         VB_Evt(TRADE_TRANSACTION_POSITION,0,0,vb_pos[k].ticket,0,0,vb_pos[k].open,vb_pos[k].vol,sl,tp);
         rs.order=0; vb_dirty=true;
         return TRADE_RETCODE_DONE;
      }
      case TRADE_ACTION_MODIFY:
      {
         int k=VB_FindOrd(rq.order);
         if(k<0) return TRADE_RETCODE_INVALID_ORDER;
         VBOrd o=vb_ord[k];
         double p=VB_N(rq.price), sl=VB_N(rq.sl), tp=VB_N(rq.tp), spl=VB_N(rq.stoplimit);
         if(p<=0) p=o.price;
         if(MathAbs(p-o.price)<VB_Pt()/2 && MathAbs(sl-o.sl)<VB_Pt()/2 && MathAbs(tp-o.tp)<VB_Pt()/2 &&
            MathAbs(spl-o.stoplimit)<VB_Pt()/2 && rq.expiration==o.exp && rq.type_time==o.ttime) return TRADE_RETCODE_NO_CHANGES;
         bool okp=true; int ty=o.type;
         if(ty==ORDER_TYPE_BUY_LIMIT)  okp=(p<ask);
         if(ty==ORDER_TYPE_BUY_STOP || ty==ORDER_TYPE_BUY_STOP_LIMIT)  okp=(p>ask);
         if(ty==ORDER_TYPE_SELL_LIMIT) okp=(p>bid);
         if(ty==ORDER_TYPE_SELL_STOP || ty==ORDER_TYPE_SELL_STOP_LIMIT) okp=(p<bid);
         if(!okp) return TRADE_RETCODE_INVALID_PRICE;
         double ref=(ty>=ORDER_TYPE_BUY_STOP_LIMIT?spl:p);
         if(!VB_StopsOk(VB_IsBuy(ty),ref,sl,tp)) return TRADE_RETCODE_INVALID_STOPS;
         vb_ord[k].price=p; vb_ord[k].sl=sl; vb_ord[k].tp=tp; vb_ord[k].stoplimit=spl;
         vb_ord[k].ttime=rq.type_time; vb_ord[k].exp=rq.expiration;
         VB_Evt(TRADE_TRANSACTION_ORDER_UPDATE,0,o.ticket,0,ty,0,p,o.vcur,sl,tp,ORDER_STATE_PLACED);
         rs.order=o.ticket; vb_dirty=true;
         return TRADE_RETCODE_DONE;
      }
      case TRADE_ACTION_REMOVE:
      {
         int k=VB_FindOrd(rq.order);
         if(k<0) return TRADE_RETCODE_INVALID_ORDER;
         rs.order=rq.order;
         VB_FinishOrder(k,ORDER_STATE_CANCELED,t);
         return TRADE_RETCODE_DONE;
      }
      case TRADE_ACTION_CLOSE_BY:
      {
         int a=VB_FindPos(rq.position), b=VB_FindPos(rq.position_by);
         if(a<0 || b<0 || a==b) return TRADE_RETCODE_INVALID;
         if(vb_pos[a].type==vb_pos[b].type) return TRADE_RETCODE_INVALID;
         double v=MathMin(vb_pos[a].vol,vb_pos[b].vol);
         double px=vb_pos[b].open;
         ulong ta=vb_pos[a].ticket, tb=vb_pos[b].ticket;
         rs.deal=VB_Close(a,v,px,DEAL_REASON_EXPERT,t,rq.comment,DEAL_ENTRY_OUT_BY,(long)rq.magic,tb);
         int b2=VB_FindPos(tb);
         if(b2>=0) VB_Close(b2,v,px,DEAL_REASON_EXPERT,t,rq.comment,DEAL_ENTRY_OUT_BY,(long)rq.magic,ta);
         rs.volume=v; rs.price=px;
         return TRADE_RETCODE_DONE;
      }
   }
   return TRADE_RETCODE_INVALID;
}
string VB_RetText(uint rc)
{
   switch(rc)
   {
      case TRADE_RETCODE_DONE:            return "Request completed (virtual)";
      case TRADE_RETCODE_PLACED:          return "Order placed (virtual)";
      case TRADE_RETCODE_NO_CHANGES:      return "No changes";
      case TRADE_RETCODE_INVALID_STOPS:   return "Invalid stops";
      case TRADE_RETCODE_INVALID_PRICE:   return "Invalid price";
      case TRADE_RETCODE_INVALID_VOLUME:  return "Invalid volume";
      case TRADE_RETCODE_NO_MONEY:        return "No money";
      case TRADE_RETCODE_POSITION_CLOSED: return "Position not found";
      case TRADE_RETCODE_INVALID_ORDER:   return "Invalid order";
      case TRADE_RETCODE_PRICE_OFF:       return "No quotes";
   }
   return "Invalid request";
}
bool VB_Send(const MqlTradeRequest &rq,MqlTradeResult &rs,bool async)
{
   VB_Sync();
   ZeroMemory(rs);
   vb_busy=true;
   uint rc=VB_Exec(rq,rs);
   vb_busy=false;
   bool ok=(rc==TRADE_RETCODE_DONE);
   rs.retcode=(ok && async ? (uint)TRADE_RETCODE_PLACED : rc);
   rs.comment=VB_RetText(rc);
   if(!ok) PrintFormat("[ReplayBroker] request rejected: %s (%u)  action=%d type=%d vol=%.2f price=%.5f sl=%.5f tp=%.5f",
                       rs.comment,rc,(int)rq.action,(int)rq.type,rq.volume,rq.price,rq.sl,rq.tp);
   VB_EvtReq(rq,rs);
   VB_Save(); VB_Publish(true); VB_DrawOrders();
   return ok;
}
void VB_SelHist(datetime from,datetime to)
{
   ArrayFree(vb_hsD); ArrayFree(vb_hsO);
   for(int i=0;i<ArraySize(vb_deal);i++) if(vb_deal[i].time>=from && vb_deal[i].time<=to){ int n=ArraySize(vb_hsD); ArrayResize(vb_hsD,n+1); vb_hsD[n]=i; }
   for(int i=0;i<ArraySize(vb_hord);i++) if(vb_hord[i].setup>=from && vb_hord[i].setup<=to){ int n=ArraySize(vb_hsO); ArrayResize(vb_hsO,n+1); vb_hsO[n]=i; }
}
long VB_DealI(const VBDeal &d,ENUM_DEAL_PROPERTY_INTEGER p)
{
   switch(p)
   {
      case DEAL_TICKET: return (long)d.ticket;      case DEAL_ORDER: return (long)d.order;
      case DEAL_TIME: return (long)d.time;          case DEAL_TIME_MSC: return d.tmsc;
      case DEAL_TYPE: return d.type;                case DEAL_ENTRY: return d.entry;
      case DEAL_MAGIC: return d.magic;              case DEAL_REASON: return d.reason;
      case DEAL_POSITION_ID: return d.pos_id;
   }
   return 0;
}
double VB_DealD(const VBDeal &d,ENUM_DEAL_PROPERTY_DOUBLE p)
{
   switch(p)
   {
      case DEAL_VOLUME: return d.vol;   case DEAL_PRICE: return d.price;  case DEAL_COMMISSION: return d.comm;
      case DEAL_SWAP: return d.swap;    case DEAL_PROFIT: return d.profit; case DEAL_SL: return d.sl; case DEAL_TP: return d.tp;
   }
   return 0;
}
string VB_DealS(const VBDeal &d,ENUM_DEAL_PROPERTY_STRING p)
{
   if(p==DEAL_SYMBOL) return d.symbol; if(p==DEAL_COMMENT) return d.comment; return "";
}
long VB_OrdI(const VBOrd &o,ENUM_ORDER_PROPERTY_INTEGER p)
{
   switch(p)
   {
      case ORDER_TICKET: return (long)o.ticket;     case ORDER_TIME_SETUP: return (long)o.setup;
      case ORDER_TYPE: return o.type;               case ORDER_STATE: return o.state;
      case ORDER_TIME_EXPIRATION: return (long)o.exp; case ORDER_TIME_DONE: return (long)o.done;
      case ORDER_TIME_SETUP_MSC: return o.smsc;     case ORDER_TIME_DONE_MSC: return o.dmsc;
      case ORDER_TYPE_FILLING: return o.filling;    case ORDER_TYPE_TIME: return o.ttime;
      case ORDER_MAGIC: return o.magic;             case ORDER_REASON: return o.reason;
      case ORDER_POSITION_ID: return o.pos_id;      case ORDER_POSITION_BY_ID: return o.pos_by;
   }
   return 0;
}
double VB_OrdD(const VBOrd &o,ENUM_ORDER_PROPERTY_DOUBLE p)
{
   switch(p)
   {
      case ORDER_VOLUME_INITIAL: return o.vinit;  case ORDER_VOLUME_CURRENT: return o.vcur;
      case ORDER_PRICE_OPEN: return o.price;      case ORDER_SL: return o.sl;  case ORDER_TP: return o.tp;
      case ORDER_PRICE_STOPLIMIT: return o.stoplimit;
      case ORDER_PRICE_CURRENT: return (VB_IsBuy(o.type)?VB_Ask():VB_Bid());
   }
   return 0;
}
string VB_OrdS(const VBOrd &o,ENUM_ORDER_PROPERTY_STRING p)
{
   if(p==ORDER_SYMBOL) return vb_rp; if(p==ORDER_COMMENT) return o.comment; return "";
}
long VB_PosI(const VBPos &q,ENUM_POSITION_PROPERTY_INTEGER p)
{
   switch(p)
   {
      case POSITION_TICKET: return (long)q.ticket;  case POSITION_TIME: return (long)q.time;
      case POSITION_TIME_MSC: return q.tmsc;        case POSITION_TIME_UPDATE: return (long)q.tupd;
      case POSITION_TIME_UPDATE_MSC: return (long)q.tupd*1000;
      case POSITION_TYPE: return q.type;            case POSITION_MAGIC: return q.magic;
      case POSITION_IDENTIFIER: return q.ident;     case POSITION_REASON: return q.reason;
   }
   return 0;
}
double VB_PosD(const VBPos &q,ENUM_POSITION_PROPERTY_DOUBLE p)
{
   int k=VB_FindPos(q.ticket); VBPos c; if(k>=0) c=vb_pos[k]; else c=q;
   switch(p)
   {
      case POSITION_VOLUME: return c.vol;         case POSITION_PRICE_OPEN: return c.open;
      case POSITION_SL: return c.sl;              case POSITION_TP: return c.tp;
      case POSITION_PRICE_CURRENT: return VB_PosCur(c);
      case POSITION_SWAP: return c.swap;          case POSITION_PROFIT: return VB_PosProfit(c);
   }
   return 0;
}
string VB_PosS(const VBPos &q,ENUM_POSITION_PROPERTY_STRING p)
{
   if(p==POSITION_SYMBOL) return vb_rp; if(p==POSITION_COMMENT) return q.comment; return "";
}
int    VB_PositionsTotal()                   { if(!VB_On()) return PositionsTotal(); VB_Sync(); return ArraySize(vb_pos); }
ulong  VB_PositionGetTicket(int i)
{
   if(!VB_On()) return PositionGetTicket(i);
   VB_Sync(); if(i<0 || i>=ArraySize(vb_pos)){ vb_spOk=false; return 0; }
   vb_sp=vb_pos[i]; vb_spOk=true; return vb_sp.ticket;
}
string VB_PositionGetSymbol(int i)           { if(!VB_On()) return PositionGetSymbol(i); return (VB_PositionGetTicket(i)>0?vb_rp:""); }
bool   VB_PositionSelect(string s)
{
   if(!VB_On()) return PositionSelect(s);
   VB_Sync(); if(!VB_Sym(s) || ArraySize(vb_pos)==0){ vb_spOk=false; return false; }
   vb_sp=vb_pos[0]; vb_spOk=true; return true;
}
bool   VB_PositionSelectByTicket(ulong t)
{
   if(!VB_On()) return PositionSelectByTicket(t);
   VB_Sync(); int k=VB_FindPos(t); if(k<0){ vb_spOk=false; return false; }
   vb_sp=vb_pos[k]; vb_spOk=true; return true;
}
double VB_PositionGetDouble(ENUM_POSITION_PROPERTY_DOUBLE p)              { if(!VB_On()) return PositionGetDouble(p);  return vb_spOk?VB_PosD(vb_sp,p):0; }
bool   VB_PositionGetDouble(ENUM_POSITION_PROPERTY_DOUBLE p,double &v)    { if(!VB_On()) return PositionGetDouble(p,v); if(!vb_spOk) return false; v=VB_PosD(vb_sp,p); return true; }
long   VB_PositionGetInteger(ENUM_POSITION_PROPERTY_INTEGER p)            { if(!VB_On()) return PositionGetInteger(p); return vb_spOk?VB_PosI(vb_sp,p):0; }
bool   VB_PositionGetInteger(ENUM_POSITION_PROPERTY_INTEGER p,long &v)    { if(!VB_On()) return PositionGetInteger(p,v); if(!vb_spOk) return false; v=VB_PosI(vb_sp,p); return true; }
string VB_PositionGetString(ENUM_POSITION_PROPERTY_STRING p)              { if(!VB_On()) return PositionGetString(p);  return vb_spOk?VB_PosS(vb_sp,p):""; }
bool   VB_PositionGetString(ENUM_POSITION_PROPERTY_STRING p,string &v)    { if(!VB_On()) return PositionGetString(p,v); if(!vb_spOk) return false; v=VB_PosS(vb_sp,p); return true; }
int    VB_OrdersTotal()                      { if(!VB_On()) return OrdersTotal(); VB_Sync(); return ArraySize(vb_ord); }
ulong  VB_OrderGetTicket(int i)
{
   if(!VB_On()) return OrderGetTicket(i);
   VB_Sync(); if(i<0 || i>=ArraySize(vb_ord)){ vb_soOk=false; return 0; }
   vb_so=vb_ord[i]; vb_soOk=true; return vb_so.ticket;
}
bool   VB_OrderSelect(ulong t)
{
   if(!VB_On()) return OrderSelect(t);
   VB_Sync(); int k=VB_FindOrd(t); if(k<0){ vb_soOk=false; return false; }
   vb_so=vb_ord[k]; vb_soOk=true; return true;
}
double VB_OrderGetDouble(ENUM_ORDER_PROPERTY_DOUBLE p)                { if(!VB_On()) return OrderGetDouble(p);  return vb_soOk?VB_OrdD(vb_so,p):0; }
bool   VB_OrderGetDouble(ENUM_ORDER_PROPERTY_DOUBLE p,double &v)      { if(!VB_On()) return OrderGetDouble(p,v); if(!vb_soOk) return false; v=VB_OrdD(vb_so,p); return true; }
long   VB_OrderGetInteger(ENUM_ORDER_PROPERTY_INTEGER p)              { if(!VB_On()) return OrderGetInteger(p); return vb_soOk?VB_OrdI(vb_so,p):0; }
bool   VB_OrderGetInteger(ENUM_ORDER_PROPERTY_INTEGER p,long &v)      { if(!VB_On()) return OrderGetInteger(p,v); if(!vb_soOk) return false; v=VB_OrdI(vb_so,p); return true; }
string VB_OrderGetString(ENUM_ORDER_PROPERTY_STRING p)                { if(!VB_On()) return OrderGetString(p);  return vb_soOk?VB_OrdS(vb_so,p):""; }
bool   VB_OrderGetString(ENUM_ORDER_PROPERTY_STRING p,string &v)      { if(!VB_On()) return OrderGetString(p,v); if(!vb_soOk) return false; v=VB_OrdS(vb_so,p); return true; }
bool   VB_HistorySelect(datetime f,datetime t)  { if(!VB_On()) return HistorySelect(f,t); VB_Sync(); VB_SelHist(f,t); return true; }
bool   VB_HistorySelectByPosition(long id)
{
   if(!VB_On()) return HistorySelectByPosition(id);
   VB_Sync(); ArrayFree(vb_hsD); ArrayFree(vb_hsO);
   for(int i=0;i<ArraySize(vb_deal);i++) if(vb_deal[i].pos_id==id){ int n=ArraySize(vb_hsD); ArrayResize(vb_hsD,n+1); vb_hsD[n]=i; }
   for(int i=0;i<ArraySize(vb_hord);i++) if(vb_hord[i].pos_id==id){ int n=ArraySize(vb_hsO); ArrayResize(vb_hsO,n+1); vb_hsO[n]=i; }
   return true;
}
int    VB_HistoryDealsTotal()     { if(!VB_On()) return HistoryDealsTotal(); return ArraySize(vb_hsD); }
ulong  VB_HistoryDealGetTicket(int i)
{
   if(!VB_On()) return HistoryDealGetTicket(i);
   if(i<0 || i>=ArraySize(vb_hsD) || vb_hsD[i]>=ArraySize(vb_deal)) return 0;
   return vb_deal[vb_hsD[i]].ticket;
}
bool   VB_HistoryDealSelect(ulong t)
{
   if(!VB_On()) return HistoryDealSelect(t);
   VB_Sync(); int k=VB_FindDeal(t); if(k<0) return false;
   ArrayResize(vb_hsD,1); vb_hsD[0]=k; return true;
}
double VB_HistoryDealGetDouble(ulong t,ENUM_DEAL_PROPERTY_DOUBLE p)             { if(!VB_On()) return HistoryDealGetDouble(t,p);  int k=VB_FindDeal(t); return k<0?0:VB_DealD(vb_deal[k],p); }
bool   VB_HistoryDealGetDouble(ulong t,ENUM_DEAL_PROPERTY_DOUBLE p,double &v)   { if(!VB_On()) return HistoryDealGetDouble(t,p,v); int k=VB_FindDeal(t); if(k<0) return false; v=VB_DealD(vb_deal[k],p); return true; }
long   VB_HistoryDealGetInteger(ulong t,ENUM_DEAL_PROPERTY_INTEGER p)           { if(!VB_On()) return HistoryDealGetInteger(t,p); int k=VB_FindDeal(t); return k<0?0:VB_DealI(vb_deal[k],p); }
bool   VB_HistoryDealGetInteger(ulong t,ENUM_DEAL_PROPERTY_INTEGER p,long &v)   { if(!VB_On()) return HistoryDealGetInteger(t,p,v); int k=VB_FindDeal(t); if(k<0) return false; v=VB_DealI(vb_deal[k],p); return true; }
string VB_HistoryDealGetString(ulong t,ENUM_DEAL_PROPERTY_STRING p)             { if(!VB_On()) return HistoryDealGetString(t,p);  int k=VB_FindDeal(t); return k<0?"":VB_DealS(vb_deal[k],p); }
bool   VB_HistoryDealGetString(ulong t,ENUM_DEAL_PROPERTY_STRING p,string &v)   { if(!VB_On()) return HistoryDealGetString(t,p,v); int k=VB_FindDeal(t); if(k<0) return false; v=VB_DealS(vb_deal[k],p); return true; }
int    VB_HistoryOrdersTotal()    { if(!VB_On()) return HistoryOrdersTotal(); return ArraySize(vb_hsO); }
ulong  VB_HistoryOrderGetTicket(int i)
{
   if(!VB_On()) return HistoryOrderGetTicket(i);
   if(i<0 || i>=ArraySize(vb_hsO) || vb_hsO[i]>=ArraySize(vb_hord)) return 0;
   return vb_hord[vb_hsO[i]].ticket;
}
bool   VB_HistoryOrderSelect(ulong t)
{
   if(!VB_On()) return HistoryOrderSelect(t);
   VB_Sync(); int k=VB_FindHOrd(t); if(k<0) return false;
   ArrayResize(vb_hsO,1); vb_hsO[0]=k; return true;
}
double VB_HistoryOrderGetDouble(ulong t,ENUM_ORDER_PROPERTY_DOUBLE p)            { if(!VB_On()) return HistoryOrderGetDouble(t,p);  int k=VB_FindHOrd(t); return k<0?0:VB_OrdD(vb_hord[k],p); }
bool   VB_HistoryOrderGetDouble(ulong t,ENUM_ORDER_PROPERTY_DOUBLE p,double &v)  { if(!VB_On()) return HistoryOrderGetDouble(t,p,v); int k=VB_FindHOrd(t); if(k<0) return false; v=VB_OrdD(vb_hord[k],p); return true; }
long   VB_HistoryOrderGetInteger(ulong t,ENUM_ORDER_PROPERTY_INTEGER p)          { if(!VB_On()) return HistoryOrderGetInteger(t,p); int k=VB_FindHOrd(t); return k<0?0:VB_OrdI(vb_hord[k],p); }
bool   VB_HistoryOrderGetInteger(ulong t,ENUM_ORDER_PROPERTY_INTEGER p,long &v)  { if(!VB_On()) return HistoryOrderGetInteger(t,p,v); int k=VB_FindHOrd(t); if(k<0) return false; v=VB_OrdI(vb_hord[k],p); return true; }
string VB_HistoryOrderGetString(ulong t,ENUM_ORDER_PROPERTY_STRING p)            { if(!VB_On()) return HistoryOrderGetString(t,p);  int k=VB_FindHOrd(t); return k<0?"":VB_OrdS(vb_hord[k],p); }
bool   VB_HistoryOrderGetString(ulong t,ENUM_ORDER_PROPERTY_STRING p,string &v)  { if(!VB_On()) return HistoryOrderGetString(t,p,v); int k=VB_FindHOrd(t); if(k<0) return false; v=VB_OrdS(vb_hord[k],p); return true; }
bool VB_OrderSend(const MqlTradeRequest &rq,MqlTradeResult &rs)       { if(!VB_On()) return OrderSend(rq,rs);      return VB_Send(rq,rs,false); }
bool VB_OrderSendAsync(const MqlTradeRequest &rq,MqlTradeResult &rs)  { if(!VB_On()) return OrderSendAsync(rq,rs); return VB_Send(rq,rs,true); }
bool VB_OrderCheck(const MqlTradeRequest &rq,MqlTradeCheckResult &cr)
{
   if(!VB_On()) return OrderCheck(rq,cr);
   VB_Sync(); ZeroMemory(cr);
   double fl=VB_Floating(), m=VB_UsedMargin(), need=0;
   if(rq.action==TRADE_ACTION_DEAL || rq.action==TRADE_ACTION_PENDING)
      need=VB_MarginFor(VB_IsBuy(rq.type)?0:1,rq.volume,rq.price>0?rq.price:(VB_IsBuy(rq.type)?VB_Ask():VB_Bid()));
   cr.balance=vb_bal; cr.equity=vb_bal+fl; cr.profit=fl; cr.margin=m+need; cr.margin_free=cr.equity-cr.margin;
   cr.margin_level=(cr.margin>0?cr.equity/cr.margin*100:0);
   cr.retcode=(cr.margin_free<0?(uint)TRADE_RETCODE_NO_MONEY:(uint)0);
   cr.comment=(cr.retcode==0?"Done":"No money");
   return (cr.retcode==0);
}
bool VB_OrderCalcMargin(ENUM_ORDER_TYPE t,string s,double v,double p,double &m)
{
   if(VB_On() && VB_Sym(s)) s=vb_src;
   return OrderCalcMargin(t,s,v,p,m);
}
bool VB_OrderCalcProfit(ENUM_ORDER_TYPE t,string s,double v,double o,double c,double &pr)
{
   if(VB_On() && VB_Sym(s)) s=vb_src;
   return OrderCalcProfit(t,s,v,o,c,pr);
}
double VB_AccountInfoDouble(ENUM_ACCOUNT_INFO_DOUBLE p)
{
   if(!VB_On()) return AccountInfoDouble(p);
   VB_Sync();
   double fl=VB_Floating(), m=VB_UsedMargin(), eq=vb_bal+fl;
   switch(p)
   {
      case ACCOUNT_BALANCE:      return vb_bal;
      case ACCOUNT_EQUITY:       return eq;
      case ACCOUNT_PROFIT:       return fl;
      case ACCOUNT_MARGIN:       return m;
      case ACCOUNT_MARGIN_FREE:  return eq-m;
      case ACCOUNT_MARGIN_LEVEL: return (m>0?eq/m*100.0:0);
      case ACCOUNT_CREDIT:       return 0;
      case ACCOUNT_ASSETS:       return 0;
      case ACCOUNT_LIABILITIES:  return 0;
   }
   return AccountInfoDouble(p);
}
long VB_RealLogin(){ return AccountInfoInteger(ACCOUNT_LOGIN); }
long VB_Login()
{
   if(GlobalVariableCheck("RPL_VLOGIN")){ long v=(long)GlobalVariableGet("RPL_VLOGIN"); if(v>0) return v; }
   return 2000000000 + (VB_RealLogin() % 100000000);
}
string VB_AccountInfoString(ENUM_ACCOUNT_INFO_STRING p)
{
   if(!VB_On()) return AccountInfoString(p);
   if(p==ACCOUNT_COMPANY || p==ACCOUNT_NAME) return AccountInfoString(p)+" (Replay)";
   return AccountInfoString(p);
}
long VB_AccountInfoInteger(ENUM_ACCOUNT_INFO_INTEGER p)
{
   if(!VB_On()) return AccountInfoInteger(p);
   switch(p)
   {
      case ACCOUNT_LOGIN:         return VB_Login();
      case ACCOUNT_MARGIN_MODE:   return ACCOUNT_MARGIN_MODE_RETAIL_HEDGING;
      case ACCOUNT_TRADE_ALLOWED: return 1;
      case ACCOUNT_TRADE_EXPERT:  return 1;
      case ACCOUNT_LIMIT_ORDERS:  return 0;
   }
   return AccountInfoInteger(p);
}
bool VB_RedirD(string s,ENUM_SYMBOL_INFO_DOUBLE p)
{
   if(!VB_On() || s!=vb_rp) return false;
   switch(p)
   {
      case SYMBOL_BID: case SYMBOL_ASK: case SYMBOL_LAST:
      case SYMBOL_BIDHIGH: case SYMBOL_BIDLOW: case SYMBOL_ASKHIGH: case SYMBOL_ASKLOW:
      case SYMBOL_LASTHIGH: case SYMBOL_LASTLOW:
      case SYMBOL_SESSION_OPEN: case SYMBOL_SESSION_CLOSE:
      case SYMBOL_PRICE_CHANGE: case SYMBOL_VOLUME_REAL: case SYMBOL_VOLUMEHIGH_REAL: case SYMBOL_VOLUMELOW_REAL:
         return false;
   }
   return true;
}
bool VB_RedirI(string s,ENUM_SYMBOL_INFO_INTEGER p)
{
   if(!VB_On() || s!=vb_rp) return false;
   switch(p)
   {
      case SYMBOL_TIME: case SYMBOL_TIME_MSC: case SYMBOL_SPREAD: case SYMBOL_SELECT: case SYMBOL_VISIBLE:
      case SYMBOL_CUSTOM: case SYMBOL_VOLUME: case SYMBOL_VOLUMEHIGH: case SYMBOL_VOLUMELOW:
      case SYMBOL_SESSION_DEALS: case SYMBOL_SESSION_BUY_ORDERS: case SYMBOL_SESSION_SELL_ORDERS:
      case SYMBOL_EXIST:
         return false;
   }
   return true;
}
double VB_SymbolInfoDouble(string s,ENUM_SYMBOL_INFO_DOUBLE p)
{
   if(VB_RedirD(s,p)) return SymbolInfoDouble(vb_src,p);
   double v=SymbolInfoDouble(s,p);
   if(VB_On() && s==vb_rp && v<=0 && (p==SYMBOL_BID || p==SYMBOL_ASK)) v=(p==SYMBOL_BID?VB_Bid():VB_Ask());
   return v;
}
bool VB_SymbolInfoDouble(string s,ENUM_SYMBOL_INFO_DOUBLE p,double &v)
{
   if(VB_RedirD(s,p)) return SymbolInfoDouble(vb_src,p,v);
   return SymbolInfoDouble(s,p,v);
}
long VB_SymbolInfoInteger(string s,ENUM_SYMBOL_INFO_INTEGER p)
{
   if(VB_RedirI(s,p)) return SymbolInfoInteger(vb_src,p);
   return SymbolInfoInteger(s,p);
}
bool VB_SymbolInfoInteger(string s,ENUM_SYMBOL_INFO_INTEGER p,long &v)
{
   if(VB_RedirI(s,p)) return SymbolInfoInteger(vb_src,p,v);
   return SymbolInfoInteger(s,p,v);
}
datetime VB_TimeCurrent()                     { if(!VB_On()) return TimeCurrent(); datetime t=VB_Now(); return (t>0?t:TimeCurrent()); }
datetime VB_TimeCurrent(MqlDateTime &dt)      { datetime t=VB_TimeCurrent(); TimeToStruct(t,dt); return t; }
datetime VB_TimeTradeServer()                 { return VB_TimeCurrent(); }
datetime VB_TimeTradeServer(MqlDateTime &dt)  { datetime t=VB_TimeCurrent(); TimeToStruct(t,dt); return t; }
#ifndef VB_NO_HOOKS
void VB_UserOnTick();
void VB_UserOnTimer();
void VB_UserOnTrade();
void VB_UserOnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result);
void VB_UserOnChartEvent(const int id,const long &lparam,const double &dparam,const string &sparam);
void VB_UserOnDeinit(const int reason);
bool VB_ToolbarClick(const string sparam)
{
   string tb="RPCT_";
   if(StringFind(sparam,tb)!=0) return false;
   ObjectSetInteger(0,sparam,OBJPROP_STATE,false);
   string n=StringSubstr(sparam,StringLen(tb));
   int code=0;
   if(n=="back") code=1; else if(n=="play") code=2; else if(n=="step") code=3;
   else if(n=="speed") code=4; else if(n=="tf") code=5;
   else if(StringFind(n,"tf_")==0) code=100+(int)StringToInteger(StringSubstr(n,3));
   else if(StringFind(n,"sp_")==0) code=200+(int)StringToInteger(StringSubstr(n,3));
   if(code>0)
   {
      GlobalVariableSet(VB_GV("cmd"),code);
      double seq=GlobalVariableCheck(VB_GV("cmdseq"))?GlobalVariableGet(VB_GV("cmdseq")):0.0;
      GlobalVariableSet(VB_GV("cmdseq"),seq+1);
   }
   ChartRedraw();
   return true;
}
void VB_Dispatch()
{
   if(vb_dispatching || ArraySize(vb_evq)==0) return;
   vb_dispatching=true;
   for(int loop=0;loop<20 && ArraySize(vb_evq)>0;loop++)
   {
      VBEvt q[]; int n=ArraySize(vb_evq); ArrayResize(q,n);
      for(int i=0;i<n;i++) q[i]=vb_evq[i];
      ArrayFree(vb_evq);
      for(int i=0;i<n;i++) VB_UserOnTradeTransaction(q[i].t,q[i].rq,q[i].rs);
      VB_UserOnTrade();
   }
   vb_dispatching=false;
}
void OnTick()
{
   if(VB_On()){ VB_Sync(); VB_Dispatch(); }
   VB_UserOnTick();
   if(VB_On()) VB_Dispatch();
}
bool VB_Paused(){ return (GlobalVariableCheck(VB_GV("playing")) && GlobalVariableGet(VB_GV("playing"))<0.5); }
void OnTimer()
{
   if(VB_On())
   {
      if(VB_Paused())
      {
         // Replay paused: the replay clock is frozen, so stay almost idle (4 runs/sec)
         static uint vb_lastPausedRun=0;
         if(GetTickCount()-vb_lastPausedRun<250) return;
         vb_lastPausedRun=GetTickCount();
      }
      VB_Sync(); VB_Dispatch();
   }
   VB_UserOnTimer();
   if(VB_On()) VB_Dispatch();
}
void OnChartEvent(const int id,const long &lparam,const double &dparam,const string &sparam)
{
   if(VB_On() && id==CHARTEVENT_OBJECT_CLICK && VB_ToolbarClick(sparam)) return;
   VB_UserOnChartEvent(id,lparam,dparam,sparam);
}
void OnDeinit(const int reason)
{
   if(VB_On() && (reason==REASON_CHARTCLOSE || reason==REASON_CLOSE))
      GlobalVariableSet(VB_GV("rcclosed"),(double)ChartID());
   if(VB_On() && vb_loaded) VB_Save();
   VB_UserOnDeinit(reason);
}
void OnTrade()
{
   if(VB_On()) return;
   VB_UserOnTrade();
}
void OnTradeTransaction(const MqlTradeTransaction &trans,const MqlTradeRequest &request,const MqlTradeResult &result)
{
   if(VB_On()) return;
   VB_UserOnTradeTransaction(trans,request,result);
}
#define OnTick              VB_UserOnTick
#define OnTimer             VB_UserOnTimer
#define OnTrade             VB_UserOnTrade
#define OnTradeTransaction  VB_UserOnTradeTransaction
#define OnChartEvent        VB_UserOnChartEvent
#define OnDeinit            VB_UserOnDeinit
#endif
#define PositionsTotal            VB_PositionsTotal
#define PositionGetTicket         VB_PositionGetTicket
#define PositionGetSymbol         VB_PositionGetSymbol
#define PositionSelect            VB_PositionSelect
#define PositionSelectByTicket    VB_PositionSelectByTicket
#define PositionGetDouble         VB_PositionGetDouble
#define PositionGetInteger        VB_PositionGetInteger
#define PositionGetString         VB_PositionGetString
#define OrdersTotal               VB_OrdersTotal
#define OrderGetTicket            VB_OrderGetTicket
#define OrderSelect               VB_OrderSelect
#define OrderGetDouble            VB_OrderGetDouble
#define OrderGetInteger           VB_OrderGetInteger
#define OrderGetString            VB_OrderGetString
#define HistorySelect             VB_HistorySelect
#define HistorySelectByPosition   VB_HistorySelectByPosition
#define HistoryDealsTotal         VB_HistoryDealsTotal
#define HistoryDealGetTicket      VB_HistoryDealGetTicket
#define HistoryDealSelect         VB_HistoryDealSelect
#define HistoryDealGetDouble      VB_HistoryDealGetDouble
#define HistoryDealGetInteger     VB_HistoryDealGetInteger
#define HistoryDealGetString      VB_HistoryDealGetString
#define HistoryOrdersTotal        VB_HistoryOrdersTotal
#define HistoryOrderGetTicket     VB_HistoryOrderGetTicket
#define HistoryOrderSelect        VB_HistoryOrderSelect
#define HistoryOrderGetDouble     VB_HistoryOrderGetDouble
#define HistoryOrderGetInteger    VB_HistoryOrderGetInteger
#define HistoryOrderGetString     VB_HistoryOrderGetString
#define OrderSend                 VB_OrderSend
#define OrderSendAsync            VB_OrderSendAsync
#define OrderCheck                VB_OrderCheck
#define OrderCalcMargin           VB_OrderCalcMargin
#define OrderCalcProfit           VB_OrderCalcProfit
#define AccountInfoDouble         VB_AccountInfoDouble
#define AccountInfoInteger        VB_AccountInfoInteger
#define AccountInfoString         VB_AccountInfoString
#define SymbolInfoDouble          VB_SymbolInfoDouble
#define SymbolInfoInteger         VB_SymbolInfoInteger
#define TimeCurrent               VB_TimeCurrent
#define TimeTradeServer           VB_TimeTradeServer
#endif
