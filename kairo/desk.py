"""Main daemon: Scout -> Filter -> Analyst -> Executor -> Risk -> Logger, hard handoffs, PAPER ONLY."""
import time, traceback, sys, signal, os
from collections import Counter
import common, scout, filter as filt, analyst, executor, risk, logger, paper
from logger import set_agent
from config import cfg, profile_name

def heartbeat_path():
    return os.path.join(common.data_dir(), "heartbeat")

def pause_flag():
    # écrit par ai_local.py (ordre « pause ») : plus d'entrées, Risk continue
    return os.path.join(common.data_dir(), "paused.flag")
CYCLE_HARD_TIMEOUT_S = 240   # a whole cycle may never take longer than this
TICK_HARD_TIMEOUT_S = 60     # a single risk tick

class StageTimeout(BaseException):  # BaseException so `except Exception` in stages can't swallow it
    pass

def _on_alarm(signum, frame):
    raise StageTimeout("hard timeout (watchdog alarm)")

def beat(note=""):
    try:
        with open(heartbeat_path(), "w") as f:
            f.write(f"{time.time():.0f} {common.now_iso()} {note}\n")
    except Exception:
        pass

def pause_status(con):
    E = cfg()["executor"]
    try:
        tripped, info = executor.circuit_tripped(con, E)
        if tripped:
            return f"PAUSED daily_drawdown {info.get('dd_pct', 0):.1f}%"
        paused, info = executor.loss_pause_active(con, E)
        if paused:
            return f"PAUSED consecutive_losses {info.get('remaining_s')}s left"
    except Exception as e:
        return f"pause_check_error {e!r}"
    return "active"

def run_cycle(con, cycle, t0=None):
    """One scout → filter → analyst → executor → risk → logger pass.

    Same decisions as the original single-desk daemon. `t0` is only used for the log line.
    """
    t0 = t0 if t0 is not None else time.time()
    C = cfg()
    signal.alarm(CYCLE_HARD_TIMEOUT_S)
    if os.path.exists(pause_flag()):
        try:
            for a in ("scout", "filter", "analyst", "executor"):
                set_agent(con, a, "idle", "desk en pause (ordre IA locale) — aucune nouvelle entrée", {"cycle": cycle})
            exits = risk.run(cycle, con) if con.execute("SELECT 1 FROM positions WHERE status='open'").fetchone() else []
            n_open = con.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
            set_agent(con, "risk", "monitoring" if n_open else "idle", f"pause : {n_open} position(s) surveillée(s)", {"open": n_open, "exits": len(exits)})
            logger.write_state(con)
            common.kv_set(con, "cycle", cycle)
            print(f"[{common.now_iso()}] cycle {cycle} [{profile_name()}] PAUSED (paused.flag) open {n_open} exits {len(exits)}", flush=True)
        except Exception as e:
            print(f"[{common.now_iso()}] paused cycle ERROR {e!r}", flush=True)
            try: con.rollback()
            except Exception: pass
        signal.alarm(0); beat(f"cycle {cycle} paused")
        return "paused"
    try:
        set_agent(con, "scout", "running", "scan DexScreener en cours", {}); logger.write_state(con)
        cands, sm = scout.run(cycle)
        set_agent(con, "scout", "idle", f"{len(cands)} paires dans la fenêtre sur {sm['mints_seen']} mints", {"cycle": cycle, "candidates": len(cands), **sm})
        set_agent(con, "filter", "running", f"vérification de {len(cands)} candidats", {}); logger.write_state(con)
        surv, kills = filt.run(cycle, cands)
        kc = Counter(k["reason"] for k in kills)
        set_agent(con, "filter", "idle", f"{len(cands)-len(surv)} éliminés, {len(surv)} survivants", {"in": len(cands), "killed": len(cands)-len(surv), "survivors": len(surv), "top_reason": kc.most_common(1)[0][0] if kc else None})
        set_agent(con, "analyst", "running", f"notation de {len(surv)} tokens", {})
        scored, passes = analyst.run(cycle, con, surv)
        best = max(scored, key=lambda x: x["score"]) if scored else None
        seuil = C["analyst"]["pass_score"]
        set_agent(con, "analyst", "idle", f"meilleur {best['symbol']} {best['score']}" if best else "rien à noter", {"scored": len(scored), "passed": len(passes), "passed_70": len(passes), "seuil": seuil})
        fills = executor.run(cycle, con, passes)
        eq, _ = executor.equity(con)
        set_agent(con, "executor", "idle", ", ".join(f"ACHAT {f['symbol']} ${f['size_usd']:.0f}" for f in fills) or "aucune entrée", {"entries": len(fills), "equity": round(eq, 2)})
        exits = risk.run(cycle, con, fills)
        n_open = con.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
        set_agent(con, "risk", "monitoring" if n_open else "idle", ", ".join(f"{e['reason']} {e['symbol']} {e['pnl_usd']:+.0f}" for e in exits) or f"{n_open} position(s) surveillée(s)", {"open": n_open, "exits": len(exits)})
        logger.log_cycle(con, cycle, cands, kills, scored, passes, fills, exits, note=profile_name())
        common.kv_set(con, "cycle", cycle)
        signal.alarm(0)
        print(f"[{common.now_iso()}] cycle {cycle} [{profile_name()}] {pause_status(con)}: scanned {len(cands)} killed {len(cands)-len(surv)} scored {len(scored)} passed {len(passes)} entries {len(fills)} exits {len(exits)} eq {eq/common.eurusd(con):.2f} EUR (${eq:.2f}) http {common.STATS} ({time.time()-t0:.0f}s)", flush=True)
        return "ok"
    except BaseException as e:
        signal.alarm(0)
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        print(f"[{common.now_iso()}] cycle {cycle} [{profile_name()}] ERROR {type(e).__name__}: {e} ({time.time()-t0:.0f}s)", flush=True)
        traceback.print_exc(); sys.stdout.flush()
        if isinstance(e, StageTimeout):
            common.reset_session()
        try:
            con.rollback()
        except Exception:
            pass
        common.kv_set(con, "cycle", cycle)
        return "error"

def main():
    signal.signal(signal.SIGALRM, _on_alarm)
    con = common.db()
    paper.ensure_session(con)
    cycle = common.kv_get(con, "cycle", 0)
    print(f"[{common.now_iso()}] desk start profile={profile_name()} cash={common.kv_get(con, 'cash')} PAPER ONLY", flush=True)
    while True:
        paper.apply_control_file(con)
        cycle = common.kv_get(con, "cycle", cycle)
        C = cfg()
        cycle_s = C["cycle_s"]
        risk_tick_s = C["risk_tick_s"]
        cycle += 1; t0 = time.time()
        beat(f"cycle {cycle} start")
        status = run_cycle(con, cycle, t0)
        if status == "paused":
            time.sleep(max(5, min(cycle_s, 30)))
            continue
        beat(f"cycle {cycle} done")
        # risk ticks between cycles (or a short pause if the cycle overran)
        if time.time() - t0 >= cycle_s:
            time.sleep(1)
            try:
                signal.alarm(TICK_HARD_TIMEOUT_S)
                if con.execute("SELECT 1 FROM positions WHERE status='open'").fetchone():
                    ex = risk.run(cycle, con)
                    if ex:
                        print(f"[{common.now_iso()}] risk tick exits: {ex}", flush=True)
                        set_agent(con, "risk", "monitoring", ", ".join(f"{e['reason']} {e['symbol']} {e['pnl_usd']:+.0f}" for e in ex), {"exits_tick": len(ex)})
                    logger.write_state(con)
                signal.alarm(0)
                beat(f"cycle {cycle} risk tick")
            except BaseException as e:
                signal.alarm(0)
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                print(f"[{common.now_iso()}] risk tick ERROR {type(e).__name__}: {e}", flush=True)
                try:
                    con.rollback()
                except Exception:
                    pass
            continue
        while time.time() - t0 < cycle_s:
            time.sleep(min(risk_tick_s, max(1, cycle_s - (time.time() - t0))))
            if time.time() - t0 >= cycle_s:
                break
            try:
                signal.alarm(TICK_HARD_TIMEOUT_S)
                if con.execute("SELECT 1 FROM positions WHERE status='open'").fetchone():
                    ex = risk.run(cycle, con)
                    if ex:
                        print(f"[{common.now_iso()}] risk tick exits: {ex}", flush=True)
                        set_agent(con, "risk", "monitoring", ", ".join(f"{e['reason']} {e['symbol']} {e['pnl_usd']:+.0f}" for e in ex), {"exits_tick": len(ex)})
                    logger.write_state(con)
                signal.alarm(0)
                beat(f"cycle {cycle} risk tick")
            except BaseException as e:
                signal.alarm(0)
                if isinstance(e, (KeyboardInterrupt, SystemExit)):
                    raise
                print(f"[{common.now_iso()}] risk tick ERROR {type(e).__name__}: {e}", flush=True)
                try:
                    con.rollback()
                except Exception:
                    pass

if __name__ == "__main__":
    main()
