"""盤後更新：把當天收盤 K 線（證交所，失敗改用 Yahoo）與三大法人買賣超補進 data/raw.json。用法：python3 scripts/eod.py [YYYY-MM-DD]"""
import json,re,sys,urllib.request,datetime,time
TZ=datetime.timezone(datetime.timedelta(hours=8))
day=sys.argv[1] if len(sys.argv)>1 else datetime.datetime.now(TZ).strftime('%Y-%m-%d')
R=json.load(open('data/raw.json',encoding='utf8'))
D=R['dates']
if day in D: print('ALREADY',day);sys.exit(0)
if day<D[-1]: print('OLDER',day,'<',D[-1]);sys.exit(0)
ymd=day.replace('-','')
def fetch(u):
    for _ in range(3):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'}),timeout=30))
        except Exception as e: err=e;time.sleep(3)
    raise err
try: mi=fetch(f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=ALLBUT0999&response=json')
except Exception as e: print('MI_INDEX error',e); mi={'stat':'ERR'}
num=lambda s:None if s is None or str(s).strip() in('','--','---','X') else float(str(s).replace(',',''))
bars={};tx=None
for t in (mi.get('tables') or []):
    f=t.get('fields') or []
    if '收盤價' in f and '證券代號' in f:
        ix={k:f.index(k) for k in ['證券代號','成交股數','開盤價','最高價','最低價','收盤價']}
        for r in t['data']:
            bars[r[ix['證券代號']].strip()]=[num(r[ix['開盤價']]),num(r[ix['最高價']]),num(r[ix['最低價']]),num(r[ix['收盤價']]),round((num(r[ix['成交股數']]) or 0)/1000)]
    if '收盤指數' in f:
        for r in t['data']:
            if str(r[0]).strip()=='發行量加權股價指數': tx=num(r[1])
from concurrent.futures import ThreadPoolExecutor
if len(bars)<500:
    # 證交所取不到（休市或被擋）：改用 Yahoo 當日 K 線
    def yb(sid):
        try:
            r=fetch(f'https://query1.finance.yahoo.com/v8/finance/chart/{sid}.TW?interval=1d&range=1d')['chart']['result'][0]
            m=r['meta'];q=r['indicators']['quote'][0]
            if datetime.datetime.fromtimestamp(m['regularMarketTime'],TZ).strftime('%Y-%m-%d')!=day: return sid,None
            g=lambda k:(q.get(k) or [None])[-1]
            return sid,[g('open'),m.get('regularMarketDayHigh'),m.get('regularMarketDayLow'),m['regularMarketPrice'],round((m.get('regularMarketVolume') or 0)/1000)]
        except Exception: return sid,None
    with ThreadPoolExecutor(24) as ex: bars={k:[None if x is None else round(x,2) for x in v[:4]]+[v[4]] for k,v in ex.map(yb,list(R['s'])) if v}
    print('Yahoo bars',len(bars))
    if len(bars)<500: print('NOTRADE',day);sys.exit(0)
    if not tx:
        try:
            m=fetch('https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1d&range=1d')['chart']['result'][0]['meta']
            if datetime.datetime.fromtimestamp(m['regularMarketTime'],TZ).strftime('%Y-%m-%d')==day: tx=round(m['regularMarketPrice'],2)
        except Exception: pass
# 成交量改用 Yahoo（與歷史資料同一來源，含零股與盤後），取不到才用證交所
def yv(sid):
    try:
        r=fetch(f'https://query1.finance.yahoo.com/v8/finance/chart/{sid}.TW?interval=1d&range=1d')['chart']['result'][0]['meta']
        if datetime.datetime.fromtimestamp(r['regularMarketTime'],TZ).strftime('%Y-%m-%d')==day and r.get('regularMarketVolume'): return sid,round(r['regularMarketVolume']/1000)
    except Exception: pass
    return sid,None
with ThreadPoolExecutor(24) as ex: YV=dict(ex.map(yv,list(R['s'])))
print('yahoo volume',sum(1 for v in YV.values() if v))
for sid,b in bars.items():
    if YV.get(sid): b[4]=YV[sid]
inst={}
try:
    t86=fetch(f'https://www.twse.com.tw/rwd/zh/fund/T86?date={ymd}&selectType=ALLBUT0999&response=json')
    if t86.get('stat')=='OK':
        fi=t86['fields'].index('三大法人買賣超股數')
        for r in t86['data']: inst[r[0].strip()]=round(num(r[fi])/1000)
except Exception as e: print('T86 err',e)
nD=len(D);D.append(day);upd=0;halt=0
for sid,s in R['s'].items():
    n=len(s['c'])
    if s['k']+n!=nD: continue          # 資料不連續（已下市等）就略過
    b=bars.get(sid);pc=s['c'][-1]
    if b and b[3]:
        o,h,l,c,v=b;o=o or c;h=h or c;l=l or c;upd+=1
    else:
        o=h=l=c=pc;v=0;halt+=1            # 停牌沿用前收盤
    for k,x in zip('ohlcv',(o,h,l,c,v)): s[k].append(x)
# 法人：s.f 對齊 dates[FK:]
FK=R['fk']
for sid,s in R['s'].items():
    f=s.get('f') or []
    need=nD-FK
    f=(f+[None]*need)[:need]
    f.append(inst.get(sid) if inst else None)
    s['f']=f
if tx: R['taiex'].append(tx)
# 視窗：最多保留 260 個交易日、法人 10 天、指數 60 天
while len(R['dates'])>260:
    R['dates'].pop(0)
    for s in R['s'].values():
        if s['k']>0: s['k']-=1
        else:
            for k in 'ohlcv': s[k].pop(0)
    R['fk']-=1
while len(R['dates'])-R['fk']>10:
    R['fk']+=1
    for s in R['s'].values(): s['f'].pop(0)
if R['fk']<0:
    for s in R['s'].values(): s['f']=s['f'][-R['fk']:]
    R['fk']=0
R['taiex']=R['taiex'][-60:]
json.dump(R,open('data/raw.json','w',encoding='utf8'),ensure_ascii=False,separators=(',',':'))
print('OK',day,'updated',upd,'halted',halt,'inst',len(inst),'taiex',tx,'days',len(R['dates']))
