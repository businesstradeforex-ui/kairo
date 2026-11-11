"""Desk profiles: 'strict', 'agressif', and 'profit' (active default).

PAPER ONLY. Switch with profile.txt or DESK_PROFILE.
  Version web : changez de profil depuis le panneau « Ordres & IA locale » (ou POST /api/orders).
  Les paramètres modifiés par l'IA locale sont stockés dans overrides.json (liste blanche + bornes, voir ai_local.py).
"""
import os, json, copy

BASE = os.path.abspath(os.environ.get("MEMEDESK_DATA") or os.path.dirname(os.path.abspath(__file__)))
PROFILE_FILE = os.path.join(BASE, "profile.txt")
OVERRIDES_FILE = os.path.join(BASE, "overrides.json")

PROFILES = {
    "strict": {
        "label_fr": "Mode strict",
        "cycle_s": 75,
        "risk_tick_s": 20,
        "scout": {
            "age_min_h": 0.5,
            "age_max_h": 72.0,
            "mcap_min": 300_000,
            "mcap_max": 20_000_000,
            "search_terms_per_cycle": 35,
            "gt_calls_per_cycle": 4,
            "jup_calls_per_cycle": 6,
            "watch_hours": 6,
        },
        "filter": {
            "liq_min": 40_000,
            "vol1h_kill": 50_000,
            "vol1h_penalty_below": None,
            "top10_max": 25.0,
            "top10_hard": None,
            "dev_max": 3.0,
            "dev_hard": None,
            "bundle_max": 10.0,
            "bundle_hard": None,
            "pump1h_max": 80.0,
            "pump_is_kill": True,
            "lp_safe_min": 90.0,
            "lp_is_kill": True,
            "dev_rugs_is_kill": True,
            "fail_closed": True,
            "mint_freeze_fail_closed": True,
            "soft_as_penalty": False,
            "rugcheck_cache_s": 600,
            "rugcheck_cap_per_cycle": None,
        },
        "analyst": {
            "pass_score": 70,
            "signal_min_score": 70,  # signals disabled effectively (must still meet 70)
            "signals_enabled": False,
        },
        "executor": {
            "min_frac": 0.08,
            "max_frac": 0.08,
            "max_open": 50,
            "reentry_cooldown_s": 0,
        },
        "risk": {
            "stop_pct": 0.06,
            "trail_activate": 0.12,
            "trail_pct": 0.06,
            "time_exit_s": None,
            "flat_abs_pct": None,
        },
    },
    "agressif": {
        "label_fr": "Mode agressif",
        "cycle_s": 25,
        "risk_tick_s": 10,
        "scout": {
            "age_min_h": 5 / 60,       # 5 minutes
            "age_max_h": 168.0,        # 7 days
            "mcap_min": 30_000,
            "mcap_max": 50_000_000,
            "search_terms_per_cycle": 12,
            "gt_calls_per_cycle": 1,   # GT gap is 6.5s; keep cycle short
            "jup_calls_per_cycle": 3,
            "watch_hours": 24,
        },
        "filter": {
            "liq_min": 15_000,         # hard safety floor (11/11: <15k = 22% win, -105$)
            "vol1h_kill": 3_000,       # only truly dead coins
            "vol1h_penalty_below": 20_000,
            "top10_max": 40.0,         # penalty above this
            "top10_hard": 85.0,        # extreme concentration
            "dev_max": 10.0,
            "dev_hard": 50.0,
            "bundle_max": 25.0,
            "bundle_hard": 70.0,
            "pump1h_max": 80.0,
            "pump_is_kill": False,     # penalty only
            "lp_safe_min": 50.0,       # penalty if below; not a kill
            "lp_is_kill": True,       # LP must be locked/burned (rug safety)
            "dev_rugs_is_kill": False, # heavy penalty; token marked rugged still killed
            "fail_closed": False,
            "mint_freeze_fail_closed": True,
            "soft_as_penalty": True,
            "rugcheck_cache_s": 900,
            "rugcheck_cap_per_cycle": 12,
        },
        "analyst": {
            "pass_score": 45,
            "signal_min_score": 28,    # a strong signal can enter above this floor
            "signals_enabled": True,
        },
        "executor": {
            "min_frac": 0.03,
            "max_frac": 0.08,
            "max_open": 10,            # 11/11: limit exposure to box-sleep gaps
            "reentry_cooldown_s": 20 * 60,
        },
        "risk": {
            "stop_pct": 0.06,
            "trail_activate": 0.12,
            "trail_pct": 0.06,
            "time_exit_s": 35 * 60,    # recycle capital if still flat
            "flat_abs_pct": 4.0,
            "partial_tp_pct": 0.15,
            "partial_tp_frac": 0.33,
            "jump_verify_pct": 0.50,
        },
    },
    "profit": {
        "label_fr": "Mode profit",
        "cycle_s": 30,
        "risk_tick_s": 10,
        "scout": {
            "age_min_h": 1.0,          # 1h (pumpswap pairs need >= 3h, see filter)
            "age_max_h": 168.0,        # 7 days: older pairs were the only non-losers
            "mcap_min": 50_000,
            "mcap_max": 30_000_000,
            "search_terms_per_cycle": 12,
            "gt_calls_per_cycle": 1,
            "jup_calls_per_cycle": 3,
            "watch_hours": 12,
        },
        "filter": {
            "liq_min": 30_000,
            "vol1h_kill": 10_000,      # loosened: THUG/FAIR (the only green trades) had 8-10k
            "liq_mcap_min": 0.10,      # DacityCoin 0.089, DACITY 0.067: thin pools rug
            "chase_h1_max": 40.0,      # no entries after a >40% 1h pump
            "young_dexes": ("pumpswap", "pumpfun"),
            "young_dex_min_age_h": 3.0, # all 13 pumpswap trades <3h lost, 4 rugged -90%
            "vol1h_penalty_below": None,
            "top10_max": 35.0,
            "top10_hard": 35.0,
            "dev_max": 5.0,
            "dev_hard": 5.0,
            "bundle_max": 10.0,
            "bundle_hard": 10.0,
            "pump1h_max": 80.0,
            "pump_is_kill": True,
            "lp_safe_min": 90.0,
            "lp_is_kill": True,
            "dev_rugs_is_kill": True,
            "fail_closed": True,
            "mint_freeze_fail_closed": True,
            "soft_as_penalty": False,
            "rugcheck_cache_s": 900,
            "rugcheck_cap_per_cycle": 20,
        },
        "analyst": {
            "pass_score": 60,
            "signal_min_score": 55,    # signal only counts if score >= 55
            "signals_enabled": True,
            "require_setup": True,     # pullback after strength, or confirmed breakout
            "pullback_m5_min": -3.0,
            "pullback_m5_max": 5.0,
            "pullback_h1_min": 5.0,
            "pullback_bs5_min": 1.2,
            "breakout_confirm_cycles": 1,
            "bs5_min": 1.1,            # buy pressure: 5m buys/sells and 1h buys > sells
            "chart_confirm": True,     # 1m EMA9/EMA21 + VWAP pullback-reclaim (GeckoTerminal OHLCV)
            "chart_calls_per_cycle": 3,
            "chart": {"touch_pct": 0.02, "max_undercut_pct": 0.04, "vol_mult": 1.0, "max_ext_vwap": 0.12},
        },
        "executor": {
            "min_frac": 0.03,
            "max_frac": 0.08,
            "max_open": 6,
            "reentry_cooldown_s": 20 * 60,
            "max_slip": 0.015,
            "min_size_usd": 15.0,
            "consec_loss_pause_n": 3,
            "consec_loss_pause_s": 15 * 60,
            "daily_dd_pct": 0.15,
        },
        "risk": {
            "stop_pct": 0.06,
            "trail_activate": 0.12,
            "trail_pct": 0.06,
            "time_exit_s": 35 * 60,
            "max_hold_s": 4 * 3600,    # close any remainder after 4h
            "flat_abs_pct": 4.0,
            "partial_tp_pct": 0.15,    # sell 50% at +15% from fill, stop to breakeven
            "partial_tp_frac": 0.50,
            "tp_levels": [(0.15, 1 / 3), (0.30, 0.5)],  # 1/3 at +15%, then half the rest (1/3) at +30%; last 1/3 trails
            "jump_verify_pct": 0.50,
        },
    },
    "turbo": {
        "label_fr": "Mode turbo",
        "cycle_s": 8,
        "risk_tick_s": 1,
        "scout": {
            "age_min_h": 5 / 60,
            "age_max_h": 72.0,
            "mcap_min": 20_000,
            "mcap_max": 25_000_000,
            "search_terms_per_cycle": 4,
            "gt_calls_per_cycle": 1,
            "jup_calls_per_cycle": 1,
            "watch_hours": 6,
            "concurrent": True,
        },
        "filter": {
            "liq_min": 12_000,
            "vol1h_kill": 2_000,
            "vol1h_penalty_below": 8_000,
            "top10_max": 45.0,
            "top10_hard": 80.0,
            "dev_max": 12.0,
            "dev_hard": 40.0,
            "bundle_max": 30.0,
            "bundle_hard": 60.0,
            "pump1h_max": 120.0,
            "pump_is_kill": False,
            "lp_safe_min": 40.0,
            "lp_is_kill": True,
            "dev_rugs_is_kill": True,
            "fail_closed": False,
            "mint_freeze_fail_closed": True,
            "soft_as_penalty": True,
            "rugcheck_cache_s": 600,
            "rugcheck_cap_per_cycle": 8,
        },
        "analyst": {
            "pass_score": 40,
            "signal_min_score": 24,
            "signals_enabled": True,
        },
        "executor": {
            "min_frac": 0.02,
            "max_frac": 0.06,
            "max_open": 10,
            "reentry_cooldown_s": 5 * 60,
            "max_slip": 0.02,
            "min_size_usd": 8.0,
            "consec_loss_pause_n": 4,
            "consec_loss_pause_s": 8 * 60,
            "daily_dd_pct": 0.12,
        },
        "risk": {
            "stop_pct": 0.05,
            "trail_activate": 0.08,
            "trail_pct": 0.04,
            "time_exit_s": 12 * 60,
            "flat_abs_pct": 3.0,
            "partial_tp_pct": 0.10,
            "partial_tp_frac": 0.5,
            "jump_verify_pct": 0.50,
        },
    },
}

def _data_base():
    try:
        import common
        return common.data_dir()
    except Exception:
        return BASE

def profile_path():
    return os.path.join(_data_base(), "profile.txt")

def overrides_path():
    return os.path.join(_data_base(), "overrides.json")

def profile_name():
    env = (os.environ.get("DESK_PROFILE") or "").strip().lower()
    if env in PROFILES:
        return env
    try:
        with open(profile_path(), encoding="utf-8") as f:
            name = f.read().strip().lower()
        if name in PROFILES:
            return name
    except Exception:
        pass
    return "profit"

# Paramètres modifiables à chaud (liste blanche) : section, clé, min, max.
# ai_local.py est le seul à écrire overrides.json, après validation des bornes.
OVERRIDABLE = {
    "liq_min": ("filter", "liq_min", 5_000, 500_000),
    "max_open": ("executor", "max_open", 1, 20),
    "stop_pct": ("risk", "stop_pct", 0.02, 0.15),
    "trail_pct": ("risk", "trail_pct", 0.02, 0.15),
    "trail_activate": ("risk", "trail_activate", 0.04, 0.50),
    "max_frac": ("executor", "max_frac", 0.01, 0.08),   # taille max par position : jamais > 8 %
}
_ov_cache = {"mtime": None, "data": {}}

def overrides():
    path = overrides_path()
    try:
        m = (path, os.path.getmtime(path))
    except OSError:
        return {}
    if m != _ov_cache["mtime"]:
        try:
            d = json.load(open(path, encoding="utf-8"))
            _ov_cache.update(mtime=m, data=d if isinstance(d, dict) else {})
        except Exception:
            _ov_cache.update(mtime=m, data={})
    return _ov_cache["data"]

def cfg():
    base = PROFILES[profile_name()]
    ov = overrides()
    if not ov:
        return base
    c = copy.deepcopy(base)
    for k, v in ov.items():
        spec = OVERRIDABLE.get(k)
        if not spec or not isinstance(v, (int, float)):
            continue
        sec, key, lo, hi = spec
        v = max(lo, min(hi, v))
        c[sec][key] = int(v) if isinstance(lo, int) and isinstance(hi, int) else float(v)
        if key == "max_frac":
            c[sec]["min_frac"] = min(c[sec].get("min_frac", v), c[sec][key])
    return c
