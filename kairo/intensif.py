"""MODE INTENSIF v2 — multi-market high-frequency PAPER scalper. Own sub-portfolio (1000 EUR virtual). PAPER ONLY:
no account, no keys, no orders anywhere. Public market data only.

Feeds (real time, free, public):
  * Binance spot WS  (aggTrade + depth5@100ms): crypto majors/alts, PAXG (tokenized gold), EUR/USDT (FX-like)
  * Binance USD-M perps WS (aggTrade + depth5@100ms): crypto majors, XAUUSDT (gold perp) — long & short
  * Kraken spot WS v2 (ticker + trade): EUR/USD, PAXG/USD, BTC/EUR, SOL/EUR
  * Jupiter lite-api price/v3 (poll ~2 s): liquid Solana tokens on DEX (no book, no tick volume)
Bars: 15 s and 1 min OHLCV built from trades (real volume -> real VWAP on CEX feeds; TWAP on Jupiter).
Strategies (each tagged): obi (L2 top-5 order-book imbalance + flow), flow_burst (trade-flow momentum burst),
  vwap_pullback (EMA9/21 trend + VWAP/EMA21 touch), bb_rsi (Bollinger 20/2 + RSI14 extreme reversion),
  fvg, sweep, order_block (SMC on 1 min bars).
Costs per venue: maker/taker fees, spread crossing (taker buys the ask / sells the bid), latency slippage;
maker entries fill only if the market trades THROUGH the limit price within 15 s, else cancelled.
Risk: 0.75% notional per trade, ATR stop 0.3-1%, TP 1.5x stop, 10 min time exit, exposure <= 20%,
daily loss cap -3% (pause until next Paris day), 6 losses in a row -> 10 min pause. Learning loop: learn.py."""
import asyncio, json, os, signal, sqlite3, statistics, time, traceback, datetime, math
from collections import deque, defaultdict
import websockets
import common, learn
from common import now_iso, kv_get, kv_set

BASE = common.BASE
DB = os.path.join(BASE, "intensif.db")
STATE = os.path.join(BASE, "intensif_state.json")
HEARTBEAT = os.path.join(BASE, "heartbeat_intensif")
CFG = {"bankroll_eur": 1000.0, "size_frac": 0.0075, "max_exposure": 0.20, "stop_min": 0.003, "stop_max": 0.01,
       "atr_mult": 1.5, "rr": 1.5, "time_exit_s": 600, "daily_loss_cap": 0.03, "max_consec_losses": 6,
       "consec_pause_s": 600, "cooldown_s": 20, "maker_ttl_s": 15, "latency": 0.0001, "warm_bars15": 24}
VENUES = {  # maker, taker fee per side; can_short
    "binance_spot": {"maker": 0.0010, "taker": 0.0010, "short": False, "label": "Binance spot"},
    "binance_perp": {"maker": 0.0002, "taker": 0.0005, "short": True, "label": "Binance perps"},
    "kraken_spot": {"maker": 0.0025, "taker": 0.0040, "short": False, "label": "Kraken spot"},
    "jupiter": {"maker": None, "taker": 0.0030, "short": False, "label": "Jupiter (DEX Solana)"},
}
BIN_SPOT = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "SUIUSDT", "LINKUSDT",
            "PEPEUSDT", "WIFUSDT", "BONKUSDT", "PAXGUSDT", "EURUSDT"]
BIN_PERP = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "SUIUSDT", "1000PEPEUSDT", "WIFUSDT", "BNBUSDT", "XAUUSDT"]
KRAKEN = ["EUR/USD", "PAXG/USD", "BTC/EUR", "SOL/EUR"]
JUP = {"So11111111111111111111111111111111111111112": "SOL", "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "JUP",
       "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "BONK", "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": "WIF",
       "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": "RAY", "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr": "POPCAT",
       "9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump": "FARTCOIN", "2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv": "PENGU",
       "6p6xgHyF7AeE6TZkSmFsko444wqoP15icUSqi2jfGiPN": "TRUMP", "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL": "JTO"}
ASSET_CLASS = {"PAXGUSDT": "or (tokenisé)", "XAUUSDT": "or (perp)", "PAXG/USD": "or (tokenisé)", "EURUSDT": "forex (stablecoin)",
               "EUR/USD": "forex (stablecoin)"}
MAKER_STRATS = {"vwap_pullback", "bb_rsi", "fvg", "order_block"}

def ema(vals, n):
    k = 2 / (n + 1); e = vals[0]
    for v in vals[1:]: e = v * k + e * (1 - k)
    return e

def rsi(vals, n=14):
    if len(vals) < n + 1: return 50.0
    g = l = 0.0
    for a, b in zip(vals[-n - 1:-1], vals[-n:]):
        d = b - a; g += max(d, 0); l += max(-d, 0)
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)

class Mkt:
    def __init__(s, venue, sym, label=None):
        s.venue, s.sym = venue, sym; s.key = f"{venue}:{sym}"; s.label = label or sym
        s.bid = s.ask = s.last = None; s.bq = s.aq = 0.0; s.obi = deque(maxlen=10)
        s.b15 = deque(maxlen=240); s.b1 = deque(maxlen=240)   # [t,o,h,l,c,v,pv]
        s.flow = deque()  # (t, signed qty*price)
        s.trades = 0; s.liq = 0; s.last_sig = 0; s.last_exit = 0; s.upd = 0; s.prev = None
        s.vw_pv = deque(); s.vol_hist = deque(maxlen=48)
    def mid(s):
        if s.bid and s.ask: return (s.bid + s.ask) / 2
        return s.last
    def on_trade(s, t, p, q, buyer_aggr):
        s.prev = s.last; s.last = p; s.trades += 1; s.upd = t
        notional = p * q
        s.flow.append((t, notional if buyer_aggr else -notional))
        while s.flow and t - s.flow[0][0] > 120: s.flow.popleft()
        for dq, w in ((s.b15, 15), (s.b1, 60)):
            b0 = int(t // w) * w
            if dq and dq[-1][0] == b0:
                b = dq[-1]; b[2] = max(b[2], p); b[3] = min(b[3], p); b[4] = p; b[5] += q; b[6] += p * q
            else:
                if dq is s.b15 and dq: s.vol_hist.append(dq[-1][5] * dq[-1][4])
                dq.append([b0, p, p, p, p, q, p * q])
        s.vw_pv.append((t, p * q, q))
        while s.vw_pv and t - s.vw_pv[0][0] > 1800: s.vw_pv.popleft()
    def vwap(s):
        q = sum(x[2] for x in s.vw_pv)
        if q > 0: return sum(x[1] for x in s.vw_pv) / q
        cl = [b[4] for b in list(s.b15)[-120:]]
        return statistics.fmean(cl) if cl else None
    def atr_pct(s):
        B = list(s.b1)[:-1][-15:]
        if len(B) >= 10:
            trs = [max(b[2] - b[3], abs(b[2] - a[4]), abs(b[3] - a[4])) for a, b in zip(B[:-1], B[1:])]
            return statistics.fmean(trs) / B[-1][4]
        B = list(s.b15)[:-1][-20:]
        if len(B) >= 10:
            return statistics.fmean(b[2] - b[3] for b in B) / B[-1][4] * 2
        return None

def signals(m, now):
    """-> list of (strategy, side, feats). side: +1 long, -1 short."""
    out = []
    B = list(m.b15)[:-1]; M = list(m.b1)[:-1]
    p = m.mid()
    if not p or len(B) < CFG["warm_bars15"] or not m.prev: return out
    cl = [b[4] for b in B]
    e9, e21 = ema(cl[-40:], 9), ema(cl[-40:], 21); e21p = ema(cl[-46:-6], 21) if len(cl) >= 46 else e21
    up = e9 > e21 and e21 >= e21p; dn = e9 < e21 and e21 <= e21p
    vw = m.vwap(); tick_up = m.last > m.prev; tick_dn = m.last < m.prev
    rng = max(b[2] for b in B[-20:]) / min(b[3] for b in B[-20:]) - 1
    f = {"rng20": round(rng * 100, 3), "obi": round(statistics.fmean(m.obi), 2) if m.obi else None, "trend": 1 if up else -1 if dn else 0}
    if rng < 0.0008: return out          # dead tape: can't beat costs
    # flow over the last 5 s vs the 2-min baseline
    f5 = sum(x[1] for x in m.flow if now - x[0] <= 5); fabs = sum(abs(x[1]) for x in m.flow if now - x[0] <= 5)
    base = sum(abs(x[1]) for x in m.flow) / 24 if m.flow else 0
    # 1) order-book imbalance (L2 top 5) confirmed by flow
    if len(m.obi) >= 5 and m.venue != "jupiter":
        ob = statistics.fmean(list(m.obi)[-5:])
        if ob > 0.75 and f5 > 0 and tick_up and up: out.append(("obi", 1, {**f, "obi5": round(ob, 2)}))
        if ob < 0.25 and f5 < 0 and tick_dn and dn: out.append(("obi", -1, {**f, "obi5": round(ob, 2)}))
    # 2) trade-flow momentum burst
    if base > 0 and fabs > 3 * base and abs(f5) > 0.7 * fabs:
        mv = (p / B[-1][4] - 1)
        if f5 > 0 and mv > 0.0004: out.append(("flow_burst", 1, {**f, "burst": round(fabs / base, 1)}))
        if f5 < 0 and mv < -0.0004: out.append(("flow_burst", -1, {**f, "burst": round(fabs / base, 1)}))
    # 3) VWAP / EMA micro-pullback
    if vw:
        if up and min(b[3] for b in B[-3:]) <= max(e21, vw) * 1.0005 and p > e9 and tick_up and p > vw:
            out.append(("vwap_pullback", 1, {**f, "vw_dev": round((p / vw - 1) * 100, 3)}))
        if dn and max(b[2] for b in B[-3:]) >= min(e21, vw) * 0.9995 and p < e9 and tick_dn and p < vw:
            out.append(("vwap_pullback", -1, {**f, "vw_dev": round((p / vw - 1) * 100, 3)}))
    # 4) Bollinger/RSI extreme reversion
    sma = statistics.fmean(cl[-20:]); sd = statistics.pstdev(cl[-20:]) or 1e-12; r = rsi(cl)
    if cl[-1] < sma - 2 * sd and r < 25 and tick_up: out.append(("bb_rsi", 1, {**f, "rsi": round(r), "z": round((p - sma) / sd, 2)}))
    if cl[-1] > sma + 2 * sd and r > 75 and tick_dn: out.append(("bb_rsi", -1, {**f, "rsi": round(r), "z": round((p - sma) / sd, 2)}))
    # 5) SMC on 1 min bars
    if len(M) >= 25:
        for i in range(len(M) - 1, len(M) - 10, -1):
            lo, hi = M[i - 2][2], M[i][3]
            if hi > lo * 1.0005:
                if lo <= p <= hi and tick_up: out.append(("fvg", 1, {**f, "gap": [lo, hi]}))
                break
            lo2, hi2 = M[i][2], M[i - 2][3]
            if hi2 > lo2 * 1.0005:
                if lo2 <= p <= hi2 and tick_dn: out.append(("fvg", -1, {**f, "gap": [lo2, hi2]}))
                break
        sw_lo = min(b[3] for b in M[-22:-2]); sw_hi = max(b[2] for b in M[-22:-2])
        if M[-1][3] < sw_lo * 0.9998 and p > sw_lo and tick_up: out.append(("sweep", 1, {**f, "swing": sw_lo}))
        if M[-1][2] > sw_hi * 1.0002 and p < sw_hi and tick_dn: out.append(("sweep", -1, {**f, "swing": sw_hi}))
        for j in range(len(M) - 5, len(M) - 25, -1):
            ob_ = M[j]
            if ob_[4] < ob_[1] and all(M[k][4] > M[k][1] for k in range(j + 1, j + 4)) and M[j + 3][4] >= ob_[1] * 1.003:
                if ob_[3] <= p <= ob_[1] and tick_up and min(b[3] for b in M[j + 1:]) > ob_[3]:
                    out.append(("order_block", 1, {**f, "ob": [ob_[3], ob_[1]]}))
                break
            if ob_[4] > ob_[1] and all(M[k][4] < M[k][1] for k in range(j + 1, j + 4)) and M[j + 3][4] <= ob_[1] * 0.997:
                if ob_[1] <= p <= ob_[2] and tick_dn and max(b[2] for b in M[j + 1:]) < ob_[2]:
                    out.append(("order_block", -1, {**f, "ob": [ob_[1], ob_[2]]}))
                break
    if not VENUES[m.venue]["short"]:
        out = [o for o in out if o[1] > 0]
    return out

def paris_day(): return datetime.datetime.now().astimezone().date().isoformat()

class Engine:
    def __init__(s):
        s.con = sqlite3.connect(DB, timeout=30); s.con.row_factory = sqlite3.Row
        s.con.executescript("""PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS itrades(id INTEGER PRIMARY KEY, venue TEXT, market TEXT, label TEXT, strategy TEXT, side INT, status TEXT,
          entry_type TEXT, entry_ts TEXT, entry_epoch REAL, entry_price REAL, qty REAL, notional REAL, fee_usd REAL, spread_usd REAL,
          stop REAL, tp REAL, exit_ts TEXT, exit_price REAL, exit_type TEXT, exit_reason TEXT, pnl_usd REAL, pnl_pct REAL, hold_s REAL,
          features TEXT, last_price REAL);
        CREATE TABLE IF NOT EXISTS iorders(id INTEGER PRIMARY KEY, market TEXT, strategy TEXT, side INT, ts REAL, limit_px REAL, status TEXT);
        CREATE TABLE IF NOT EXISTS equity(ts TEXT, equity REAL, cash REAL, n_open INT);
        CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);""")
        c = s.con
        if kv_get(c, "cash") is None:
            fx = common.eurusd(c)
            for k, v in (("bankroll_eur", CFG["bankroll_eur"]), ("session_eurusd", fx), ("bankroll_usd", CFG["bankroll_eur"] * fx),
                         ("cash", CFG["bankroll_eur"] * fx), ("session", {"started": now_iso(), "bankroll_eur": CFG["bankroll_eur"], "eurusd": fx})):
                kv_set(c, k, v)
        s.m = {}
        for x in BIN_SPOT: s._add("binance_spot", x)
        for x in BIN_PERP: s._add("binance_perp", x)
        for x in KRAKEN: s._add("kraken_spot", x)
        for mint, sym in JUP.items(): s._add("jupiter", mint, sym)
        s.pending = {}   # market key -> order dict
        s.execs = deque(); s.lessons = kv_get(c, "lessons", {}) or {}; s.feed_msgs = defaultdict(int); s.feed_ok = {}
        s.last_learn = s.last_state = s.last_eq = s.last_log = 0; s.signals_seen = 0; s.blocked = defaultdict(int)
        s.open = {r["market"] + "|" + r["strategy"]: dict(r) for r in c.execute("SELECT * FROM itrades WHERE status='open'")}
    def _add(s, venue, sym, label=None):
        mk = Mkt(venue, sym, label); s.m[mk.key] = mk
    # ---------- accounting ----------
    def cash(s): return kv_get(s.con, "cash", 0.0)
    def equity(s):
        ov = 0.0; upnl = 0.0
        for t in s.open.values():
            mk = s.m.get(t["market"]); p = (mk.mid() if mk else None) or t["entry_price"]
            upnl += (p - t["entry_price"]) * t["qty"] * t["side"]
            ov += t["notional"]
        return s.cash() + ov + upnl, ov
    def guards(s):
        c = s.con
        if kv_get(c, "day") != paris_day():
            eq, _ = s.equity(); kv_set(c, "day", paris_day()); kv_set(c, "day_start_eq", eq)
        eq, _ = s.equity(); st = kv_get(c, "day_start_eq") or eq
        if eq <= st * (1 - CFG["daily_loss_cap"]): return "daily_cap", (eq / st - 1) * 100
        now = time.time(); pu = kv_get(c, "consec_pause_until", 0) or 0
        if now < pu: return f"consec_losses ({int(pu - now)} s)", (eq / st - 1) * 100
        reset = kv_get(c, "consec_reset_epoch", 0) or 0
        rows = c.execute("SELECT pnl_usd, fee_usd, spread_usd, exit_ts FROM itrades WHERE status='closed' ORDER BY id DESC LIMIT ?", (CFG["max_consec_losses"],)).fetchall()
        def real_loss(r):  # a flat exit that only lost fees/spread is a scratch, not a real loss
            return r["pnl_usd"] < -1.5 * ((r["fee_usd"] or 0) + abs(r["spread_usd"] or 0))
        if len(rows) == CFG["max_consec_losses"] and all(real_loss(r) for r in rows) and \
           all(datetime.datetime.fromisoformat(r["exit_ts"]).timestamp() > reset for r in rows):
            kv_set(c, "consec_pause_until", now + CFG["consec_pause_s"]); kv_set(c, "consec_reset_epoch", now + CFG["consec_pause_s"])
            return f"consec_losses ({int(CFG['consec_pause_s'])} s)", (eq / st - 1) * 100
        return None, (eq / st - 1) * 100
    # ---------- execution simulation ----------
    def try_signal(s, mk, now):
        if now - mk.last_sig < 1.0: return
        mk.last_sig = now
        sigs = signals(mk, now)
        if not sigs: return
        s.signals_seen += len(sigs)
        for strat, side, feats in sigs:
            k = mk.key + "|" + strat
            if k in s.open or mk.key in s.pending or now - mk.last_exit < CFG["cooldown_s"]: continue
            if any(t["market"] == mk.key and t["side"] != side for t in s.open.values()): continue
            mult, why = learn.size_mult(s.lessons, strat, mk.key, None, True)
            if mult <= 0: s.blocked[strat] += 1; continue
            eq, ov = s.equity(); size = eq * CFG["size_frac"] * mult
            if ov + size > eq * CFG["max_exposure"] or size > s.cash(): s.blocked["exposure"] += 1; return
            atr = mk.atr_pct()
            if not atr: return
            stop_pct = min(CFG["stop_max"], max(CFG["stop_min"], CFG["atr_mult"] * atr))
            feats = {**feats, "atr_pct": round(atr * 100, 3), "stop_pct": round(stop_pct * 100, 3), "mult": mult, "learn": why,
                     "hour": datetime.datetime.now().astimezone().hour}
            V = VENUES[mk.venue]
            if strat in MAKER_STRATS and V["maker"] is not None and mk.bid and mk.ask:
                px = mk.bid if side > 0 else mk.ask
                s.pending[mk.key] = {"strategy": strat, "side": side, "ts": now, "limit": px, "size": size, "stop_pct": stop_pct, "feats": feats}
                return
            s.fill(mk, strat, side, size, stop_pct, feats, "taker", None)
            return
    def fill(s, mk, strat, side, size, stop_pct, feats, etype, limit_px):
        V = VENUES[mk.venue]; now = time.time()
        if etype == "taker":
            if mk.bid and mk.ask:
                ref = mk.ask if side > 0 else mk.bid
                spread_cost = abs(ref - mk.mid()) / mk.mid() * size
            else:
                ref = mk.last; spread_cost = 0.0
            slip = CFG["latency"] + (size / max(mk.liq / 2, 1) if mk.venue == "jupiter" and mk.liq else 0)
            px = ref * (1 + slip * side); fee = V["taker"] * size
        else:
            px = limit_px; fee = V["maker"] * size; spread_cost = -abs(px - mk.mid()) / mk.mid() * size if mk.mid() else 0
        qty = size / px
        stop = px * (1 - stop_pct * side); tp = px * (1 + stop_pct * CFG["rr"] * side)
        kv_set(s.con, "cash", s.cash() - size - fee)
        cur = s.con.execute("""INSERT INTO itrades(venue,market,label,strategy,side,status,entry_type,entry_ts,entry_epoch,entry_price,qty,notional,fee_usd,
              spread_usd,stop,tp,features,last_price) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (mk.venue, mk.key, mk.label, strat, side, "open", etype, now_iso(), now, px, qty, size, fee, spread_cost, stop, tp, json.dumps(feats), px))
        t = dict(s.con.execute("SELECT * FROM itrades WHERE id=?", (cur.lastrowid,)).fetchone())
        s.open[mk.key + "|" + strat] = t; s.execs.append(now)
    def close(s, t, mk, px, etype, reason):
        V = VENUES[mk.venue]; now = time.time()
        value = px * t["qty"]
        fee = (V["maker"] if etype == "maker" else V["taker"]) * value
        gross = (px - t["entry_price"]) * t["qty"] * t["side"]
        pnl = gross - fee - t["fee_usd"]
        kv_set(s.con, "cash", s.cash() + t["notional"] + gross - fee)
        s.con.execute("""UPDATE itrades SET status='closed', exit_ts=?, exit_price=?, exit_type=?, exit_reason=?, pnl_usd=?, pnl_pct=?, hold_s=?,
                         fee_usd=fee_usd+?, last_price=? WHERE id=?""",
                      (now_iso(), px, etype, reason, pnl, pnl / t["notional"] * 100, now - t["entry_epoch"], fee, px, t["id"]))
        s.open.pop(t["market"] + "|" + t["strategy"], None); mk.last_exit = now; s.execs.append(now)
        if pnl < 0:
            common.jsonl("journal_losses", {"mode": "intensif", "id": t["id"], "market": t["market"], "strategy": t["strategy"], "side": t["side"],
                                            "entry_type": t["entry_type"], "exit_reason": reason, "pnl_usd": pnl, "hold_s": round(now - t["entry_epoch"]),
                                            "features": json.loads(t["features"] or "{}"), "entry_ts": t["entry_ts"]})
    def on_price(s, mk, trade_px=None):
        now = time.time()
        # pending maker entries: fill only if the market trades THROUGH the limit
        o = s.pending.get(mk.key)
        if o:
            if trade_px is not None and ((o["side"] > 0 and trade_px < o["limit"]) or (o["side"] < 0 and trade_px > o["limit"])):
                s.pending.pop(mk.key); s.fill(mk, o["strategy"], o["side"], o["size"], o["stop_pct"], o["feats"], "maker", o["limit"])
            elif now - o["ts"] > CFG["maker_ttl_s"]:
                s.pending.pop(mk.key); s.blocked["maker_unfilled"] += 1
        for k, t in list(s.open.items()):
            if t["market"] != mk.key: continue
            side = t["side"]
            exit_ref = (mk.bid if side > 0 else mk.ask) or mk.last
            if exit_ref is None: continue
            t["last_price"] = mk.mid() or exit_ref
            if (side > 0 and exit_ref <= t["stop"]) or (side < 0 and exit_ref >= t["stop"]):
                s.close(t, mk, exit_ref * (1 - CFG["latency"] * side), "taker", "stop")
            elif trade_px is not None and ((side > 0 and trade_px > t["tp"]) or (side < 0 and trade_px < t["tp"])) and VENUES[mk.venue]["maker"] is not None:
                s.close(t, mk, t["tp"], "maker", "take_profit")
            elif VENUES[mk.venue]["maker"] is None and ((side > 0 and exit_ref >= t["tp"]) or (side < 0 and exit_ref <= t["tp"])):
                s.close(t, mk, exit_ref * (1 - CFG["latency"] * side), "taker", "take_profit")
            elif now - t["entry_epoch"] > CFG["time_exit_s"]:
                s.close(t, mk, exit_ref * (1 - CFG["latency"] * side), "taker", "time_exit")
    def on_tick(s, mk):
        s.on_price(mk, None)
    def maybe_trade(s, mk):
        if s.pause: return
        s.try_signal(mk, time.time())
    # ---------- feeds ----------
    async def binance(s, venue, syms, host):
        streams = "/".join(f"{x.lower()}@aggTrade/{x.lower()}@depth5@100ms" for x in syms)
        url = f"wss://{host}/stream?streams={streams}"
        while True:
            try:
                async with websockets.connect(url, open_timeout=10, ping_interval=20, max_size=2**22) as ws:
                    s.feed_ok[venue] = now_iso()
                    async for raw in ws:
                        d = json.loads(raw); st = d.get("stream", ""); x = d.get("data") or {}
                        sym = st.split("@")[0].upper(); mk = s.m.get(f"{venue}:{sym}")
                        if not mk: continue
                        s.feed_msgs[venue] += 1
                        if "@aggTrade" in st:
                            p = float(x["p"]); mk.on_trade(time.time(), p, float(x["q"]), not x.get("m"))
                            s.on_price(mk, p); s.maybe_trade(mk)
                        else:
                            bids = x.get("bids") or x.get("b") or []; asks = x.get("asks") or x.get("a") or []
                            if not bids or not asks: continue
                            mk.bid, mk.bq = float(bids[0][0]), float(bids[0][1]); mk.ask, mk.aq = float(asks[0][0]), float(asks[0][1])
                            bv = sum(float(b[1]) for b in bids[:5]); av = sum(float(a[1]) for a in asks[:5])
                            if bv + av > 0: mk.obi.append(bv / (bv + av))
                            s.on_tick(mk)
            except Exception as e:
                s.feed_ok[venue] = f"reconnect {type(e).__name__}"; await asyncio.sleep(3)
    async def kraken(s):
        while True:
            try:
                async with websockets.connect("wss://ws.kraken.com/v2", open_timeout=10, ping_interval=20) as ws:
                    await ws.send(json.dumps({"method": "subscribe", "params": {"channel": "ticker", "symbol": KRAKEN, "event_trigger": "bbo"}}))
                    await ws.send(json.dumps({"method": "subscribe", "params": {"channel": "trade", "symbol": KRAKEN}}))
                    s.feed_ok["kraken_spot"] = now_iso()
                    async for raw in ws:
                        d = json.loads(raw); ch = d.get("channel")
                        if ch not in ("ticker", "trade"): continue
                        for x in d.get("data") or []:
                            mk = s.m.get("kraken_spot:" + x.get("symbol", ""))
                            if not mk: continue
                            s.feed_msgs["kraken_spot"] += 1
                            if ch == "ticker":
                                mk.bid, mk.ask = float(x["bid"]), float(x["ask"]); mk.bq, mk.aq = float(x.get("bid_qty") or 0), float(x.get("ask_qty") or 0)
                                if mk.bq + mk.aq > 0: mk.obi.append(mk.bq / (mk.bq + mk.aq))
                                s.on_tick(mk)
                            else:
                                p = float(x["price"]); mk.on_trade(time.time(), p, float(x["qty"]), x.get("side") == "buy")
                                s.on_price(mk, p); s.maybe_trade(mk)
            except Exception as e:
                s.feed_ok["kraken_spot"] = f"reconnect {type(e).__name__}"; await asyncio.sleep(3)
    async def jupiter(s):
        ids = ",".join(JUP)
        while True:
            try:
                d = await asyncio.to_thread(common.get_json, "https://lite-api.jup.ag/price/v3", {"ids": ids}, (4, 6), 1, "GET", None, False)
                if isinstance(d, dict):
                    s.feed_ok["jupiter"] = now_iso()
                    for mint, v in d.items():
                        mk = s.m.get("jupiter:" + mint)
                        if not mk or not isinstance(v, dict) or not v.get("usdPrice"): continue
                        p = float(v["usdPrice"]); mk.liq = float(v.get("liquidity") or 0); s.feed_msgs["jupiter"] += 1
                        if mk.last and abs(p / mk.last - 1) > 0.2: continue
                        if p != mk.last:
                            mk.on_trade(time.time(), p, 0.0, p > (mk.last or p))
                        s.on_price(mk, None); s.maybe_trade(mk)
            except Exception as e:
                s.feed_ok["jupiter"] = f"error {type(e).__name__}"
            await asyncio.sleep(2.0)
    async def warmup(s):
        """Seed 1 min bars from Binance REST klines (public) so SMC/ATR work immediately."""
        for venue, base in (("binance_spot", "https://api.binance.com/api/v3/klines"), ("binance_perp", "https://fapi.binance.com/fapi/v1/klines")):
            for sym in (BIN_SPOT if venue == "binance_spot" else BIN_PERP):
                d = await asyncio.to_thread(common.get_json, base, {"symbol": sym, "interval": "1m", "limit": 60}, (4, 6), 1, "GET", None, False)
                mk = s.m[f"{venue}:{sym}"]
                for k in d or []:
                    mk.b1.append([int(k[0]) // 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[7])])
    # ---------- housekeeping ----------
    async def house(s):
        while True:
            try:
                s.pause, s.day_pct = s.guards()
                now = time.time()
                if now - s.last_learn > 20:
                    rows = s.con.execute("SELECT strategy, market, entry_ts, pnl_usd, notional FROM itrades WHERE status='closed' ORDER BY id").fetchall()
                    s.lessons = learn.refresh(s.con, [{"setup": r["strategy"], "token": r["market"], "entry_ts": r["entry_ts"], "pnl": r["pnl_usd"],
                                                       "cost": r["notional"], "combo": True} for r in rows], now_iso())
                    s.last_learn = now
                # Jupiter & quiet markets: also check exits on time
                for t in list(s.open.values()):
                    mk = s.m.get(t["market"])
                    if mk: s.on_price(mk, None)
                s.con.commit()
                if now - s.last_eq > 15:
                    eq, _ = s.equity(); s.con.execute("INSERT INTO equity VALUES(?,?,?,?)", (now_iso(), eq, s.cash(), len(s.open))); s.con.commit(); s.last_eq = now
                if now - s.last_state > 2:
                    st = s.write_state()
                    with open(HEARTBEAT, "w") as f: f.write(f"{now:.0f}\n")
                    if now - s.last_log > 60:
                        print(f"[{now_iso()}] intensif {s.pause or 'active'}: markets {st['markets_live']}/{len(s.m)} open {len(s.open)} closed {st['closed']} "
                              f"win {st['win_rate'] or 0:.1f}% net ${st['pnl_net_usd']:.2f} fees ${st['fees_usd']:.2f} exec/min last {st['exec_last_min']} "
                              f"avg10m {st['exec_per_min_10m']} eq {st['equity_eur']:.2f} EUR day {s.day_pct:+.2f}% feeds {dict(s.feed_msgs)}", flush=True)
                        s.last_log = now
            except Exception as e:
                print(f"[{now_iso()}] intensif house ERROR {type(e).__name__}: {e}", flush=True); traceback.print_exc()
                try: s.con.rollback()
                except Exception: pass
            await asyncio.sleep(1)
    def write_state(s):
        c = s.con; fx = common.eurusd(c); eq, ov = s.equity(); now = time.time()
        while s.execs and now - s.execs[0] > 600: s.execs.popleft()
        cl = c.execute("SELECT COUNT(*) n, SUM(pnl_usd>0) w, COALESCE(SUM(pnl_usd),0) pnl FROM itrades WHERE status='closed'").fetchone()
        fees = c.execute("SELECT COALESCE(SUM(fee_usd),0) f, COALESCE(SUM(spread_usd),0) sp FROM itrades").fetchone()
        tot_exec = c.execute("SELECT COUNT(*) + COALESCE(SUM(status='closed'),0) FROM itrades").fetchone()[0] or 0
        started = (kv_get(c, "session") or {}).get("started")
        try: mins = max(1.0, (now - datetime.datetime.fromisoformat(started).timestamp()) / 60)
        except Exception: mins = 1.0
        q = lambda sql: [dict(r) for r in c.execute(sql)]
        lab = {k: m.label for k, m in s.m.items()}
        by_m = q("SELECT market, venue, label, COUNT(*) n, SUM(pnl_usd>0) w, SUM(pnl_usd) pnl, SUM(fee_usd) fees FROM itrades WHERE status='closed' GROUP BY market ORDER BY n DESC")
        for r in by_m: r["asset_class"] = ASSET_CLASS.get(r["label"], "crypto"); r["venue_fr"] = VENUES[r["venue"]]["label"]
        st = {"ts": now_iso(), "mode": "PAPER", "label_fr": "Mode intensif", "version": 2, "eurusd": fx,
              "bankroll_eur": kv_get(c, "bankroll_eur", 1000.0), "bankroll_usd": kv_get(c, "bankroll_usd"),
              "equity_usd": eq, "equity_eur": eq / fx, "exposure_usd": ov, "cash_usd": s.cash(),
              "closed": cl["n"], "wins": cl["w"] or 0, "win_rate": (cl["w"] or 0) / cl["n"] * 100 if cl["n"] else None,
              "pnl_net_usd": cl["pnl"], "fees_usd": fees["f"], "spread_usd": fees["sp"], "slippage_usd": fees["sp"],
              "exec_last_min": sum(1 for t in s.execs if now - t <= 60), "exec_per_min_10m": round(len(s.execs) / min(10, mins), 2),
              "exec_per_min_session": round(tot_exec / mins, 2), "executions": tot_exec, "session_min": round(mins, 1),
              "paused": s.pause, "day_pct": round(s.day_pct, 2), "watch": len(s.m),
              "markets_live": sum(1 for m in s.m.values() if m.upd and now - m.upd < 120 or (m.venue == "jupiter" and m.last)),
              "feeds": {v: {"msgs": s.feed_msgs.get(v, 0), "status": s.feed_ok.get(v)} for v in VENUES},
              "blocked": dict(s.blocked), "signals_seen": s.signals_seen, "pending": len(s.pending), "cfg": CFG,
              "venues": {k: {kk: vv for kk, vv in v.items()} for k, v in VENUES.items()},
              "by_setup": q("SELECT strategy setup, COUNT(*) n, SUM(pnl_usd>0) w, SUM(pnl_usd) pnl, SUM(fee_usd) fees FROM itrades WHERE status='closed' GROUP BY strategy ORDER BY n DESC"),
              "by_market": by_m,
              "lessons_fr": learn.lessons_fr(s.lessons, lab),
              "open": [{**t, "symbol": t["label"], "setup": t["strategy"], "cost_usd": t["notional"]} for t in s.open.values()],
              "recent": [{**r, "symbol": r["label"], "setup": r["strategy"], "slip_usd": r["spread_usd"]} for r in
                         q("SELECT id,label,venue,strategy,side,entry_type,exit_type,entry_ts,exit_ts,pnl_usd,pnl_pct,exit_reason,fee_usd,spread_usd,hold_s FROM itrades WHERE status='closed' ORDER BY id DESC LIMIT 40")]}
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f: json.dump(st, f, default=str)
        os.replace(tmp, STATE); s.last_state = now
        return st
    async def main(s):
        s.pause, s.day_pct = None, 0.0
        print(f"[{now_iso()}] intensif v2 start PAPER ONLY markets={len(s.m)} cash=${s.cash():.2f}", flush=True)
        try: await asyncio.wait_for(s.warmup(), 60)
        except Exception as e: print("warmup error", e, flush=True)
        await asyncio.gather(s.binance("binance_spot", BIN_SPOT, "stream.binance.com:443"),
                             s.binance("binance_perp", BIN_PERP, "fstream.binance.com"),
                             s.kraken(), s.jupiter(), s.house())

if __name__ == "__main__":
    asyncio.run(Engine().main())
