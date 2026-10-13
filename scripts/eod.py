"""盤後更新：收盤 K 線（證交所，缺的用 Yahoo）、外資／投信買賣超（證交所 T86＋櫃買中心）、本益比／淨值比／殖利率 → data/raw.json
用法：python3 scripts/eod.py [YYYY-MM-DD] [fill]
  fill：不新增 K 線，只整理視窗並補抓缺漏的法人與估值資料
資料格式：o/h/l 以「與收盤價的差 ×100」整數儲存（enc=1），f/ff/ft 對齊 dates[fk:]（單位：張）"""
import json,re,sys,urllib.request,datetime,time
from concurrent.futures import ThreadPoolExecutor
TZ=datetime.timezone(datetime.timedelta(hours=8))
day=sys.argv[1] if len(sys.argv)>1 and sys.argv[1] else datetime.datetime.now(TZ).strftime('%Y-%m-%d')
FILL=len(sys.argv)>2 and sys.argv[2]=='fill'
MAXD,W=160,20   # K 線保留 160 個交易日、法人保留 20 日
PATH='data/raw.json'
R=json.load(open(PATH,encoding='utf8'))
D=R['dates']
if R.get('enc'):
    for s in R['s'].values():
        for k in 'ohl': s[k]=[round(c+d/100,2) for c,d in zip(s['c'],s[k])]
SUF=lambda sid:'.TWO' if R['s'][sid].get('x')=='o' else '.TW'
if not FILL:
    if day in D: print('ALREADY',day);sys.exit(0)
    if day<D[-1]: print('OLDER',day,'<',D[-1]);sys.exit(0)
def fetch(u,n=4):
    err=None
    for k in range(n):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30))
        except Exception as e: err=e;time.sleep(3+4*k)
    raise err
def num(x):
    try: return float(str(x).replace(',',''))
    except Exception: return None
def yq(sid):
    try:
        r=fetch(f'https://query1.finance.yahoo.com/v8/finance/chart/{sid}{SUF(sid)}?interval=1d&range=1d',3)['chart']['result'][0]
        m=r['meta'];q=r['indicators']['quote'][0]
        if datetime.datetime.fromtimestamp(m['regularMarketTime'],TZ).strftime('%Y-%m-%d')!=day: return sid,None
        g=lambda k:(q.get(k) or [None])[-1];rr=lambda v:None if v is None else round(v,2)
        return sid,[rr(g('open')),rr(m.get('regularMarketDayHigh')),rr(m.get('regularMarketDayLow')),rr(m['regularMarketPrice']),round((m.get('regularMarketVolume') or 0)/1000) if m.get('regularMarketVolume') else None]
    except Exception: return sid,None
upd=halt=0;tx=None
if not FILL:
    ymd=day.replace('-','')
    try: mi=fetch(f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=ALLBUT0999&response=json')
    except Exception as e: print('MI_INDEX error',e); mi={}
    bars={}
    for t in (mi.get('tables') or []):
        f=t.get('fields') or []
        if '收盤價' in f and '證券代號' in f:
            ix={k:f.index(k) for k in ['證券代號','成交股數','開盤價','最高價','最低價','收盤價']}
            for r in t['data']:
                bars[r[ix['證券代號']].strip()]=[num(r[ix['開盤價']]),num(r[ix['最高價']]),num(r[ix['最低價']]),num(r[ix['收盤價']]),round((num(r[ix['成交股數']]) or 0)/1000)]
        if '收盤指數' in f:
            for r in t['data']:
                if str(r[0]).strip()=='發行量加權股價指數': tx=num(r[1])
    with ThreadPoolExecutor(24) as ex: Y=dict(ex.map(yq,list(R['s'])))
    print('twse bars',len(bars),'yahoo',sum(1 for v in Y.values() if v))
    for sid,y in Y.items():
        if not y: continue
        if sid in bars:
            if y[4]: bars[sid][4]=y[4]
        elif y[3]: bars[sid]=y[:4]+[y[4] or 0]
    if len(bars)<500: print('NOTRADE',day);sys.exit(0)
    if not tx:
        try:
            m=fetch('https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1d&range=1d')['chart']['result'][0]['meta']
            if datetime.datetime.fromtimestamp(m['regularMarketTime'],TZ).strftime('%Y-%m-%d')==day: tx=round(m['regularMarketPrice'],2)
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
# ---- 法人陣列對齊：f 三大法人合計、ff 外資、ft 投信（張），對應 dates[fk:] ----
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
# ---- 補抓法人：視窗內外資資料全空的日子都重抓（含首次回補） ----
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
FK=R['fk'];got=0
for j in range(len(D)-FK):
    if any(s['ff'][j] is not None for s in R['s'].values()): continue
    if got: time.sleep(2)
    c=chips(D[FK+j])
    if len(c)<300: print('chips missing',D[FK+j],len(c));continue
    got+=1
    for sid,s in R['s'].items():
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
# ---- 數字精簡：整數價格去掉 .0 ----
for s in R['s'].values():
    s['c']=[int(x) if isinstance(x,float) and x==int(x) else x for x in s['c']]
    for k in 'ohl': s[k]=[round((x-c)*100) for x,c in zip(s[k],s['c'])]
R['enc']=1
out=json.dumps(R,ensure_ascii=False,separators=(',',':'))
open(PATH,'w',encoding='utf8').write(out)
print('OK',D[-1],'updated',upd,'halted',halt,'inst',inst,'chipdays',got,'val',len(val),'taiex',tx,'days',len(D),'MB',round(len(out.encode())/1e6,2))
