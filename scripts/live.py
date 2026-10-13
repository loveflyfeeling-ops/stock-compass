"""盤中報價：先試證交所 MIS（即時），失敗改用 Yahoo Finance（約延遲 20 分鐘）。
輸出 data/live.json：{t, day, n, src, ix:[價,開,高,低,量,昨收,時間], q:{代號:[價,開,高,低,量(張),昨收,時間]}}"""
import json, sys, time, datetime, urllib.request
from concurrent.futures import ThreadPoolExecutor
TZ = datetime.timezone(datetime.timedelta(hours=8))
UA = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://mis.twse.com.tw/stock/index.jsp'}
ids = list(json.load(open('data/raw.json', encoding='utf8'))['s'])
try: old = json.load(open('data/live.json', encoding='utf8'))
except Exception: old = {}
r2 = lambda x: None if x is None else round(x, 2)
def num(s):
    try:
        v = float(str(s).split('_')[0]); return v if v > 0 else None
    except Exception: return None
def get_json(u, timeout=20):
    return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout))

def from_mis():
    q = {}; ix = None
    chans = ['tse_%s.tw' % i for i in ids]
    def batch(ch):
        for _ in range(2):
            try: return get_json('https://mis.twse.com.tw/stock/api/getStockInfo.jsp?json=1&delay=0&ex_ch=' + '|'.join(ch)).get('msgArray', [])
            except Exception: time.sleep(2)
        return []
    groups = [chans[i:i+80] for i in range(0, len(chans), 80)] + [['tse_t00.tw']]
    with ThreadPoolExecutor(6) as ex:
        for arr in ex.map(batch, groups):
            for m in arr:
                p = num(m.get('z')) or num(m.get('pz')) or num(m.get('b'))
                if not p: continue
                row = [r2(p), r2(num(m.get('o'))), r2(num(m.get('h'))), r2(num(m.get('l'))),
                       int(float(m.get('v') or 0)), r2(num(m.get('y'))), int(int(m.get('tlong', 0)) / 1000)]
                if m.get('c') == 't00': ix = row
                else: q[m.get('c')] = row
    return q, ix

def yahoo(sym):
    u = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=1d'
    for _ in range(3):
        try:
            r = get_json(u, 15)['chart']['result'][0]; m = r['meta']; qq = r['indicators']['quote'][0]
            o = (qq.get('open') or [None])[-1]
            return [r2(m['regularMarketPrice']), r2(o), r2(m.get('regularMarketDayHigh')), r2(m.get('regularMarketDayLow')),
                    round((m.get('regularMarketVolume') or 0) / 1000), r2(m.get('chartPreviousClose')), m['regularMarketTime']]
        except Exception: time.sleep(1)

def from_yahoo():
    with ThreadPoolExecutor(24) as ex: res = dict(zip(ids, ex.map(lambda i: yahoo(i + '.TW'), ids)))
    return {k: v for k, v in res.items() if v}, yahoo('%5ETWII')

src = 'twse'
try: q, ix = from_mis()
except Exception as e: print('MIS error', e); q, ix = {}, None
if len(q) < 0.8 * len(ids):
    print('MIS got', len(q), '-> fallback Yahoo'); src = 'yahoo'; q, ix = from_yahoo()
if len(q) < 0.8 * len(ids): print('FAIL', len(q)); sys.exit(1)
t = max(v[6] for v in q.values())
if t <= old.get('t', 0): print('NOCHANGE', datetime.datetime.fromtimestamp(t, TZ)); sys.exit(0)
day = datetime.datetime.fromtimestamp(t, TZ).strftime('%Y-%m-%d')
json.dump({'t': t, 'day': day, 'n': len(q), 'src': src, 'ix': ix, 'q': q}, open('data/live.json', 'w', encoding='utf8'), separators=(',', ':'))
print('OK', src, len(q), datetime.datetime.fromtimestamp(t, TZ).strftime('%Y-%m-%d %H:%M'))
