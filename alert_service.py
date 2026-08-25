#!/usr/bin/env python3
"""
Rocket Roy — Live Magnificent 7 Alert Service

Run:
    pip install flask flask-cors requests websockets
    python alert_service_live.py

The browser connects to ws://127.0.0.1:5001/ws.
This service connects to Finnhub's WebSocket and streams trades to the browser.
REST quote polling remains as a fallback/health mechanism.

Set:
    GMAIL_USER
    GMAIL_PASS       (Gmail App Password)
    ALERT_EMAIL      (optional)
"""

import asyncio
import json
import os
import smtplib
import threading
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
import websockets
from flask import Flask, request, jsonify
from flask_cors import CORS

FINNHUB_KEY = os.getenv("FINNHUB_KEY", "da6r941r01qqqkkgsvm0")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_PASS = os.getenv("GMAIL_PASS", "")
ALERT_EMAIL = os.getenv("ALERT_EMAIL", "roy20020904@gmail.com")

PORT = 5001
REST_INTERVAL = 30

STOCKS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]

app = Flask(__name__)
CORS(app)

positions = {}
account_size = 150.0
alert_log = []

browser_clients = set()
browser_lock = threading.Lock()


def send_email(subject, body_text, body_html=None):
    if not GMAIL_USER or not GMAIL_PASS:
        print(f"[EMAIL SKIPPED] No credentials set. Subject: {subject}")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Rocket Roy Monitor <{GMAIL_USER}>"
        msg["To"] = ALERT_EMAIL
        msg.attach(MIMEText(body_text, "plain"))
        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, ALERT_EMAIL, msg.as_string())

        print(f"[EMAIL SENT] {subject}")
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


def alert_email_html(ticker, alert_type, message, price, buy_price, account):
    color = (
        "#ef4444" if alert_type == "stop"
        else "#22c55e" if alert_type == "target"
        else "#fb923c"
    )
    icon = "🔴" if alert_type == "stop" else "💰" if alert_type == "target" else "⚠️"

    return f"""
    <div style="font-family:monospace;background:#07080f;color:#eef0f8;padding:32px;border-radius:12px;max-width:520px">
      <h2 style="color:{color};margin:0 0 6px">{icon} Rocket Roy Alert</h2>
      <p style="color:#888;font-size:13px;margin:0 0 20px">
        {datetime.now().strftime('%d %b %Y, %H:%M:%S')}
      </p>
      <div style="background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:16px;margin-bottom:16px">
        <div style="font-size:22px;font-weight:800;margin-bottom:8px">{ticker}</div>
        <div style="font-size:15px;color:{color};font-weight:600;margin-bottom:6px">{message}</div>
        <div style="font-size:13px;color:#888">
          Current: <strong style="color:#fff">${price:.2f}</strong>
          &nbsp;·&nbsp;
          Buy price: <strong style="color:#fff">${buy_price:.2f}</strong>
          &nbsp;·&nbsp;
          Account: <strong style="color:#fff">£{account:.0f}</strong>
        </div>
      </div>
      <p style="color:#444;font-size:11px;margin:0">
        Not financial advice · Rocket Roy Risk Monitor
      </p>
    </div>
    """


def log_alert(ticker, alert_type, message):
    alert_log.insert(0, {
        "ticker": ticker,
        "type": alert_type,
        "message": message,
        "time": datetime.now().strftime("%H:%M:%S"),
    })
    del alert_log[50:]
    print(f"[ALERT] {ticker} {alert_type}: {message}")


def check_rules(ticker, price, pos):
    try:
        buy = float(pos.get("buyPrice", 0) or 0)
        shares = float(pos.get("shares", 0) or 0)
    except (TypeError, ValueError):
        return

    if not buy or not shares or not price:
        return

    stop_price = buy * 0.93
    target_price = buy * 1.14
    max_risk = account_size * 0.01
    pos_risk = shares * buy * 0.07

    if pos_risk > max_risk and not pos.get("sizeFired"):
        pos["sizeFired"] = True
        max_shares = int(max_risk / (buy * 0.07))
        msg = (
            f"Position oversized for 1% risk rule. Risk £{pos_risk:.2f} "
            f"exceeds limit £{max_risk:.2f}. Suggested max: {max_shares} shares."
        )
        log_alert(ticker, "size", msg)
        send_email(
            f"⚠️ {ticker} — Position Oversized",
            msg,
            alert_email_html(ticker, "size", msg, price, buy, account_size),
        )

    if price <= stop_price and not pos.get("stopFired"):
        pos["stopFired"] = True
        chg = (price - buy) / buy * 100
        msg = (
            f"STOP LOSS — {ticker} at ${price:.2f}, down "
            f"{abs(chg):.1f}% from buy ${buy:.2f}. Sell now, don't hesitate."
        )
        log_alert(ticker, "stop", msg)
        send_email(
            f"🔴 STOP LOSS: {ticker} — Sell now",
            msg,
            alert_email_html(ticker, "stop", msg, price, buy, account_size),
        )

    if price >= target_price and not pos.get("targetFired"):
        pos["targetFired"] = True
        chg = (price - buy) / buy * 100
        msg = (
            f"2:1 TARGET HIT — {ticker} at ${price:.2f}, up "
            f"{chg:.1f}% from buy ${buy:.2f}. Consider taking profit."
        )
        log_alert(ticker, "target", msg)
        send_email(
            f"💰 TARGET HIT: {ticker} — Consider taking profit",
            msg,
            alert_email_html(ticker, "target", msg, price, buy, account_size),
        )


def process_trade(ticker, price):
    if ticker not in STOCKS:
        return

    pos = positions.get(ticker, {})
    if pos:
        check_rules(ticker, price, pos)

    message = json.dumps({
        "type": "quote",
        "ticker": ticker,
        "price": price,
        "time": datetime.now().isoformat(),
    })

    with browser_lock:
        clients = list(browser_clients)

    if clients:
        asyncio.run_coroutine_threadsafe(
            broadcast_to_clients(clients, message),
            ws_loop,
        )


async def broadcast_to_clients(clients, message):
    dead = []
    for ws in clients:
        try:
            await ws.send(message)
        except Exception:
            dead.append(ws)

    if dead:
        with browser_lock:
            for ws in dead:
                browser_clients.discard(ws)


async def finnhub_stream():
    url = f"wss://ws.finnhub.io?token={FINNHUB_KEY}"

    while True:
        try:
            print("[LIVE] Connecting to Finnhub WebSocket...")
            async with websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
            ) as ws:
                for ticker in STOCKS:
                    await ws.send(json.dumps({
                        "type": "subscribe",
                        "symbol": ticker,
                    }))

                print("[LIVE] Finnhub WebSocket connected.")
                print("[LIVE] Subscribed:", ", ".join(STOCKS))

                async for raw in ws:
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if data.get("type") != "trade":
                        continue

                    for trade in data.get("data", []):
                        ticker = trade.get("s")
                        price = trade.get("p")

                        if ticker in STOCKS and isinstance(price, (int, float)):
                            process_trade(ticker, float(price))

        except Exception as e:
            print(f"[LIVE] WebSocket disconnected: {e}")
            print("[LIVE] Reconnecting in 3 seconds...")
            await asyncio.sleep(3)


def live_loop():
    global ws_loop
    ws_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(ws_loop)
    ws_loop.run_until_complete(finnhub_stream())


def fetch_price(ticker):
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": ticker, "token": FINNHUB_KEY},
            timeout=5,
        )
        r.raise_for_status()
        d = r.json()
        return d.get("c"), d.get("o")
    except Exception as e:
        print(f"[REST] {ticker}: {e}")
        return None, None


def rest_fallback_loop():
    while True:
        time.sleep(REST_INTERVAL)

        for ticker in STOCKS:
            price, opening = fetch_price(ticker)

            if price:
                process_trade(ticker, float(price))

        print("[REST] Fallback quote refresh complete.")


@app.route("/ping")
def ping():
    return jsonify({
        "ok": True,
        "live": True,
        "time": datetime.now().isoformat(),
    })


@app.route("/positions", methods=["POST"])
def update_positions():
    global positions, account_size

    data = request.get_json(silent=True) or {}

    if "positions" in data:
        for ticker, pos in data["positions"].items():
            if ticker not in positions:
                positions[ticker] = {}

            positions[ticker].update({
                "buyPrice": pos.get("buyPrice", ""),
                "shares": pos.get("shares", ""),
            })

            # Re-arm alerts if the user changes the position.
            positions[ticker]["stopFired"] = False
            positions[ticker]["targetFired"] = False

    if "accountSize" in data:
        try:
            account_size = float(data["accountSize"]) or 150
        except (TypeError, ValueError):
            account_size = 150

    return jsonify({"ok": True})


@app.route("/alert", methods=["POST"])
def receive_alert():
    data = request.get_json(silent=True) or {}
    ticker = data.get("ticker", "")
    atype = data.get("type", "")
    msg = data.get("message", "")
    log_alert(ticker, atype, msg)
    return jsonify({"ok": True})


@app.route("/alerts")
def get_alerts():
    return jsonify(alert_log)


@app.route("/test-email", methods=["POST"])
def test_email():
    ok = send_email(
        "🚀 RocketRoy Monitor — Test Email",
        "This is a test email from your Rocket Roy Risk Dashboard. SMTP is working correctly.",
        """
        <div style="font-family:monospace;background:#07080f;color:#eef0f8;padding:32px;border-radius:12px">
          <h2 style="color:#6c63ff">🚀 Rocket Roy Live Monitor</h2>
          <p>SMTP is working correctly.</p>
          <p>You will receive alerts when risk rules are triggered.</p>
        </div>
        """,
    )
    return jsonify({"ok": ok})


async def browser_ws(websocket):
    with browser_lock:
        browser_clients.add(websocket)

    print("[BROWSER] Live dashboard connected.")

    try:
        await websocket.send(json.dumps({
            "type": "status",
            "live": True,
            "time": datetime.now().isoformat(),
        }))

        await websocket.wait_closed()
    finally:
        with browser_lock:
            browser_clients.discard(websocket)
        print("[BROWSER] Live dashboard disconnected.")


def browser_ws_loop():
    async def runner():
        async with websockets.serve(
            browser_ws,
            "127.0.0.1",
            5001,
            ping_interval=20,
            ping_timeout=20,
        ):
            print("[BROWSER] WebSocket server listening on ws://127.0.0.1:5001/ws")
            await asyncio.Future()

    asyncio.run(runner())


if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════╗
║        Rocket Roy — LIVE Alert Service          ║
║        Finnhub WebSocket + REST fallback        ║
╚══════════════════════════════════════════════════╝
""")

    if not GMAIL_USER or not GMAIL_PASS:
        print("⚠️  GMAIL_USER / GMAIL_PASS not set.")
        print("   Alerts will be logged, but email won't send.")

    # Flask HTTP API
    threading.Thread(
        target=lambda: app.run(
            host="127.0.0.1",
            port=5001,
            debug=False,
            use_reloader=False,
        ),
        daemon=True,
    ).start()

    # Browser WebSocket on the same port cannot coexist with Flask's HTTP server
    # directly. Use a combined asyncio HTTP/WebSocket server in production.
    #
    # To keep this file simple and robust, the browser websocket uses port 5002.
    # The dashboard below therefore connects to 5002.
    print("[INFO] Browser WebSocket will run on port 5002.")

    # Start browser WS on 5002.
    def run_browser_ws_5002():
        async def runner():
            async with websockets.serve(
                browser_ws,
                "127.0.0.1",
                5002,
                ping_interval=20,
                ping_timeout=20,
            ):
                print("[BROWSER] WebSocket: ws://127.0.0.1:5002")
                await asyncio.Future()
        asyncio.run(runner())

    threading.Thread(target=run_browser_ws_5002, daemon=True).start()

    # Live Finnhub stream.
    threading.Thread(target=live_loop, daemon=True).start()

    # REST fallback.
    threading.Thread(target=rest_fallback_loop, daemon=True).start()

    while True:
        time.sleep(3600)
