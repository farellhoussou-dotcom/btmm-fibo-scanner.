"""
Scanner Fibonacci 61.8% multi-paires.

Pour chaque paire :
  - Point A = le plus bas des DAYS_LOOKBACK derniers jours (D1)
  - Point B = le plus haut des DAYS_LOOKBACK derniers jours (D1)
  - Le sens (haussier/baissier) est donne par lequel des deux (haut ou bas)
    s'est forme le plus RECEMMENT chronologiquement.
  - Niveau 61.8% = A * 0.618 + B * 0.382
  - "Tester le niveau" = la bougie M15 en cours touche ce niveau
    (avec une tolerance en pips).

Une alerte Telegram est envoyee uniquement au moment ou une paire PASSE
de "pas en test" a "en test" (pas de spam a chaque execution).

Donnees de prix : Yahoo Finance (gratuit, sans cle API), via yfinance.
"""

import os
import sys
import json
from datetime import datetime, timezone

import requests
import yfinance as yf

# --- Paires surveillees (nom affiche -> ticker Yahoo Finance) -------------
PAIRS = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X",
    "AUDUSD": "AUDUSD=X",
    "NZDUSD": "NZDUSD=X",
    "USDCAD": "USDCAD=X",
    "EURGBP": "EURGBP=X",
    "EURJPY": "EURJPY=X",
    "GBPJPY": "GBPJPY=X",
    "GBPCHF": "GBPCHF=X",
    "GBPCAD": "GBPCAD=X",
    "EURCHF": "EURCHF=X",
    "AUDJPY": "AUDJPY=X",
    "XAUUSD": "XAUUSD=X",
}

# --- Parametres (modifiables via variables d'environnement) ---------------
DAYS_LOOKBACK = int(os.environ.get("DAYS_LOOKBACK", "2"))
TOLERANCE_PIPS = float(os.environ.get("TOLERANCE_PIPS", "3.0"))
STATE_FILE = "state.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def pip_size(name: str) -> float:
    """Taille d'un pip selon le type de paire."""
    if "JPY" in name:
        return 0.01
    if name == "XAUUSD":
        return 0.1
    return 0.0001


def get_daily_high_low(ticker: str, days: int):
    """Retourne (high_val, high_date, low_val, low_date) sur les `days`
    derniers jours cloturees (exclut la bougie du jour en cours, potentiellement
    incomplete)."""
    data = yf.Ticker(ticker).history(period=f"{days + 5}d", interval="1d")
    if data.empty or len(data) < days + 1:
        return None

    completed = data.iloc[:-1]  # on retire la derniere ligne (jour en cours)
    recent = completed.tail(days)
    if recent.empty:
        return None

    high_val = float(recent["High"].max())
    high_date = recent["High"].idxmax()
    low_val = float(recent["Low"].min())
    low_date = recent["Low"].idxmin()
    return high_val, high_date, low_val, low_date


def get_current_m15(ticker: str):
    """Retourne (high, low) de la derniere bougie M15 disponible."""
    data = yf.Ticker(ticker).history(period="2d", interval="15m")
    if data.empty:
        return None
    last = data.iloc[-1]
    return float(last["High"]), float(last["Low"])


def compute_level(high_val, high_date, low_val, low_date):
    """Calcule le niveau 61.8% et le sens du mouvement."""
    if low_date > high_date:
        # le creux est plus recent -> mouvement baissier menant a ce creux
        A, B = high_val, low_val
        bullish = False
    else:
        # le sommet est plus recent -> mouvement haussier menant a ce sommet
        A, B = low_val, high_val
        bullish = True

    level = A * 0.618 + B * 0.382
    return level, bullish


def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ATTENTION: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID manquants, alerte non envoyee.", file=sys.stderr)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=15)
        if resp.status_code != 200:
            print(f"Erreur Telegram ({resp.status_code}): {resp.text}", file=sys.stderr)
    except Exception as e:
        print(f"Erreur envoi Telegram: {e}", file=sys.stderr)


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def main():
    state = load_state()
    new_state = {}
    alerts = []

    for name, ticker in PAIRS.items():
        try:
            daily = get_daily_high_low(ticker, DAYS_LOOKBACK)
            m15 = get_current_m15(ticker)
            if daily is None or m15 is None:
                print(f"{name}: donnees insuffisantes, ignore.")
                continue

            high_val, high_date, low_val, low_date = daily
            level, bullish = compute_level(high_val, high_date, low_val, low_date)
            cur_high, cur_low = m15

            tol = TOLERANCE_PIPS * pip_size(name)
            testing = (cur_low - tol) <= level <= (cur_high + tol)

            new_state[name] = bool(testing)
            was_testing = bool(state.get(name, False))

            sens = "Haussier (rebond attendu)" if bullish else "Baissier (rejet attendu)"
            print(f"{name}: niveau 61.8%={level:.5f} | sens={sens} | testing={testing}")

            if testing and not was_testing:
                alerts.append(
                    f"{name} | Test du niveau Fibonacci 61.8%\n"
                    f"Sens: {sens}\n"
                    f"Niveau 61.8%: {level:.5f}\n"
                    f"Range utilisee: {DAYS_LOOKBACK} derniers jours\n"
                    f"Heure: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
                )
        except Exception as e:
            print(f"Erreur sur {name}: {e}", file=sys.stderr)

    for alert in alerts:
        send_telegram(alert)
        print("ALERTE ENVOYEE:\n" + alert)

    save_state(new_state)


if __name__ == "__main__":
    main()
