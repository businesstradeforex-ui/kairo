"""Paper fill model: pool impact, swap fee, and a flat priority fee.

Used by mode turbo. The original executor.slippage() stays the formula for
strict, agressif and profit so those results do not move.
"""
FEE = 0.0025          # 0.25% swap, same order of magnitude as the original desk
PRIORITY_FEE_USD = 0.02  # paper stand-in for a Solana priority fee, not a live quote

def impact(size_usd, liq_usd):
    quote = max(float(liq_usd) / 2.0, 1.0)
    return min(max(float(size_usd), 0.0) / quote, 0.25)

def paper_buy(price, size_usd, liq_usd, fee=FEE, priority_fee_usd=PRIORITY_FEE_USD):
    price = float(price)
    size_usd = float(size_usd)
    slip = min(impact(size_usd, liq_usd) + fee, 0.25)
    fill = price * (1.0 + slip)
    fee_usd = size_usd * fee
    cost = size_usd + priority_fee_usd
    qty = (size_usd / fill) if fill > 0 else 0.0
    return {"side": "buy", "fill_price": fill, "slip": slip, "fee_usd": fee_usd,
            "priority_fee_usd": float(priority_fee_usd), "cost_usd": cost, "qty": qty}

def size_for_score(equity, score, min_frac, max_frac):
    """Linear size between the profile bounds. Never above max_frac of equity."""
    lo, hi = float(min_frac), float(max_frac)
    hi = min(hi, 0.08)
    lo = min(lo, hi)
    frac = lo + (hi - lo) * max(0.0, min(1.0, (float(score) - 20.0) / 60.0))
    return max(0.0, min(frac, hi) * float(equity))
