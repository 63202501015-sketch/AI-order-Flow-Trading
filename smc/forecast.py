"""Leakage-safe 15-minute SMC forecast context.

This module does not claim calibrated probabilities.  It combines confirmed
SMC structure with momentum, volatility, volume and liquidity-sweep context.
For a real 15-minute model, feed 1m/5m OHLCV and validate out-of-sample.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np
import pandas as pd

from .analyzer import analyze
from .structure import Trend, StructureEventType


@dataclass
class Forecast15m:
    signal: str
    confidence: float
    up_score: float
    down_score: float
    price: float
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    structure: str
    liquidity_sweep: str
    rsi14: float
    atr14: float
    relative_volume: float
    reasons: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"15m context: {self.signal} | confidence {self.confidence:.1f}%\n"
            f"Structure: {self.structure} | Liquidity: {self.liquidity_sweep}\n"
            f"Price/Entry: {self.price:.4f} / {self.entry:.4f}\n"
            f"SL: {self.stop_loss:.4f} | TP1: {self.take_profit_1:.4f} | TP2: {self.take_profit_2:.4f}\n"
            f"RSI14: {self.rsi14:.1f} | ATR14: {self.atr14:.4f} | RelVol: {self.relative_volume:.2f}x"
        )


def _features(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["ema9"] = x["close"].ewm(span=9, adjust=False).mean()
    x["ema21"] = x["close"].ewm(span=21, adjust=False).mean()

    delta = x["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    ag = gain.ewm(alpha=1/14, adjust=False).mean()
    al = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    x["rsi14"] = (100 - 100 / (1 + rs)).fillna(50.0)

    prev = x["close"].shift(1)
    tr = pd.concat([
        x["high"] - x["low"],
        (x["high"] - prev).abs(),
        (x["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    x["atr14"] = tr.ewm(alpha=1/14, adjust=False).mean()

    vol_ma = x["volume"].rolling(20, min_periods=1).mean() if "volume" in x else pd.Series(1.0, index=x.index)
    x["relative_volume"] = (x["volume"] / vol_ma.replace(0, np.nan)).fillna(1.0) if "volume" in x else 1.0
    x["momentum3"] = x["close"].pct_change(3).fillna(0.0)
    return x


def _liquidity_sweep(df: pd.DataFrame, lookback: int = 20) -> str:
    if len(df) <= lookback:
        return "NONE"
    cur = df.iloc[-1]
    hist = df.iloc[-lookback-1:-1]
    hi, lo = float(hist["high"].max()), float(hist["low"].min())
    if cur["low"] < lo and cur["close"] > lo:
        return "SELL_SIDE_SWEEP"
    if cur["high"] > hi and cur["close"] < hi:
        return "BUY_SIDE_SWEEP"
    return "NONE"


def forecast_15m(df: pd.DataFrame) -> Forecast15m:
    """Return a 15-minute directional context from completed candles.

    Use 5-minute bars for the intended horizon (3 bars = 15 minutes).
    The confidence value is a heuristic evidence-strength score, not a
    statistically calibrated probability.
    """
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    if len(df) < 25:
        raise ValueError("forecast_15m requires at least 25 completed candles")
    if not df.index.is_monotonic_increasing:
        raise ValueError("df must be sorted by time ascending")

    x = _features(df)
    cur = x.iloc[-1]
    smc = analyze(df)
    sweep = _liquidity_sweep(x)
    up = down = 0.0
    reasons: list[str] = []

    if smc.trend == Trend.UP:
        up += 3.0; reasons.append("SMC trend bullish")
    elif smc.trend == Trend.DOWN:
        down += 3.0; reasons.append("SMC trend bearish")

    if smc.last_event is not None:
        tag = smc.last_event.type.value
        if smc.last_event.direction == Trend.UP:
            up += 2.0 if smc.last_event.type == StructureEventType.CHOCH else 1.5
            reasons.append(f"{tag} bullish")
        elif smc.last_event.direction == Trend.DOWN:
            down += 2.0 if smc.last_event.type == StructureEventType.CHOCH else 1.5
            reasons.append(f"{tag} bearish")

    active = smc.active_order_blocks()
    if active:
        ob = active[-1]
        atr = max(float(cur["atr14"]), 1e-12)
        distance = min(abs(float(cur["close"]) - ob.top), abs(float(cur["close"]) - ob.bottom)) / atr
        if distance <= 1.0:
            if ob.direction == Trend.UP:
                up += 2.0; reasons.append("near bullish order block")
            else:
                down += 2.0; reasons.append("near bearish order block")

    if sweep == "SELL_SIDE_SWEEP":
        up += 2.0; reasons.append("sell-side liquidity swept")
    elif sweep == "BUY_SIDE_SWEEP":
        down += 2.0; reasons.append("buy-side liquidity swept")

    if cur["ema9"] > cur["ema21"]:
        up += 1.0; reasons.append("EMA9 > EMA21")
    elif cur["ema9"] < cur["ema21"]:
        down += 1.0; reasons.append("EMA9 < EMA21")

    rsi = float(cur["rsi14"])
    if 52 <= rsi < 72:
        up += 1.0
    elif 28 < rsi <= 48:
        down += 1.0

    if cur["momentum3"] > 0:
        up += 0.75
    elif cur["momentum3"] < 0:
        down += 0.75

    rv = float(cur["relative_volume"])
    if rv >= 1.5:
        if cur["close"] > cur["open"]:
            up += 0.75; reasons.append("bullish relative-volume expansion")
        elif cur["close"] < cur["open"]:
            down += 0.75; reasons.append("bearish relative-volume expansion")

    edge = up - down
    signal = "BUY" if edge >= 3.0 else "SELL" if edge <= -3.0 else "WAIT"
    total = up + down
    confidence = 50.0 if total == 0 else 50.0 + min(45.0, abs(edge) / total * 45.0)

    price = float(cur["close"])
    atr = max(float(cur["atr14"]), 1e-12)
    if signal == "BUY":
        sl, tp1, tp2 = price - 1.5*atr, price + 1.5*atr, price + 2.5*atr
    elif signal == "SELL":
        sl, tp1, tp2 = price + 1.5*atr, price - 1.5*atr, price - 2.5*atr
    else:
        sl = tp1 = tp2 = price

    structure = "NONE" if smc.last_event is None else f"{smc.last_event.type.value}_{smc.last_event.direction.value.upper()}"
    return Forecast15m(
        signal=signal, confidence=confidence, up_score=up, down_score=down,
        price=price, entry=price, stop_loss=sl, take_profit_1=tp1,
        take_profit_2=tp2, structure=structure, liquidity_sweep=sweep,
        rsi14=rsi, atr14=atr, relative_volume=rv, reasons=reasons,
    )
