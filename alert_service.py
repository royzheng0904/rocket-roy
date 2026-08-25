#!/usr/bin/env python3
"""
Magnificent 7 — Alert Service
Run: python alert_service.py
Requires: pip install flask flask-cors requests
"""

import time, json, smtplib, threading, requests, os
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify
from flask_cors import CORS

# ── Config ──────────────────────────────────────────────
FINNHUB_KEY   = 'da6r941r01qqqkkgsvm0'
SMTP_HOST     = 'smtp.gmail.com'
SMTP_PORT     = 587
GMAIL_USER    = os.getenv('GMAIL_USER', '')   # set env var or hardcode here
GMAIL_PASS    = os.getenv('GMAIL_PASS', '')   # use Gmail App Password
ALERT_EMAIL   = os.getenv('ALERT_EMAIL', 'roy20020904@gmail.com')
POLL_INTERVAL = 30   # seconds
PORT          = 5001
# ────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)

positions   = {}   # { ticker: { buyPrice, shares, stopFired, targetFired } }
account_size = 150
alert_log   = []

STOCKS = ['AAPL','MSFT','GOOGL','AMZN','NVDA','META','TSLA']

# ── Email ────────────────────────────────────────────────
def send_email(subject, body_text, body_html=None):
    if not GMAIL_USER or not GMAIL_PASS:
        print(f'[EMAIL SKIPPED] No credentials set. Subject: {subject}')
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f'Mag7 Monitor <{GMAIL_USER}>'
        msg['To']      = ALERT_EMAIL
        msg.attach(MIMEText(body_text, 'plain'))
        if body_html:
            msg.attach(MIMEText(body_html, 'html'))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, ALERT_EMAIL, msg.as_string())
        print(f'[EMAIL SENT] {subject}')
        return True
    except Exception as e:
        print(f'[EMAIL ERROR] {e}')
        return False


def alert_email_html(ticker, alert_type, message, price, buy_price, account):
    color = '#ef4444' if alert_type == 'stop' else '#22c55e' if alert_type == 'target' else '#fb923c'
    icon  = '🔴' if alert_type == 'stop' else '💰' if alert_type == 'target' else '⚠️'
    return f"""
    <div style="font-family:monospace;background:#07080f;color:#eef0f8;padding:32px;border-radius:12px;max-width:520px">
      <h2 style="color:{color};margin:0 0 6px">{icon} Magnificent 7 Alert</h2>
      <p style="color:#888;font-size:13px;margin:0 0 20px">{datetime.now().strftime('%d %b %Y, %H:%M')}</p>
      <div style="background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:16px;margin-bottom:16px">
        <div style="font-size:22px;font-weight:800;margin-bottom:8px">{ticker}</div>
        <div style="font-size:15px;color:{color};font-weight:600;margin-bottom:6px">{message}</div>
        <div style="font-size:13px;color:#888">
          Current: <strong style="color:#fff">${price:.2f}</strong> &nbsp;·&nbsp;
          Buy price: <strong style="color:#fff">${buy_price:.2f}</strong> &nbsp;·&nbsp;
          Account: <strong style="color:#fff">£{account:.0f}</strong>
        </div>
      </div>
      <p style="color:#444;font-size:11px;margin:0">Not financial advice · Mag7 Risk Monitor</p>
    </div>"""


# ── Price fetching ───────────────────────────────────────
def fetch_price(ticker):
    try:
        r = requests.get(
            f'https://finnhub.io/api/v1/quote',
            params={'symbol': ticker, 'token': FINNHUB_KEY},
            timeout=5
        )
        d = r.json()
        return d.get('c'), d.get('o')
    except:
        return None, None


# ── Rules check ─────────────────────────────────────────
def check_rules(ticker, price, pos):
    buy   = float(pos.get('buyPrice', 0) or 0)
    shares = float(pos.get('shares', 0) or 0)
    if not buy or not shares or not price:
        return

    stop_price   = buy * 0.93
    target_price = buy * 1.14
    max_risk     = account_size * 0.01
    pos_risk     = shares * buy * 0.07

    # Position size — one-time
    if pos_risk > max_risk and not pos.get('sizeFired'):
        pos['sizeFired'] = True
        max_shares = int(max_risk / (buy * 0.07))
        msg = f'Position oversized for 1% risk rule. Risk £{pos_risk:.2f} exceeds limit £{max_risk:.2f}. Suggested max: {max_shares} shares.'
        log_alert(ticker, 'size', msg)
        send_email(
            f'⚠️ {ticker} — Position Oversized',
            msg,
            alert_email_html(ticker, 'size', msg, price, buy, account_size)
        )

    # Stop loss
    if price <= stop_price and not pos.get('stopFired'):
        pos['stopFired'] = True
        chg = ((price - buy) / buy * 100)
        msg = f"STOP LOSS — {ticker} at ${price:.2f}, down {abs(chg):.1f}% from buy ${buy:.2f}. Sell now, don't hesitate."
        log_alert(ticker, 'stop', msg)
        send_email(
            f'🔴 STOP LOSS: {ticker} — Sell now',
            msg,
            alert_email_html(ticker, 'stop', msg, price, buy, account_size)
        )

    # 2:1 Target
    if price >= target_price and not pos.get('targetFired'):
        pos['targetFired'] = True
        chg = ((price - buy) / buy * 100)
        msg = f"2:1 TARGET HIT — {ticker} at ${price:.2f}, up {chg:.1f}% from buy ${buy:.2f}. Consider taking profit."
        log_alert(ticker, 'target', msg)
        send_email(
            f'💰 TARGET HIT: {ticker} — Consider taking profit',
            msg,
            alert_email_html(ticker, 'target', msg, price, buy, account_size)
        )


def log_alert(ticker, alert_type, message):
    alert_log.insert(0, {
        'ticker': ticker, 'type': alert_type,
        'message': message,
        'time': datetime.now().strftime('%H:%M')
    })
    if len(alert_log) > 50:
        alert_log.pop()
    print(f'[ALERT] {ticker} {alert_type}: {message}')


# ── Poll loop ────────────────────────────────────────────
def poll_loop():
    while True:
        for ticker in STOCKS:
            pos = positions.get(ticker, {})
            if not pos.get('buyPrice'):
                continue
            price, _ = fetch_price(ticker)
            if price:
                check_rules(ticker, price, pos)
        time.sleep(POLL_INTERVAL)


# ── API routes ───────────────────────────────────────────
@app.route('/ping')
def ping():
    return jsonify({'ok': True, 'time': datetime.now().isoformat()})


@app.route('/positions', methods=['POST'])
def update_positions():
    global positions, account_size
    data = request.json
    if 'positions' in data:
        for ticker, pos in data['positions'].items():
            if ticker not in positions:
                positions[ticker] = {}
            positions[ticker].update({
                'buyPrice': pos.get('buyPrice', ''),
                'shares':   pos.get('shares', ''),
            })
    if 'accountSize' in data:
        account_size = float(data['accountSize']) or 150
    return jsonify({'ok': True})


@app.route('/alert', methods=['POST'])
def receive_alert():
    data = request.json
    ticker = data.get('ticker','')
    atype  = data.get('type','')
    msg    = data.get('message','')
    log_alert(ticker, atype, msg)
    return jsonify({'ok': True})


@app.route('/alerts')
def get_alerts():
    return jsonify(alert_log)


@app.route('/test-email', methods=['POST'])
def test_email():
    ok = send_email(
        '🚀 RocketRoy Monitor — Test Email',
        'This is a test email from your Rocket Roy Risk Dashboard. SMTP is working correctly.',
        '<div style="font-family:monospace;background:#07080f;color:#eef0f8;padding:32px;border-radius:12px"><h2 style="color:#6c63ff">🚀 Mag7 Monitor</h2><p>SMTP is working correctly. You will receive alerts when risk rules are triggered.</p><p style="color:#444;font-size:12px;margin-top:16px">Not financial advice.</p></div>'
    )
    return jsonify({'ok': ok})


# ── Main ─────────────────────────────────────────────────
if __name__ == '__main__':
    print(f'''
╔══════════════════════════════════════════╗
║   Rocket Roy — Alert Service          ║
║   Polling every {POLL_INTERVAL}s on port {PORT}           ║
║   Email → {ALERT_EMAIL[:30]}  ║
╚══════════════════════════════════════════╝
    ''')
    if not GMAIL_USER or not GMAIL_PASS:
        print('⚠️  WARNING: GMAIL_USER / GMAIL_PASS not set.')
        print('   Set env vars or edit the config at the top of this file.')
        print('   Alerts will be logged but emails will NOT be sent.\n')

    t = threading.Thread(target=poll_loop, daemon=True)
    t.start()
    app.run(host='127.0.0.1', port=PORT, debug=False)
