"""Run the same desk cycle for every account, one after another.

Decisions inside a cycle are desk.run_cycle (the original pipeline). Accounts do not
share a portfolio. Set KAIRO_MULTIUSER=0 to run desk.py on a single folder instead,
which is the original one-portfolio layout.
"""
import os, signal, time
import common, desk, paper, webauth
from config import cfg

def main():
    signal.signal(signal.SIGALRM, desk._on_alarm)
    print(f"[{common.now_iso()}] userdesk start (isolated portfolios) PAPER by default", flush=True)
    while True:
        accs = webauth.trading_accounts()
        if not accs:
            time.sleep(5)
            continue
        try:
            with open(os.path.join(common.BASE, "heartbeat"), "w") as f:
                f.write(f"{time.time():.0f} {common.now_iso()} userdesk\n")
        except OSError:
            pass
        t0 = time.time()
        slowest = 30
        for acc in accs:
            common.bind_data_dir(acc["dir"])
            con = common.db()
            try:
                paper.ensure_session(con)
                paper.apply_control_file(con)
                cycle = int(common.kv_get(con, "cycle", 0) or 0) + 1
                desk.beat(f"cycle {cycle} start")
                status = desk.run_cycle(con, cycle)
                if status != "paused":
                    desk.beat(f"cycle {cycle} done")
                slowest = max(slowest, cfg()["cycle_s"])
            except Exception as e:
                print(f"[{common.now_iso()}] user {acc['id']} ERROR {e!r}", flush=True)
            finally:
                con.close()
                common.clear_data_dir()
        wait = max(5, slowest - (time.time() - t0))
        time.sleep(wait)

if __name__ == "__main__":
    main()
