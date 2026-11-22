#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одна проверка скидки USDT за запуск (для GitHub Actions).
Состояние между запусками хранится в state.json, история — в log.csv.
Ничего не торгует, ключей кошелька не знает."""
import csv, json, os, time, urllib.request
from datetime import datetime, timezone, timedelta

TG_TOKEN = os.environ.get("TG_TOKEN", "")
TG_CHAT = os.environ.get("TG_CHAT", "")

BUY_BELOW = 0.04      # %: скидка USDT ≤ → выгодно менять USDT → USDC/USDG
SELL_ABOVE = 0.15     # %: скидка USDT ≥ → выгодно менять USDG/USDC → USDT
HYSTERESIS = 0.02
CONFIRM_CHECKS = 2
EKB = timezone(timedelta(hours=5))

POOLS = [
    {"name": "XL USDG/USDT0", "net": "x-layer", "addr": "0x0cbe0dbe1400e57f371a38bd3b9bc80f7c3676da", "kind": "usdt", "main": True},
    {"name": "ETH USDC/USDT", "net": "eth", "addr": "0x3416cf6c708da44db2624d63ea0aaef7113527c6", "kind": "usdt"},
    {"name": "XL USDG/USDC", "net": "x-layer", "addr": "0xbb9a35f790ea6ea9763b99e885f33bcf95860d40", "kind": "par", "invert": True},
]
API = "https://api.geckoterminal.com/api/v2/networks/{net}/pools/{addr}"


def fetch(pool):
    req = urllib.request.Request(API.format(**pool), headers={"Accept": "application/json", "User-Agent": "usdt-watch/1.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        p = float(json.load(r)["data"]["attributes"]["base_token_price_quote_token"])
    return 1 / p if pool.get("invert") else p


def tg(text):
    if not TG_TOKEN or not TG_CHAT:
        print("[TG не настроен]", text); return
    req = urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                                 data=json.dumps({"chat_id": TG_CHAT, "text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()


def main():
    st = {"state": "neutral", "buy": 0, "sell": 0, "par_alert": False}
    if os.path.exists("state.json"):
        st.update(json.load(open("state.json")))
    now = datetime.now(EKB).strftime("%Y-%m-%d %H:%M")
    vals = {}
    for p in POOLS:
        try:
            vals[p["name"]] = (fetch(p) - 1) * 100
        except Exception as e:
            print(p["name"], "ошибка:", e)
        time.sleep(2)

    new = not os.path.exists("log.csv")
    with open("log.csv", "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time_ekb"] + [p["name"] for p in POOLS])
        w.writerow([now] + [f"{vals[p['name']]:.4f}" if p["name"] in vals else "" for p in POOLS])

    line = "  ".join(f"{k}: {v:+.3f}%" for k, v in vals.items())
    print(now, line)
    d = vals.get("XL USDG/USDT0")
    if d is not None:
        st["buy"] = st["buy"] + 1 if d <= BUY_BELOW else 0
        st["sell"] = st["sell"] + 1 if d >= SELL_ABOVE else 0
        s = st["state"]
        if s != "buy" and st["buy"] >= CONFIRM_CHECKS:
            st["state"] = "buy"
            tg(f"🟢 Скидка USDT {d:.3f}% (≤{BUY_BELOW}%). Хороший момент менять USDT0 → USDC/USDG (проскальзывание 0,1%).\n{line}")
        elif s != "sell" and st["sell"] >= CONFIRM_CHECKS:
            st["state"] = "sell"
            tg(f"🔴 Скидка USDT {d:.3f}% (≥{SELL_ABOVE}%). Менять в USDG/USDC сейчас дорого; если нужен USDT — выгодный момент продать USDG/USDC.\n{line}")
        elif s == "buy" and d > BUY_BELOW + HYSTERESIS:
            st["state"] = "neutral"; tg(f"⚪ Скидка USDT вернулась к {d:.3f}% — окно для покупки закрылось.")
        elif s == "sell" and d < SELL_ABOVE - HYSTERESIS:
            st["state"] = "neutral"; tg(f"⚪ Скидка USDT опустилась до {d:.3f}% — окно для продажи закрылось.")

    par = vals.get("XL USDG/USDC")
    if par is not None:
        if abs(par) > 0.3 and not st["par_alert"]:
            st["par_alert"] = True; tg(f"⚠️ USDG отклонился от USDC на {par:+.3f}% — проверить.")
        elif abs(par) < 0.2:
            st["par_alert"] = False
    json.dump(st, open("state.json", "w"))


if __name__ == "__main__":
    main()
