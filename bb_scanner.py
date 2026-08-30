"""
bb_scanner.py
Scanner "3 Directions" - independant de MT4, concu pour tourner via GitHub
Actions (cron), pas besoin que ton PC soit allume.

Conditions detectees pour chaque paire :
  1) 3 jours (D1) consecutifs dans le meme sens
  2) 3 sessions asiatiques consecutives dans le meme sens
  3) N (par defaut 3) plus hauts / plus bas journaliers casses
     successivement (structure de marche)

Source de donnees : Yahoo Finance (via yfinance), gratuit, sans cle API.
Alertes envoyees par Telegram. Etat persiste dans state.json (commite par
le workflow scan.yml) pour eviter les notifications en double.
"""
import os
import json
import requests
import yfinance as yf
from datetime import datetime, timezone, timedelta

# --------------------------- CONFIG ------------------------------------
SYMBOLS = {
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X", "USDCAD": "USDCAD=X", "AUDUSD": "AUDUSD=X",
    "NZDUSD": "NZDUSD=X", "EURGBP": "EURGBP=X", "EURJPY": "EURJPY=X",
    "EURCHF": "EURCHF=X", "EURCAD": "EURCAD=X", "EURAUD": "EURAUD=X",
    "EURNZD": "EURNZD=X", "GBPJPY": "GBPJPY=X", "GBPCHF": "GBPCHF=X",
    "GBPCAD": "GBPCAD=X", "GBPAUD": "GBPAUD=X", "GBPNZD": "GBPNZD=X",
    "AUDJPY": "AUDJPY=X", "CHFJPY": "CHFJPY=X",
}

ASIAN_START_HOUR = 0
ASIAN_END_HOUR = 9
STRUCTURE_LEVELS = 3

STATE_FILE = "state.json"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram non configure:", message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    except Exception as e:
        print("Erreur envoi Telegram:", e)


def get_daily_data(ticker):
    df = yf.download(ticker, period="30d", interval="1d", progress=False, auto_adjust=False)
    if df.empty:
        return None
    df = df.dropna()
    if df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)
    return df


def get_hourly_data(ticker):
    df = yf.download(ticker, period="10d", interval="1h", progress=False, auto_adjust=False)
    if df.empty:
        return None
    df = df.dropna()
    if df.columns.nlevels > 1:
        df.columns = df.columns.get_level_values(0)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df


def daily_direction_signal(df):
    closed = df.iloc[:-1] if len(df) > 3 else df
    if len(closed) < 3:
        return None
    last3 = closed.iloc[-3:]
    diffs = (last3["Close"] - last3["Open"]).values
    if all(d > 0 for d in diffs):
        return "HAUSSIER"
    if all(d < 0 for d in diffs):
        return "BAISSIER"
    return None


def structure_signal(df, levels=STRUCTURE_LEVELS):
    closed = df.iloc[:-1] if len(df) > levels + 1 else df
    if len(closed) < levels + 1:
        return None
    recent = closed.iloc[-(levels + 1):]
    highs = recent["High"].values
    lows = recent["Low"].values
    bullish = all(highs[i] > highs[i - 1] for i in range(1, len(highs)))
    bearish = all(lows[i] < lows[i - 1] for i in range(1, len(lows)))
    if bullish:
        return "HAUSSIER"
    if bearish:
        return "BAISSIER"
    return None


def session_direction(hdf, day_start):
    sess_start = day_start + timedelta(hours=ASIAN_START_HOUR)
    sess_end = day_start + timedelta(hours=ASIAN_END_HOUR)
    window = hdf[(hdf.index >= sess_start) & (hdf.index < sess_end)]
    if window.empty:
        return None
    open_price = window["Open"].iloc[0]
    close_price = window["Close"].iloc[-1]
    if close_price > open_price:
        return "HAUSSIER"
    if close_price < open_price:
        return "BAISSIER"
    return None


def asian_sessions_signal(hdf):
    if hdf is None or hdf.empty:
        return None
    last_ts = hdf.index[-1]
    today_midnight = last_ts.normalize()
    if last_ts.hour < ASIAN_END_HOUR:
        today_midnight -= timedelta(days=1)

    directions = []
    for i in range(3):
        day_start = today_midnight - timedelta(days=i)
        d = session_direction(hdf, day_start)
        if d is None:
            return None
        directions.append(d)

    if all(d == directions[0] for d in directions):
        return directions[0]
    return None


def main():
    state = load_state()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for symbol, ticker in SYMBOLS.items():
        sym_state = state.get(symbol, {})
        try:
            ddf = get_daily_data(ticker)
            hdf = get_hourly_data(ticker)
        except Exception as e:
            print(f"Erreur donnees {symbol}: {e}")
            continue

        if ddf is None:
            continue

        if sym_state.get("daily") != today_str:
            sig = daily_direction_signal(ddf)
            if sig:
                send_telegram(f"📊 {symbol} : 3 jours consecutifs {sig}")
                sym_state["daily"] = today_str

        if sym_state.get("asian") != today_str:
            sig = asian_sessions_signal(hdf) if hdf is not None else None
            if sig:
                send_telegram(f"🌏 {symbol} : 3 sessions asiatiques consecutives {sig}")
                sym_state["asian"] = today_str

        if sym_state.get("structure") != today_str:
            sig = structure_signal(ddf)
            if sig:
                send_telegram(
                    f"🧱 {symbol} : {STRUCTURE_LEVELS} niveaux journaliers casses successivement - {sig}"
                )
                sym_state["structure"] = today_str

        state[symbol] = sym_state

    save_state(state)


if __name__ == "__main__":
    main()
