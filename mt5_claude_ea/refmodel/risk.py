"""Deterministic guards mirrored from Risk.mqh / Execution.mqh."""
from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass
from typing import Optional

EPS = 1e-9


# ---------- price / volume normalisation -------------------------------------------------
def round_to_tick(price: float, tick: float, mode: str = "nearest") -> float:
    q = price / tick
    n = {"nearest": lambda: math.floor(q + 0.5), "down": lambda: math.floor(q + EPS),
         "up": lambda: math.ceil(q - EPS)}[mode]()
    return round(n * tick, 10)


def normalize_volume(vol: float, vmin: float, vmax: float, step: float) -> float:
    """Floor to step, cap at max. Below the broker minimum -> 0 (never round risk UP)."""
    if not (vol > 0 and step > 0 and vmin > 0 and vmax >= vmin):
        return 0.0
    v = math.floor(vol / step + EPS) * step
    v = min(v, math.floor(vmax / step + EPS) * step)
    return round(v, 8) if v + EPS >= vmin else 0.0


def volume_for_risk(risk_money: float, sl_distance: float, tick_size: float, tick_value: float) -> float:
    """Lots such that a stop-out at sl_distance loses ~risk_money (before slippage)."""
    if risk_money <= 0 or sl_distance <= 0 or tick_size <= 0 or tick_value <= 0:
        return 0.0
    return risk_money / (sl_distance / tick_size * tick_value)


# ---------- initial stops -------------------------------------------------------------------
def initial_stops(side: str, entry: float, atr: float, tick: float,
                  sl_mult: float = 1.0, tp_mult: float = 3.0) -> tuple[float, float]:
    if side == "BUY":
        return round_to_tick(entry - sl_mult * atr, tick), round_to_tick(entry + tp_mult * atr, tick)
    return round_to_tick(entry + sl_mult * atr, tick), round_to_tick(entry - tp_mult * atr, tick)


def stops_valid(side: str, bid: float, ask: float, sl: float, tp: float, min_dist: float) -> bool:
    """Broker StopLevel rule for market orders. min_dist = stops_level_points * point."""
    if side == "BUY":
        return sl > 0 and tp > 0 and bid - sl >= min_dist - EPS and tp - bid >= min_dist - EPS
    return sl > 0 and tp > 0 and sl - ask >= min_dist - EPS and ask - tp >= min_dist - EPS


# ---------- break-even + trailing (monotonic) ---------------------------------------------------
def trail_sl(side: str, entry: float, cur_sl: float, price: float, atr: float, tick: float, *,
             be_trigger: float = 1.0, trail_start: float = 1.5, trail_dist: float = 1.0,
             be_buffer_ticks: int = 0, min_dist: float = 0.0, freeze_dist: float = 0.0) -> Optional[float]:
    """Return a new SL or None. `price` is Bid for BUY, Ask for SELL.

    +be_trigger*ATR  -> SL to entry (+ optional buffer in ticks, default 0)
    +trail_start*ATR -> SL follows price at trail_dist*ATR
    BUY SL never decreases; SELL SL never increases. Respects stop/freeze distance.
    """
    if atr <= 0 or tick <= 0:
        return None
    sign = 1 if side == "BUY" else -1
    gain = (price - entry) * sign
    cand = None
    if gain >= be_trigger * atr - EPS:
        cand = entry + sign * be_buffer_ticks * tick
    if gain >= trail_start * atr - EPS:
        t = price - sign * trail_dist * atr
        cand = t if cand is None else (max(cand, t) if sign == 1 else min(cand, t))
    if cand is None:
        return None
    if cur_sl > 0 and freeze_dist > 0 and abs(price - cur_sl) <= freeze_dist + EPS:
        return None                                   # inside freeze level: broker would reject
    limit = price - sign * min_dist                   # closest SL the broker accepts
    if sign == 1:
        cand = round_to_tick(min(cand, limit), tick, "down")
        return cand if (cur_sl <= 0 or cand >= cur_sl + tick - EPS) else None
    cand = round_to_tick(max(cand, limit), tick, "up")
    return cand if (cur_sl <= 0 or cand <= cur_sl - tick + EPS) else None


# ---------- daily stop with persistent latch --------------------------------------------------------
@dataclass
class DailyState:
    day: int = 0            # broker day as yyyymmdd
    latched: bool = False
    reason: str = ""


class DailyGuard:
    """Latches when realized + floating P/L (incl. commission/swap) of MANAGED trades reaches
    +profit_target or -loss_limit in account currency. Stays latched until the broker day
    changes, across restarts (state file here; terminal GlobalVariables in the EA)."""

    def __init__(self, path: str, profit_target: float = 200.0, loss_limit: float = 100.0):
        self.path, self.profit_target, self.loss_limit = path, profit_target, loss_limit
        self.state = self._load()

    def _load(self) -> DailyState:
        try:
            with open(self.path, encoding="utf-8") as fh:
                d = json.load(fh)
            return DailyState(int(d["day"]), bool(d["latched"]), str(d.get("reason", "")))
        except FileNotFoundError:
            return DailyState()
        except (ValueError, KeyError, TypeError):
            # Unreadable state must not silently re-enable trading.
            return DailyState(day=-1, latched=True, reason="state file corrupt")

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(asdict(self.state), fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def update(self, day: int, realized: float, floating: float) -> bool:
        """Returns True while trading must stay stopped for `day`."""
        if self.state.day == -1:
            return True                                # corrupt state: stay stopped (manual reset)
        if day != self.state.day:
            self.state = DailyState(day=day)
            self._save()
        if not self.state.latched:
            total = realized + floating
            if self.profit_target > 0 and total >= self.profit_target - EPS:
                self.state.latched, self.state.reason = True, "daily profit target"
            elif self.loss_limit > 0 and total <= -self.loss_limit + EPS:
                self.state.latched, self.state.reason = True, "daily loss limit"
            if self.state.latched:
                self._save()
        return self.state.latched


def quick_profit_hit(enabled: bool, floating: float, threshold: float = 9.0) -> bool:
    return enabled and threshold > 0 and floating >= threshold - EPS


# ---------- entry gate ------------------------------------------------------------------------------
@dataclass
class GateInput:
    signal: str = "HOLD"
    confidence: float = 0.0
    signal_bar_time: int = 0
    last_closed_bar_time: int = 0
    signal_age_sec: float = 0.0
    allow_orders: bool = False            # InpAllowOrders, default OFF
    trade_permitted: bool = True          # terminal + account + symbol trade mode
    symbol_allowed: bool = True
    session_ok: bool = False
    spread_points: float = 0.0
    max_spread_points: float = 0.0
    daily_latched: bool = False
    trades_today: int = 0
    max_trades_per_day: int = 0
    sec_since_last_entry: float = 1e18
    cooldown_sec: float = 0.0
    managed_positions: int = 0
    foreign_position_on_netting: bool = False
    last_order_bar_time: int = -1
    min_confidence: float = 0.0
    max_signal_age_sec: float = 0.0
    volume: float = 0.0
    stops_ok: bool = False
    margin_ok: bool = False


def entry_gate(g: GateInput) -> tuple[bool, str]:
    """Ordered, fail-closed. The first failing check names the reason; the AI can skip none."""
    checks = [
        (g.signal in ("BUY", "SELL"), "signal is HOLD/invalid"),
        (g.allow_orders, "live orders not enabled (InpAllowOrders=false)"),
        (g.trade_permitted, "trading not permitted"),
        (g.symbol_allowed, "symbol not allowlisted"),
        (g.signal_bar_time == g.last_closed_bar_time and g.signal_bar_time > 0, "signal is not for the last closed bar"),
        (g.signal_age_sec <= g.max_signal_age_sec, "signal stale"),
        (g.last_order_bar_time != g.signal_bar_time, "bar already traded (dedup)"),
        (g.confidence >= g.min_confidence, "confidence below minimum"),
        (not g.daily_latched, "daily stop latched"),
        (g.session_ok, "outside allowed sessions"),
        (g.max_spread_points > 0 and g.spread_points <= g.max_spread_points, "spread above limit"),
        (g.trades_today < g.max_trades_per_day, "daily trade cap reached"),
        (g.sec_since_last_entry >= g.cooldown_sec, "cooldown active"),
        (not g.foreign_position_on_netting, "netting account holds a non-EA position on this symbol"),
        (g.managed_positions == 0, "managed position already open"),
        (g.volume > 0, "volume below broker minimum"),
        (g.stops_ok, "SL/TP violate broker stop level"),
        (g.margin_ok, "insufficient free margin"),
    ]
    for ok, reason in checks:
        if not ok:
            return False, reason
    return True, "ok"


def reverse_plan(reverse_enabled: bool, position_side: Optional[str], signal: str) -> str:
    """NONE | ENTER | IGNORE_OPPOSITE | CLOSE_THEN_RECHECK. Never opens against an open position."""
    if signal not in ("BUY", "SELL"):
        return "NONE"
    if position_side is None:
        return "ENTER"
    if position_side == signal:
        return "NONE"
    return "CLOSE_THEN_RECHECK" if reverse_enabled else "IGNORE_OPPOSITE"
