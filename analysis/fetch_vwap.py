#!/usr/bin/env python3
"""Fetch daily OHLCV bars from Tencent (unadjusted, exchange-sourced) and compute
volume-weighted average price (VWAP) over the first 6 months and first 1 year of
trading for each IPO, versus the offer price. No estimation — direct from bars.
Marks availability False where the window has not yet elapsed (future date)."""
import json, urllib.request, time, datetime, sys

TODAY = datetime.date(2026, 7, 23)
d = json.load(open("output/analysis/dashboard_data.json"))
deals = d["deals"]

def fetch(code, start, end):
    url = (f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"param=hk{code},day,{start},{end},400,bfq")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=25) as r:
                j = json.loads(r.read().decode())
            node = j.get("data", {}).get(f"hk{code}", {})
            bars = node.get("day") or node.get("qfqday") or []
            return bars
        except Exception as e:
            time.sleep(0.6)
    return []

def vwap_window(bars, ipo_dt, days, offer):
    """VWAP over bars within [ipo, ipo+days]; typical price (H+L+C)/3 x volume."""
    end = ipo_dt + datetime.timedelta(days=days)
    num = den = 0.0
    last = None
    for b in bars:
        dt = datetime.date.fromisoformat(b[0])
        if dt < ipo_dt or dt > end:
            continue
        o, c, h, l, v = (float(b[1]), float(b[2]), float(b[3]), float(b[4]), float(b[5]))
        tp = (h + l + c) / 3.0
        num += tp * v
        den += v
        last = dt
    if den <= 0:
        return None, None, None
    vwap = num / den
    ret = (vwap / offer - 1.0) * 100.0
    return round(ret, 1), last, end

out = {}
n = len(deals)
for i, x in enumerate(deals):
    code = x["stock_code"]
    offer = x.get("ipo_price_hkd")
    ipo = x.get("ipo_date")
    rec = {"v6": None, "v1": None, "a6": False, "a1": False, "nbars": 0}
    if offer and ipo:
        ipo_dt = datetime.date.fromisoformat(ipo)
        end_fetch = min(ipo_dt + datetime.timedelta(days=400), TODAY)
        bars = fetch(code, ipo, end_fetch.isoformat())
        rec["nbars"] = len(bars)
        last_bar = datetime.date.fromisoformat(bars[-1][0]) if bars else None
        for days, vk, ak in ((182, "v6", "a6"), (365, "v1", "a1")):
            window_end = ipo_dt + datetime.timedelta(days=days)
            # available only if the window has fully elapsed AND bars reach near its end
            if window_end <= TODAY and last_bar and last_bar >= window_end - datetime.timedelta(days=12):
                ret, _, _ = vwap_window(bars, ipo_dt, days, offer)
                if ret is not None:
                    rec[vk] = ret
                    rec[ak] = True
        time.sleep(0.12)
    out[code] = rec
    if i % 25 == 0:
        with open("/tmp/vwap.json", "w") as f:
            json.dump(out, f)
        print(f"{i}/{n} done", flush=True)

with open("/tmp/vwap.json", "w") as f:
    json.dump(out, f)
a6 = sum(1 for v in out.values() if v["a6"])
a1 = sum(1 for v in out.values() if v["a1"])
print(f"DONE. 6m-VWAP available: {a6}/{n} · 1y-VWAP available: {a1}/{n}", flush=True)
