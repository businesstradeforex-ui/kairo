"""Extra entry checks used only by mode turbo.

They read fields the scout already stores (5-minute trades, 5-minute and
1-hour volume). Missing fields do not invent a pass: too few trades is a skip.
"""

def pressure_block(txns):
    m5 = (txns or {}).get("m5") or {}
    buys = float(m5.get("buys") or 0)
    sells = float(m5.get("sells") or 0)
    total = buys + sells
    if total < 8:
        return "too_few_trades"
    if buys / total < 0.45:
        return "sell_pressure"
    return None

def velocity_block(vol):
    m5 = float((vol or {}).get("m5") or 0)
    h1 = float((vol or {}).get("h1") or 0)
    if h1 < 20_000:
        return None
    if m5 * 12 < h1 * 0.25:
        return "volume_fading"
    return None

def turbo_block(candidate):
    reason = pressure_block(candidate.get("txns"))
    if reason:
        return reason
    return velocity_block(candidate.get("vol"))
