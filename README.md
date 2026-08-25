# 🚀 rocket-roy — Risk Dashboard

Real-time monitoring dashboard for stocks with automated email alerts.

## Quick start

### 1 — Open the dashboard
Just open `dashboard.html` in your browser. No server needed for the frontend. or https://yourusername.github.io/rocket-roy/dashboard.html using github pages

### 2 — Start the alert backend (for email alerts)

Install dependencies once:
```bash
pip install flask flask-cors requests
```

Set your Gmail credentials as environment variables:
```bash
export GMAIL_USER=your@gmail.com
export GMAIL_PASS=zyzbfneibupamsmm
export ALERT_EMAIL=roy20020904@gmail.com
```

Then run:
```bash
python alert_service.py
```

The backend runs on http://localhost:5001. The dashboard shows **Backend online** when it's running.

### 3 — Test email
Click the **✉ Test email** button in the dashboard header to verify SMTP is working.

---

## How it works

- Dashboard fetches live prices from Finnhub every 30 seconds
- Enter a **Buy Price** and **Shares Held** on any stock card to arm the risk engine
- Alert service polls prices every 30 seconds independently (works even with browser closed)
- Emails fire automatically when rules are triggered

## Risk rules

| Rule | Trigger |
|------|---------|
| Stop loss | Price drops ≥ 7% below buy price |
| 2:1 target | Price rises ≥ 14% above buy price |
| Position size | (shares × 7% of buy) exceeds 1% of account |
| Max risk/trade | 1% of account size |

Alerts fire **once per position** and re-arm when buy price or shares are changed.

---

## Disclaimer
Not financial advice. Local personal use only. API key and credentials are in plain text — do not share or host publicly.
