#!/usr/bin/env python3
"""Recompute 6m/1y VWAP for split-affected names on the ORIGINAL (offer) share basis.
A correction is applied to a window ONLY when the detected split ex-date falls inside
that window; otherwise the raw VWAP already reflects a single, consistent share basis
and is kept unchanged. Piecewise restores post-split bars by the known factor."""
import json, csv, math, urllib.request, time, datetime

TODAY = datetime.date(2026, 7, 23)
d = json.load(open("output/analysis/dashboard_data.json"))
deals = {x["stock_code"]: x for x in d["deals"]}
raw = json.load(open("/tmp/vwap.json"))
fac = {r["stock_code"]: float(r["factor"]) for r in csv.DictReader(open("output/analysis/tencent_day1.csv"))
       if r["factor"] and abs(float(r["factor"]) - 1) > 0.01}

def fetch(code, start, end):
    url = f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?param=hk{code},day,{start},{end},400,bfq"
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=25) as r:
                j = json.loads(r.read().decode())
            return j.get("data", {}).get(f"hk{code}", {}).get("day") or []
        except Exception:
            time.sleep(0.5)
    return []

def detect_ex(bars, F):
    """Ex-date index whose overnight close-to-close move matches ln(F) tightly."""
    target = math.log(F)
    if abs(target) < 0.30:          # move too small to distinguish from normal volatility
        return None
    best_i, best_err = None, 0.12
    for t in range(1, len(bars)):
        pc, cc = float(bars[t-1][2]), float(bars[t][2])
        if pc <= 0 or cc <= 0:
            continue
        err = abs((math.log(pc) - math.log(cc)) - target)
        if err < best_err:
            best_err, best_i = err, t
    return best_i

def vwap_piecewise(bars, ipo_dt, days, offer, F, ex_date):
    end = ipo_dt + datetime.timedelta(days=days)
    num = den = 0.0
    for b in bars:
        dt = datetime.date.fromisoformat(b[0])
        if dt < ipo_dt or dt > end:
            continue
        c, h, l, v = float(b[2]), float(b[3]), float(b[4]), float(b[5])
        tp = (h + l + c) / 3.0
        num += tp * v
        den += (v / F) if dt >= ex_date else v
    return round((num / den / offer - 1.0) * 100.0, 1) if den > 0 else None

out = {}
for code, F in fac.items():
    x = deals.get(code)
    if not x:
        continue
    offer, ipo = x.get("ipo_price_hkd"), x.get("ipo_date")
    if not (offer and ipo):
        continue
    ipo_dt = datetime.date.fromisoformat(ipo)
    r0 = raw.get(code, {})
    v6, v1 = r0.get("v6"), r0.get("v1")           # start from raw
    bars = fetch(code, ipo, min(ipo_dt + datetime.timedelta(days=400), TODAY).isoformat())
    ex_i = detect_ex(bars, F) if bars else None
    ex_date = datetime.date.fromisoformat(bars[ex_i][0]) if ex_i is not None else None
    changed = []
    if ex_date is not None:
        if r0.get("a6") and ex_date <= ipo_dt + datetime.timedelta(days=182):
            nv = vwap_piecewise(bars, ipo_dt, 182, offer, F, ex_date)
            if nv is not None: v6, changed = nv, changed + ["6m"]
        if r0.get("a1") and ex_date <= ipo_dt + datetime.timedelta(days=365):
            nv = vwap_piecewise(bars, ipo_dt, 365, offer, F, ex_date)
            if nv is not None: v1, changed = nv, changed + ["1y"]
    out[code] = {"v6": v6, "v1": v1}
    tag = f"ex={ex_date} fixed={changed}" if changed else ("ex outside window" if ex_date else "no ex within life")
    print(f"{code:>6} F={F:<6} raw(v6={r0.get('v6')},v1={r0.get('v1')}) -> (v6={v6},v1={v1})  [{tag}]", flush=True)
    time.sleep(0.12)

json.dump(out, open("/tmp/vwap_fix.json", "w"))
print("corrections written:", len(out))
