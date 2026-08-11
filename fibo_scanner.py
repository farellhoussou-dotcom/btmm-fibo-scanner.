"""
Scanner Fibonacci 61.8% multi-paires.

Pour chaque paire :
  - Point A = le plus bas des DAYS_LOOKBACK derniers jours (D1)
  - Point B = le plus haut des DAYS_LOOKBACK derniers jours (D1)
  - Le sens (haussier/baissier) est donne par lequel des deux (haut ou bas)
    s'est forme le plus RECEMMENT chronologiquement.
  - Entree = niveau 61.8% = A * 0.618 + B * 0.382
  - Stop Loss = niveau 100% = point A
  - Lot = calcule pour que la perte au SL soit plafonnee a RISK_USD
  - "Tester le niveau" = la bougie M15 en cours touche ce niveau
    (avec une tolerance en pips), SAUF si une annonce economique a fort
    impact est en cours sur l'une des devises de la paire (fenetre de
    blackout avant/apres, configurable) -> dans ce cas le signal est ignore.

Une alerte (Telegram + ntfy) est envoyee uniquement au moment ou une paire
PASSE de "pas en test" a "en test" (pas de spam a chaque execution).

Donnees de prix : Yahoo Finance (gratuit, sans cle API), via yfinance.
Calendrier economique : Forex Factory (gratuit, sans cle API).
"""

import os
import sys
import json
from datetime import datetime, timedelta, timezone

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

# --- Parametres generaux (modifiables via variables d'environnement) ------
DAYS_LOOKBACK = int(os.environ.get("DAYS_LOOKBACK", "2"))
TOLERANCE_PIPS = float(os.environ.get("TOLERANCE_PIPS", "3.0"))
STATE_FILE = "state.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

# --- Gestion du risque -----------------------------------------------------
RISK_USD = float(os.environ.get("RISK_USD", "140"))

# --- Filtre d'annonces economiques -----------------------------------------
USE_NEWS_FILTER = os.environ.get("USE_NEWS_FILTER", "true").lower() == "true"
NEWS_IMPACT_FILTER = set(x.strip() for x in os.environ.get("NEWS_IMPACT_FILTER", "High").split(","))
BLACKOUT_BEFORE_MIN = int(os.environ.get("BLACKOUT_BEFORE_MIN", "15"))
BLACKOUT_AFTER_MIN = int(os.environ.get("BLACKOUT_AFTER_MIN", "15"))
CALENDAR_URL = os.environ.get("CALENDAR_URL", "https://nfs.faireconomy.media/ff_calendar_thisweek.json")


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
    """Calcule le niveau 61.8% (entree), le SL (niveau 100% = point A) et
    le sens du mouvement."""
    if low_date > high_date:
        # le creux est plus recent -> mouvement baissier menant a ce creux
        A, B = high_val, low_val
        bullish = False
    else:
        # le sommet est plus recent -> mouvement haussier menant a ce sommet
        A, B = low_val, high_val
        bullish = True

    entry = A * 0.618 + B * 0.382
    sl = A
    return entry, sl, bullish


_quote_to_usd_cache = {}


def get_quote_to_usd(ccy: str):
    """Retourne combien vaut 1 unite de `ccy` en USD (avec cache pour eviter
    les appels repetes dans la meme execution)."""
    if ccy == "USD":
        return 1.0
    if ccy in _quote_to_usd_cache:
        return _quote_to_usd_cache[ccy]

    rate = None
    try:
        d = yf.Ticker(f"{ccy}USD=X").history(period="5d")
        if not d.empty:
            rate = float(d["Close"].iloc[-1])
    except Exception:
        pass

    if rate is None:
        try:
            d = yf.Ticker(f"USD{ccy}=X").history(period="5d")
            if not d.empty:
                inv = float(d["Close"].iloc[-1])
                if inv > 0:
                    rate = 1.0 / inv
        except Exception:
            pass

    _quote_to_usd_cache[ccy] = rate
    return rate


def get_pip_value_per_lot(name: str):
    """Valeur en USD d'un mouvement d'un pip, pour 1.0 lot standard
    (100 000 unites, ou 100 onces pour l'or)."""
    contract_size = 100 if name == "XAUUSD" else 100000
    pip = pip_size(name)
    quote_ccy = "USD" if name == "XAUUSD" else name[3:6]

    value_in_quote = pip * contract_size

    if quote_ccy == "USD":
        return value_in_quote

    q2usd = get_quote_to_usd(quote_ccy)
    if q2usd is None:
        return None
    return value_in_quote * q2usd


def calc_lot(entry: float, sl: float, risk_usd: float, name: str):
    """Calcule le lot pour que la perte au SL soit plafonnee a risk_usd.
    Arrondi vers le bas au pas de 0.01, jamais au-dessus du risque cible."""
    distance = abs(entry - sl)
    if distance <= 0:
        return None

    pip = pip_size(name)
    distance_pips = distance / pip

    pip_value = get_pip_value_per_lot(name)
    if not pip_value or pip_value <= 0:
        return None

    raw_lot = risk_usd / (distance_pips * pip_value)

    lot = int(raw_lot * 100) / 100.0  # arrondi vers le bas au 0.01
    if lot < 0.01:
        return None  # risque trop faible pour atteindre le lot minimum
    return lot


def fetch_calendar():
    """Telecharge et parse le calendrier economique. Retourne une liste de
    tuples (datetime_utc, country, impact)."""
    events = []
    try:
        resp = requests.get(CALENDAR_URL, timeout=15)
        data = resp.json()
    except Exception as e:
        print(f"Erreur telechargement calendrier: {e}", file=sys.stderr)
        return events

    for item in data:
        try:
            country = item.get("country", "")
            impact = item.get("impact", "")
            date_str = item.get("date", "")
            if not country or not date_str:
                continue
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            dt_utc = dt.astimezone(timezone.utc)
            events.append((dt_utc, country, impact))
        except Exception:
            continue

    print(f"Calendrier economique charge : {len(events)} evenements.")
    return events


def is_news_blackout(name: str, now_utc: datetime, events: list):
    """Verifie si une annonce a fort impact touchant cette paire est dans sa
    fenetre de blackout (avant/apres). Retourne (bool, event_or_None)."""
    if not USE_NEWS_FILTER or not events:
        return False, None

    currencies = {"USD"} if name == "XAUUSD" else {name[:3], name[3:6]}

    for dt_utc, country, impact in events:
        if impact not in NEWS_IMPACT_FILTER:
            continue
        if country not in currencies:
            continue
        window_start = dt_utc - timedelta(minutes=BLACKOUT_BEFORE_MIN)
        window_end = dt_utc + timedelta(minutes=BLACKOUT_AFTER_MIN)
        if window_start <= now_utc <= window_end:
            return True, dt_utc

    return False, None


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


def send_ntfy(text: str, title: str = "BTMM Fibo Scanner"):
    if not NTFY_TOPIC:
        print("ATTENTION: NTFY_TOPIC manquant, alerte ntfy non envoyee.", file=sys.stderr)
        return
    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    try:
        resp = requests.post(
            url,
            data=text.encode("utf-8"),
            headers={"Title": title, "Priority": "high", "Tags": "chart_with_upwards_trend"},
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"Erreur ntfy ({resp.status_code}): {resp.text}", file=sys.stderr)
    except Exception as e:
        print(f"Erreur envoi ntfy: {e}", file=sys.stderr)


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

    now_utc = datetime.now(timezone.utc)
    events = fetch_calendar() if USE_NEWS_FILTER else []

    for name, ticker in PAIRS.items():
        try:
            daily = get_daily_high_low(ticker, DAYS_LOOKBACK)
            m15 = get_current_m15(ticker)
            if daily is None or m15 is None:
                print(f"{name}: donnees insuffisantes, ignore.")
                continue

            high_val, high_date, low_val, low_date = daily
            entry, sl, bullish = compute_level(high_val, high_date, low_val, low_date)
            cur_high, cur_low = m15

            tol = TOLERANCE_PIPS * pip_size(name)
            price_at_level = (cur_low - tol) <= entry <= (cur_high + tol)

            news_block, news_time = is_news_blackout(name, now_utc, events)
            testing = price_at_level and not news_block

            new_state[name] = bool(testing)
            was_testing = bool(state.get(name, False))

            sens = "Haussier (ACHAT)" if bullish else "Baissier (VENTE)"
            lot = calc_lot(entry, sl, RISK_USD, name)
            lot_str = f"{lot:.2f}" if lot else "N/A (risque trop faible)"

            news_tag = " [NEWS - ignore]" if news_block else ""
            print(f"{name}: entree={entry:.5f} sl={sl:.5f} lot={lot_str} sens={sens} testing={testing}{news_tag}")

            if testing and not was_testing:
                alerts.append(
                    f"{name} | Signal BTMM - Test du niveau 61.8%\n"
                    f"Sens: {sens}\n"
                    f"Entree (61.8%): {entry:.5f}\n"
                    f"Stop Loss (100%): {sl:.5f}\n"
                    f"Lot (risque {RISK_USD:.0f}$): {lot_str}\n"
                    f"Range utilisee: {DAYS_LOOKBACK} derniers jours\n"
                    f"Heure: {now_utc.strftime('%Y-%m-%d %H:%M UTC')}"
                )
        except Exception as e:
            print(f"Erreur sur {name}: {e}", file=sys.stderr)

    for alert in alerts:
        send_telegram(alert)
        send_ntfy(alert)
        print("ALERTE ENVOYEE:\n" + alert)

    save_state(new_state)


if __name__ == "__main__":
    main()
