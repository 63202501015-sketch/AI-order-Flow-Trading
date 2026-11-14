"""3-model voting. Votes are correlated model opinions, NOT independent statistical evidence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .models import AISignal

REQUIRED_VOTES = 3


@dataclass(frozen=True)
class VoteOutcome:
    signal: str
    confidence: float
    reason: str
    unanimous: bool
    disagreement: bool


def validate_vote_models(models: Sequence[str]) -> None:
    cleaned = [m.strip() for m in models]
    if len(cleaned) != REQUIRED_VOTES or any(not m for m in cleaned):
        raise ValueError("voting requires exactly 3 model ids")
    if len({m.lower() for m in cleaned}) != REQUIRED_VOTES:
        raise ValueError("voting requires 3 genuinely distinct model ids")


def tally(votes: Sequence[Optional[AISignal]]) -> VoteOutcome:
    """All 3 responses required; >=2 identical BUY or SELL wins; anything else HOLD.

    Confidence = mean confidence of the agreeing votes only. It remains an
    uncalibrated self-report and must not be read as a win probability.
    """
    if len(votes) != REQUIRED_VOTES or any(v is None for v in votes):
        return VoteOutcome("HOLD", 0.0, "vote incomplete: not all 3 models answered", False, False)
    names = [v.signal for v in votes]  # type: ignore[union-attr]
    disagreement = len(set(names)) > 1
    for side in ("BUY", "SELL"):
        agree = [v for v in votes if v.signal == side]  # type: ignore[union-attr]
        if len(agree) >= 2:
            conf = sum(v.confidence for v in agree) / len(agree)  # type: ignore[union-attr]
            return VoteOutcome(side, conf, f"vote {len(agree)}/3 {side}: {agree[0].reason}"[:300],
                               len(agree) == 3, disagreement)
    return VoteOutcome("HOLD", 0.0, "vote: no 2/3 BUY or SELL majority (" + ",".join(names) + ")",
                       not disagreement, disagreement)
