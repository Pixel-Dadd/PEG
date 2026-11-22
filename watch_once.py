#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Одна проверка скидки USDT за запуск (для GitHub Actions).
Сигнал считается по МЕДИАНЕ последних 3 проверок — одиночные всплески не срабатывают.
Состояние хранится в state.json, история — в log.csv. Ничего не торгует."""
import csv, json, os, statistics, time, urllib.request
from datetime import datetime, timezone, timedelta

TG_TOKEN = os.environ.get("TG_TOKEN", "")
TG_CHAT = os.environ.get("TG_CHAT", "")

BUY_BELOW = 0.04     # %: скидка USDT ≤ → выгодно менять USDT0 → USDC/USDG
SELL_ABOVE = 0.15    # %: скидка USDT ≥ → выгодно менять USDC/USDG → USDT0
HYSTERESIS = 0.02    # %: зазор для сообщения «окно закрылось»
WINDOW = 3           # по скольким последним проверкам считать медиану
EKB = timezone(timedelta(hours=5))

POOLS = [
    {"name": "XL USDG/USDT0", "net": "x-layer", "addr": "0x0cbe0dbe1400e57f371a38bd3b9bc80f7c3676da"},
    {"name": "ETH USDC/USDT", "net": "eth", "addr": "0x3416cf6c708da44db2624d63ea0aaef7113527c6"},
    {"name": "XL USDG/USDC", "net": "x-layer", "addr": "0xbb9a35f790ea6ea9763b99e885f33bcf95860d40", "invert": True},
]
MAIN = "XL USDG/USDT0"
PAR = "XL USDG/USDC"
API = "https://api.geckoterminal.com/api/v2/networks/{net}/pools/{addr}"


def fetch(pool):
    for attempt in range(3):
        try:
            req = urllib.request.Request(API.format(**pool), headers={"Accept": "application/json", "User-Agent": "usdt-watch/1.2"})
            with urllib.request.urlopen(req, timeout=20) as r:
                p = float(json.load(r)["data"]["attributes"]["base_token_price_quote_token"])
            return 1 / p if pool.get("invert") else p
        except Exception as e:
            print(pool["name"], "попытка", attempt + 1, "ошибка:", e)
            time.sleep(10)
    return None


def tg(text):
    if not TG_TOKEN or not TG_CHAT:
        print("[TG не настроен]", text); return
    req = urllib.request.Request(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                                 data=json.dumps({"chat_id": TG_CHAT, "text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()


def main():
    st = {"state": "neutral", "hist": [], "par_alert": False}
    if os.path.exists("state.json"):
        st.update(json.load(open("state.json")))
    st.setdefault("hist", [])
    now = datetime.now(EKB).strftime("%Y-%m-%d %H:%M")

    vals = {}
    for p in POOLS:
        price = fetch(p)
        if price is not None:
            vals[p["name"]] = (price - 1) * 100
        time.sleep(2)

    new = not os.path.exists("log.csv")
    with open("log.csv", "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time_ekb"] + [p["name"] for p in POOLS])
        w.writerow([now] + [f"{vals[p['name']]:.4f}" if p["name"] in vals else "" for p in POOLS])
    print(now, vals)

    d = vals.get(MAIN)
    if d is not None and abs(d) < 1:          # отбрасываем явные выбросы (>1%)
        st["hist"] = (st["hist"] + [d])[-WINDOW:]
    if len(st["hist"]) >= WINDOW:
        m = statistics.median(st["hist"])
        s = st["state"]
        if s != "buy" and m <= BUY_BELOW:
            st["state"] = "buy"
            tg(f"🟢 USDT подешевел меньше обычного: скидка {m:.3f}%\n"
               f"Можно менять USDT0 → USDC/USDG. Сверь курс в Uniswap на 500 USDT0.")
        elif s != "sell" and m >= SELL_ABOVE:
            st["state"] = "sell"
            tg(f"🔴 USDT сильно дешевле USDG: скидка {m:.3f}%\n"
               f"Менять USDT0 → USDG сейчас дорого. Если нужен USDT — выгодно продать USDG/USDC.")
        elif s == "buy" and m > BUY_BELOW + HYSTERESIS:
            st["state"] = "neutral"
            tg(f"⚪ Окно для покупки закрылось: скидка USDT {m:.3f}%")
        elif s == "sell" and m < SELL_ABOVE - HYSTERESIS:
            st["state"] = "neutral"
            tg(f"⚪ Окно для продажи закрылось: скидка USDT {m:.3f}%")

    par = vals.get(PAR)
    if par is not None:
        if abs(par) > 0.3 and not st["par_alert"]:
            st["par_alert"] = True
            tg(f"⚠️ USDG отошёл от USDC на {par:+.3f}% — проверить, что с USDG.")
        elif abs(par) < 0.2:
            st["par_alert"] = False

    json.dump(st, open("state.json", "w"))


if __name__ == "__main__":
    main()
