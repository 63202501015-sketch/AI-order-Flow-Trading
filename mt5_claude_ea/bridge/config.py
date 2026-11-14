"""Bridge configuration from environment (.env is never committed). Fail closed on bad config."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Mapping, Optional

from .voting import validate_vote_models

LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")

# USD per 1M tokens (input, output). Snapshot of Anthropic first-party list prices
# as documented on 2026-11-03; used ONLY for a rough spend estimate in the audit log.
# Override with PRICE_TABLE_JSON; verify against the current pricing page.
DEFAULT_PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}


class ConfigError(RuntimeError):
    pass


def _bool(env: Mapping[str, str], key: str, default: bool = False) -> bool:
    return env.get(key, str(default)).strip().lower() == "true"


def _num(env: Mapping[str, str], key: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(env.get(key, default))
    except ValueError as exc:
        raise ConfigError(f"{key} is not a number") from exc
    if not (lo <= v <= hi):
        raise ConfigError(f"{key} out of range [{lo}, {hi}]")
    return v


@dataclass(frozen=True)
class Settings:
    bridge_token: str = ""
    ai_enabled: bool = False
    api_key: str = field(default="", repr=False)
    model: str = "claude-opus-5-5"
    voting_enabled: bool = False
    vote_models: tuple[str, ...] = ()
    effort: str = "low"
    max_tokens: int = 4096
    request_timeout: float = 20.0      # per attempt
    decision_deadline: float = 75.0    # whole decision incl. retries
    max_retries: int = 5
    backoff_base: float = 0.5
    backoff_max: float = 8.0
    cb_threshold: int = 5
    cb_cooldown: float = 300.0
    stale_max_age: float = 240.0       # seconds after bar close a request is still accepted
    clock_skew: float = 5.0
    symbol_allowlist: tuple[str, ...] = ("XAUUSD", "XAUUSD.sc")
    host: str = "127.0.0.1"
    port: int = 8765
    db_path: str = "bridge_state.sqlite3"
    audit_path: str = "logs/bridge_audit.jsonl"
    retention_days: int = 14
    max_daily_cost_usd: float = 10.0   # estimated spend per UTC day; reached => HOLD. 0 disables.
    prompt_price_mode: str = "raw"     # raw | normalized (see bridge/prompt.py)
    prices: Mapping[str, tuple[float, float]] = field(default_factory=lambda: dict(DEFAULT_PRICES))

    @property
    def active_models(self) -> tuple[str, ...]:
        return self.vote_models if self.voting_enabled else (self.model,)

    @property
    def has_key(self) -> bool:
        return bool(self.api_key) and self.api_key != "replace_me"


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    env = os.environ if env is None else env
    token = env.get("BRIDGE_TOKEN", "").strip()
    if token in ("replace_me", "changeme"):
        token = ""
    if token and len(token) < 32:
        raise ConfigError("BRIDGE_TOKEN must be at least 32 characters (use: python -m bridge --new-token)")
    host = env.get("BRIDGE_HOST", "127.0.0.1").strip()
    if host not in LOOPBACK_HOSTS:
        raise ConfigError("BRIDGE_HOST must be a loopback address; the bridge is local-only")
    voting = _bool(env, "VOTING_ENABLED")
    vote_models = tuple(m.strip() for m in env.get("VOTE_MODELS", "").split(",") if m.strip())
    if voting:
        try:
            validate_vote_models(vote_models)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
    effort = env.get("AI_EFFORT", "low").strip()
    if effort not in ("low", "medium", "high", "xhigh", "max"):
        raise ConfigError("AI_EFFORT invalid")
    prices = dict(DEFAULT_PRICES)
    if env.get("PRICE_TABLE_JSON"):
        try:
            for k, v in json.loads(env["PRICE_TABLE_JSON"]).items():
                prices[str(k)] = (float(v[0]), float(v[1]))
        except (ValueError, TypeError, IndexError, KeyError) as exc:
            raise ConfigError("PRICE_TABLE_JSON invalid") from exc
    price_mode = env.get("PROMPT_PRICE_MODE", "raw").strip()
    if price_mode not in ("raw", "normalized"):
        raise ConfigError("PROMPT_PRICE_MODE must be raw or normalized")
    allow = tuple(s.strip() for s in env.get("SYMBOL_ALLOWLIST", "XAUUSD,XAUUSD.sc").split(",") if s.strip())
    if not allow:
        raise ConfigError("SYMBOL_ALLOWLIST is empty")
    return Settings(
        bridge_token=token,
        ai_enabled=_bool(env, "AI_ENABLED"),
        api_key=env.get("ANTHROPIC_API_KEY", "").strip(),
        model=env.get("ANTHROPIC_MODEL", "claude-opus-5-5").strip(),
        voting_enabled=voting,
        vote_models=vote_models,
        effort=effort,
        max_tokens=int(_num(env, "AI_MAX_TOKENS", 4096, 256, 32000)),
        request_timeout=_num(env, "AI_TIMEOUT", 20, 1, 120),
        decision_deadline=_num(env, "DECISION_DEADLINE_SEC", 75, 5, 240),
        max_retries=int(_num(env, "MAX_RETRIES", 5, 0, 5)),
        backoff_base=_num(env, "BACKOFF_BASE_SEC", 0.5, 0.01, 10),
        backoff_max=_num(env, "BACKOFF_MAX_SEC", 8, 0.01, 60),
        cb_threshold=int(_num(env, "CIRCUIT_FAILURE_THRESHOLD", 5, 1, 100)),
        cb_cooldown=_num(env, "CIRCUIT_COOLDOWN_SEC", 300, 1, 86400),
        stale_max_age=_num(env, "STALE_MAX_AGE_SEC", 240, 5, 295),
        clock_skew=_num(env, "CLOCK_SKEW_SEC", 5, 0, 60),
        symbol_allowlist=allow,
        host=host,
        port=int(_num(env, "BRIDGE_PORT", 8765, 1024, 65535)),
        db_path=env.get("BRIDGE_DB_PATH", "bridge_state.sqlite3"),
        audit_path=env.get("BRIDGE_AUDIT_PATH", "logs/bridge_audit.jsonl"),
        retention_days=int(_num(env, "RETENTION_DAYS", 14, 1, 3650)),
        max_daily_cost_usd=_num(env, "MAX_DAILY_COST_USD", 10, 0, 100000),
        prompt_price_mode=price_mode,
        prices=prices,
    )
