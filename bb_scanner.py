"""
bb_scanner.py

Scanner Bollinger Bands mean-reversion, independant de MT4.
Concu pour tourner via GitHub Actions (cron), pas besoin que ton PC soit allume.

Parametres identiques a l'indicateur MT4 :
  BB Period = 15, Deviation = 2.5, timeframe H4

Source de donnees : Yahoo Finance (via yfinance), gratuit, sans cle API.
Alertes envoyees par Telegram.
"""

import os
import json
import numpy as np
import pandas as pd
import yfinance as yf
import requests
from datetime import datetime, timezone

# --------------------------- CONFIG ------------------------------------

# 20 paires (format Yahoo Finance). Cle = symbole affiche, valeur = ticker Yahoo.
SYMBOLS = {
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X", "USDCAD": "USDCAD=X", "AUDUSD": "AUDUSD=X",
    "NZDUSD": "NZDUSD=X", "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X",
    "EURCHF": "EURCHF=X", "EURCAD": "EURCAD=X", "EURAUD": "EURAUD=X",
    "EURNZD": "EURNZD=X", "GBPJPY": "GBPJPY=X", "GBPCHF": "GBPCHF=X",
    "GBPCAD": "GBPCAD=X", "GBPAUD": "GBPAUD=X", "GBPNZD": "GBPNZD=X",
    "AUDJPY": "AUDJPY=X", "CHFJPY": "CHFJPY=X",
}

BB_PERIOD = 15
BB_DEVIATION = 2.5
SUGGESTED_SL_PIPS = 40
SUGGESTED_RR = 1.5

STATE_FILE = "state.json"

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


# --------------------------- HELPERS ------------------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram non configure (secrets manquants), message non envoye:")
        print(message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15)
        if r.status_code != 200:
            print(f"Erreur Telegram: {r.status_code} {r.text}")
    except Exception as e:
        print(f"Exception envoi Telegram: {e}")


def pip_size(symbol):
    return 0.01 if "JPY" in symbol else 0.0001


def get_h4_data(yahoo_ticker):
    """Telecharge des bougies 1H recentes et les regroupe en bougies H4."""
    df = yf.download(yahoo_ticker, period="60d", interval="1h", progress=False, auto_adjust=False)
    if df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    h4 = df.resample("4h").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last"}).dropna()
    return h4


def bollinger(df, period, deviation):
    ma = df["Close"].rolling(period).mean()
    std = df["Close"].rolling(period).std()
    upper = ma + deviation * std
    lower = ma - deviation * std
    return ma, upper, lower


# --------------------------- MAIN SCAN ------------------------------------

def scan():
    state = load_state()
    alerts_sent = 0

    for symbol, ticker in SYMBOLS.items():
        try:
            h4 = get_h4_data(ticker)
            if h4 is None or len(h4) < BB_PERIOD + 5:
                print(f"{symbol}: donnees insuffisantes, ignore.")
                continue

            ma, upper, lower = bollinger(h4, BB_PERIOD, BB_DEVIATION)

            last_closed = h4.iloc[-2]  # derniere bougie H4 completement cloturee
            last_time = h4.index[-2]
            last_upper = upper.iloc[-2]
            last_lower = lower.iloc[-2]
            last_mid = ma.iloc[-2]

            if pd.isna(last_upper) or pd.isna(last_lower):
                continue

            direction = None
            if last_closed["Close"] < last_lower:
                direction = "ACHAT (rebond attendu depuis la bande basse)"
            elif last_closed["Close"] > last_upper:
                direction = "VENTE (retour attendu depuis la bande haute)"

            last_time_str = str(last_time)
            already_alerted = state.get(symbol) == last_time_str

            if direction and not already_alerted:
                pip = pip_size(symbol)
                price = last_closed["Close"]
                is_buy = "ACHAT" in direction
                sl = price - SUGGESTED_SL_PIPS * pip if is_buy else price + SUGGESTED_SL_PIPS * pip
                tp = price + SUGGESTED_SL_PIPS * SUGGESTED_RR * pip if is_buy else price - SUGGESTED_SL_PIPS * SUGGESTED_RR * pip

                msg = (
                    f"SIGNAL {symbol} (H4)\n"
                    f"{direction}\n"
                    f"Cloture: {price:.5f}\n"
                    f"Bande haute/basse: {last_upper:.5f} / {last_lower:.5f}\n"
                    f"Moyenne (cible retour): {last_mid:.5f}\n"
                    f"--- suggestions (pas d'ordre envoye) ---\n"
                    f"SL suggere: {sl:.5f} ({SUGGESTED_SL_PIPS} pips)\n"
                    f"TP suggere: {tp:.5f}\n"
                    f"Bougie: {last_time_str} UTC"
                )
                print(msg)
                send_telegram(msg)
                alerts_sent += 1

            state[symbol] = last_time_str

        except Exception as e:
            print(f"{symbol}: erreur pendant le scan - {e}")

    save_state(state)
    print(f"Scan termine : {alerts_sent} alerte(s) envoyee(s). {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    scan()
