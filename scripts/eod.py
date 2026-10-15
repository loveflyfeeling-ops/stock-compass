"""盤後更新 → data/raw.json
- 收盤 K 線：上市取證交所 MI_INDEX、上櫃取櫃買中心 dailyQuotes，兩邊都沒有的才用 Yahoo Finance
- 股票清單：每天比對證交所（BWIBBU）與櫃買中心（公司基本資料）的普通股清單，自動補進新上市櫃股票（含歷史 K 線），移除已下市且停止交易的股票
- 外資／投信買賣超：證交所 T86＋櫃買中心，近 20 日內缺漏的日子自動補抓
- 本益比／股價淨值比／殖利率：證交所 BWIBBU＋櫃買中心
用法：python3 scripts/eod.py [YYYY-MM-DD] [fill]
  fill：不新增當日 K 線，只整理視窗、同步股票清單並補抓缺漏資料
資料格式：o/h/l 以「與收盤價的差 ×100」整數儲存（enc=1）；f/ff/ft 對齊 dates[fk:]（單位：張）"""
import json,sys,urllib.request,datetime,time
from concurrent.futures import ThreadPoolExecutor
TZ=datetime.timezone(datetime.timedelta(hours=8))
day=sys.argv[1] if len(sys.argv)>1 and sys.argv[1] else datetime.datetime.now(TZ).strftime('%Y-%m-%d')
FILL=len(sys.argv)>2 and sys.argv[2]=='fill'
MAXD,W=160,20   # K 線保留 160 個交易日、法人保留 20 日
PATH='data/raw.json'
IND={'01':'水泥工業','02':'食品工業','03':'塑膠工業','04':'紡織纖維','05':'電機機械','06':'電器電纜','08':'玻璃陶瓷','09':'造紙工業','10':'鋼鐵工業','11':'橡膠工業','12':'汽車工業','14':'建材營造','15':'航運業','16':'觀光餐旅','17':'金融保險','18':'貿易百貨','19':'綜合','20':'其他','21':'化學工業','22':'生技醫療業','23':'油電燃氣業','24':'半導體業','25':'電腦及週邊設備業','26':'光電業','27':'通信網路業','28':'電子零組件業','29':'電子通路業','30':'資訊服務業','31':'其他電子業','32':'文化創意業','33':'農業科技業','34':'電子商務','35':'綠能環保','36':'數位雲端','37':'運動休閒','38':'居家生活'}
R=json.load(open(PATH,encoding='utf8'))
D=R['dates']
if R.get('enc'):
    for s in R['s'].values():
        for k in 'ohl': s[k]=[round(c+d/100,2) for c,d in zip(s['c'],s[k])]
SUF=lambda sid:'.TWO' if R['s'].get(sid,{}).get('x')=='o' else '.TW'
if not FILL:
    if day in D: print('ALREADY',day);sys.exit(0)
    if day<D[-1]: print('OLDER',day,'<',D[-1]);sys.exit(0)
def fetch(u,n=4):
    err=None
    for k in range(n):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=40))
        except Exception as e: err=e;time.sleep(3+4*k)
    raise err
def num(x):
    try: return float(str(x).replace(',',''))
    except Exception: return None
r2=lambda v:None if v is None else round(v,2)
tsday=lambda t:datetime.datetime.fromtimestamp(t,TZ).strftime('%Y-%m-%d')
def ychart(sym,q):
    return fetch(f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&{q}',3)['chart']['result'][0]
def yq(sid,suf=None):
    try:
        r=ychart(sid+(suf or SUF(sid)),'range=1d');m=r['meta'];q=r['indicators']['quote'][0]
        if tsday(m['regularMarketTime'])!=day: return sid,None
        g=lambda k:(q.get(k) or [None])[-1]
        return sid,[r2(g('open')),r2(m.get('regularMarketDayHigh')),r2(m.get('regularMarketDayLow')),r2(m['regularMarketPrice']),round((m.get('regularMarketVolume') or 0)/1000)]
    except Exception: return sid,None
upd=halt=0;tx=None
if not FILL:
    ymd=day.replace('-','');bars={}
    try: mi=fetch(f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=ALLBUT0999&response=json')
    except Exception as e: print('MI_INDEX error',e); mi={}
    for t in (mi.get('tables') or []):
        f=t.get('fields') or []
        if '收盤價' in f and '證券代號' in f:
            ix={k:f.index(k) for k in ['證券代號','成交股數','開盤價','最高價','最低價','收盤價']}
            for r in t['data']:
                bars[r[ix['證券代號']].strip()]=[num(r[ix['開盤價']]),num(r[ix['最高價']]),num(r[ix['最低價']]),num(r[ix['收盤價']]),round((num(r[ix['成交股數']]) or 0)/1000)]
        if '收盤指數' in f:
            for r in t['data']:
                if str(r[0]).strip()=='發行量加權股價指數': tx=num(r[1])
    nt=len(bars)
    try:
        t=fetch(f'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={day.replace("-","%2F")}&id=&response=json')
        for tb in t.get('tables') or []:
            F=tb.get('fields') or []
            if '收盤' in F and '代號' in F:
                a=[F.index(k) for k in ('開盤','最高','最低','收盤','成交股數')]
                for r in tb['data']:
                    sid=r[F.index('代號')].strip()
                    if sid not in bars: bars[sid]=[num(r[a[0]]),num(r[a[1]]),num(r[a[2]]),num(r[a[3]]),round((num(r[a[4]]) or 0)/1000)]
    except Exception as e: print('TPEx quotes err',e)
    print('twse bars',nt,'tpex bars',len(bars)-nt)
    need=[sid for sid in R['s'] if not (bars.get(sid) and bars[sid][3])]
    with ThreadPoolExecutor(8) as ex:
        for sid,b in ex.map(yq,need):
            if b and b[3]: bars[sid]=b
    print('yahoo filled',sum(1 for sid in need if sid in bars and bars[sid][3]),'of',len(need))
    if len(bars)<500: print('NOTRADE',day);sys.exit(0)
    if not tx:
        try:
            m=ychart('%5ETWII','range=1d')['meta']
            if tsday(m['regularMarketTime'])==day: tx=round(m['regularMarketPrice'],2)
        except Exception: pass
    nD=len(D);D.append(day)
    for sid,s in R['s'].items():
        if s['k']+len(s['c'])!=nD: continue
        b=bars.get(sid);pc=s['c'][-1]
        if b and b[3]:
            o,h,l,c,v=b;o=o or c;h=max(h or c,c);l=min(l or c,c);upd+=1
        else:
            o=h=l=c=pc;v=0;halt+=1
        for k,x in zip('ohlcv',(o,h,l,c,v)): s[k].append(x)
    if tx: R['taiex'].append(tx)
# ---- 視窗整理：K 線 MAXD 日、法人 W 日 ----
nD=len(D);FK=R['fk']
for s in R['s'].values():
    for key in ('f','ff','ft'):
        a=s.get(key) or []
        s[key]=(a+[None]*(nD-FK))[:nD-FK]
while len(D)>MAXD:
    D.pop(0)
    for s in R['s'].values():
        if s['k']>0: s['k']-=1
        else:
            for k in 'ohlcv': s[k].pop(0)
    R['fk']-=1
while len(D)-R['fk']>W:
    R['fk']+=1
    for s in R['s'].values():
        for key in ('f','ff','ft'): s[key].pop(0)
if R['fk']<0:
    for s in R['s'].values():
        for key in ('f','ff','ft'): s[key]=s[key][-R['fk']:]
    R['fk']=0
while len(D)-R['fk']<W and R['fk']>0:
    R['fk']-=1
    for s in R['s'].values():
        for key in ('f','ff','ft'): s[key].insert(0,None)
R['taiex']=R['taiex'][-60:]
FK=R['fk']
# ---- 股票清單同步 ----
tw={};tp={};twi={}
try:
    t=fetch(f'https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={D[-1].replace("-","")}&selectType=ALL&response=json')
    if t.get('stat')=='OK': tw={r[0].strip():r[1].strip() for r in t['data']}
except Exception as e: print('TWSE list err',e)
try: tp={x['SecuritiesCompanyCode'].strip():(x['CompanyAbbreviation'].strip(),x.get('SecuritiesIndustryCode','').strip()) for x in fetch('https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O')}
except Exception as e: print('TPEx list err',e)
try: twi={x.get('公司代號','').strip():x.get('產業別','').strip() for x in fetch('https://openapi.twse.com.tw/v1/opendata/t187ap03_L',1)}
except Exception: pass
for sid,(n,ic) in tp.items():
    if sid in R['s'] and IND.get(ic): R['s'][sid]['i']=IND[ic];R['s'][sid]['x']='o'
NEW=[]
def yhist(sid,suf):
    try:
        t0=int(datetime.datetime.strptime(D[0],'%Y-%m-%d').replace(tzinfo=TZ).timestamp())-86400
        r=ychart(sid+suf,f'period1={t0}&period2={int(time.time())+86400}');q=r['indicators']['quote'][0];out={}
        for j,t in enumerate(r.get('timestamp') or []):
            c=q['close'][j]
            if c is None: continue
            o,h,l,v=q['open'][j],q['high'][j],q['low'][j],q['volume'][j]
            out[tsday(t)]=[r2(o or c),r2(max(h or c,c)),r2(min(l or c,c)),r2(c),round((v or 0)/1000)]
        return sid,out
    except Exception: return sid,None
if len(tw)>800 and len(tp)>500:
    cand=[(sid,n,'.TW',IND.get(twi.get(sid,''),'其他'),None) for sid,n in tw.items() if sid not in R['s']]
    cand+=[(sid,n,'.TWO',IND.get(ic,'其他'),'o') for sid,(n,ic) in tp.items() if sid not in R['s']]
    with ThreadPoolExecutor(8) as ex: H=dict(ex.map(lambda c:yhist(c[0],c[2]),cand))
    for sid,n,suf,ind,x in cand:
        h=H.get(sid)
        if not h: print('no history',sid,n);continue
        idx=[j for j,d in enumerate(D) if d in h]
        if not idx: print('no bars in window',sid,n);continue
        k=idx[0];s={'n':n,'i':ind,'k':k,'o':[],'h':[],'l':[],'c':[],'v':[]}
        if x: s['x']=x
        for j in range(k,len(D)):
            b=h.get(D[j]) or [s['c'][-1]]*4+[0]
            for key,val in zip('ohlcv',b): s[key].append(val)
        for key in ('f','ff','ft'): s[key]=[None]*(len(D)-FK)
        R['s'][sid]=s;NEW.append(sid)
    # 已下市：不在兩邊清單、不是 ETF、且最近 5 日都沒有成交
    gone=[sid for sid,s in R['s'].items() if sid not in tw and sid not in tp and not s['i'].startswith('ETF') and sum(s['v'][-5:])==0 and s['k']+len(s['c'])==len(D)]
    for sid in gone: del R['s'][sid]
    print('new listings',len(NEW),'delisted',len(gone),gone[:10])
# ---- 法人：缺整天的日子全部補抓；有新股時把近 20 日也補給新股 ----
def chips(d):
    ymd=d.replace('-','');out={}
    try:
        t=fetch(f'https://www.twse.com.tw/rwd/zh/fund/T86?date={ymd}&selectType=ALLBUT0999&response=json')
        if t.get('stat')=='OK':
            F=t['fields'];a=F.index('外陸資買賣超股數(不含外資自營商)');b=F.index('外資自營商買賣超股數');c=F.index('投信買賣超股數');z=F.index('三大法人買賣超股數')
            for r in t['data']: out[r[0].strip()]=[round(num(r[z])/1000),round(((num(r[a]) or 0)+(num(r[b]) or 0))/1000),round((num(r[c]) or 0)/1000)]
    except Exception as e: print('T86 err',d,e)
    if not out: return {}
    time.sleep(1.5)
    try:
        t=fetch(f'https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date={d.replace("-","%2F")}&response=json')
        for tb in t.get('tables') or []:
            for r in tb.get('data') or []:
                if len(r)>=24: out.setdefault(r[0].strip(),[round(num(r[23])/1000),round(num(r[10])/1000),round(num(r[13])/1000)])
    except Exception as e: print('TPEx err',d,e)
    return out
got=0;NS=set(NEW)
for j in range(len(D)-FK):
    full=not any(s['ff'][j] is not None for s in R['s'].values())
    if not full and not NS: continue
    if got: time.sleep(2)
    c=chips(D[FK+j])
    if len(c)<300: print('chips missing',D[FK+j],len(c));continue
    got+=1
    for sid,s in R['s'].items():
        if not full and sid not in NS: continue
        v=c.get(sid)
        if v: s['f'][j],s['ff'][j],s['ft'][j]=v
inst=sum(1 for s in R['s'].values() if s['ff'] and s['ff'][-1] is not None)
# ---- 估值：本益比、股價淨值比、殖利率（證交所＋櫃買） ----
vd=D[-1];val={}
try:
    t=fetch(f'https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date={vd.replace("-","")}&selectType=ALL&response=json')
    if t.get('stat')=='OK':
        F=t['fields'];a,b,c=F.index('本益比'),F.index('股價淨值比'),F.index('殖利率(%)')
        for r in t['data']: val[r[0].strip()]=[num(r[a]),num(r[b]),num(r[c])]
except Exception as e: print('BWIBBU err',e)
try:
    t=fetch(f'https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate?date={vd.replace("-","%2F")}&response=json')
    for tb in t.get('tables') or []:
        F=tb.get('fields') or []
        if '本益比' in F:
            a,b,c=F.index('本益比'),F.index('股價淨值比'),F.index('殖利率(%)')
            for r in tb['data']: val.setdefault(r[0].strip(),[num(r[a]),num(r[b]),num(r[c])])
except Exception as e: print('TPEx PE err',e)
if len(val)>300:
    R['vd']=vd
    for sid,s in R['s'].items():
        v=val.get(sid)
        for k in ('pe','pb','dy'): s.pop(k,None)
        if v:
            for k,x in zip(('pe','pb','dy'),v):
                if x is not None and x>0: s[k]=x
# ---- 存檔（價格差值編碼） ----
for s in R['s'].values():
    s['c']=[int(x) if isinstance(x,float) and x==int(x) else x for x in s['c']]
    for k in 'ohl': s[k]=[round((x-c)*100) for x,c in zip(s[k],s['c'])]
R['enc']=1
out=json.dumps(R,ensure_ascii=False,separators=(',',':'))
open(PATH,'w',encoding='utf8').write(out)
print('OK',D[-1],'updated',upd,'halted',halt,'stocks',len(R['s']),'new',len(NEW),'inst',inst,'chipdays',got,'val',len(val),'taiex',tx,'days',len(D),'MB',round(len(out.encode())/1e6,2))
