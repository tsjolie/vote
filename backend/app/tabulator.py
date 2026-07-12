"""Instant-runoff (ranked-choice) tabulation.

Implemented as a pure function per instructions.md §8 so it can be unit-tested
without any database or framework dependencies.

    tabulate(options, ballots, poll_id, question_id) -> TallyResult

`options` is the ordered list of the question's *current* option ids.
`ballots` is a list of rankings; each ranking is a full permutation of `options`
(only counted ballots should be passed in — invalidated/banned ballots are
excluded by the caller).
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Optional

# Tiebreak stage identifiers, surfaced in the API/charts.
TB_BORDA = "borda"
TB_FIRST_CHOICE = "first_choice"
TB_RANDOM = "random"


@dataclass
class Round:
    round: int
    counts: dict[str, int]
    eliminated: Optional[str] = None
    tiebreak_used: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "round": self.round,
            "counts": self.counts,
            "eliminated": self.eliminated,
            "tiebreak_used": self.tiebreak_used,
        }


@dataclass
class TallyResult:
    question_id: str
    total_ballots: int
    winner_option_id: Optional[str]
    rounds: list[Round] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "question_id": self.question_id,
            "total_ballots": self.total_ballots,
            "winner_option_id": self.winner_option_id,
            "rounds": [r.to_dict() for r in self.rounds],
        }


def _current_choice(ranking: list[str], remaining: set[str]) -> Optional[str]:
    """Highest-ranked option still in the remaining candidate set."""
    for opt in ranking:
        if opt in remaining:
            return opt
    return None


def _count_round(ballots: list[list[str]], remaining: set[str]) -> dict[str, int]:
    counts = {opt: 0 for opt in remaining}
    for ranking in ballots:
        choice = _current_choice(ranking, remaining)
        if choice is not None:
            counts[choice] += 1
    return counts


def _borda_scores(options: list[str], ballots: list[list[str]]) -> dict[str, int]:
    """Borda over ALL active ballots using each ballot's full original ranking.

    A 1st-place option on an N-option question scores N-1, last scores 0.
    """
    n = len(options)
    scores = {opt: 0 for opt in options}
    for ranking in ballots:
        for idx, opt in enumerate(ranking):
            # rank_position is 1-indexed: N - rank_position == N - (idx + 1)
            scores[opt] += n - (idx + 1)
    return scores


def _resolve_tiebreak(
    tied: list[str],
    borda: dict[str, int],
    first_choice: dict[str, int],
    poll_id: str,
    question_id: str,
) -> tuple[str, str]:
    """Pick exactly ONE candidate to eliminate from `tied`.

    Returns (eliminated_id, stage). Stages, in order:
      1. borda        — lowest Borda score is eliminated.
      2. first_choice — fewest round-1 first choices is eliminated.
      3. random       — deterministic PRNG seeded from poll+question.

    For a final two-way tie the caller eliminates one and treats the survivor as
    the winner; "higher Borda wins" is exactly "lowest Borda is eliminated".
    """
    # Stage 1: Borda.
    min_borda = min(borda[c] for c in tied)
    borda_low = [c for c in tied if borda[c] == min_borda]
    if len(borda_low) == 1:
        return borda_low[0], TB_BORDA

    # Stage 2: fewest round-1 first-choice votes among the Borda-tied set.
    min_fc = min(first_choice[c] for c in borda_low)
    fc_low = [c for c in borda_low if first_choice[c] == min_fc]
    if len(fc_low) == 1:
        return fc_low[0], TB_FIRST_CHOICE

    # Stage 3: deterministic pseudo-random shuffle of the still-tied set.
    ordered = sorted(fc_low)  # lexicographic sort first for determinism
    seed = hashlib.sha256(
        f"{poll_id}{question_id}tiebreak".encode("utf-8")
    ).digest()
    rng = random.Random(int.from_bytes(seed, "big"))
    rng.shuffle(ordered)
    return ordered[0], TB_RANDOM


def tabulate(
    options: list[str],
    ballots: list[list[str]],
    poll_id: str = "",
    question_id: str = "",
) -> TallyResult:
    """Run instant-runoff over `ballots` and return the full elimination story."""
    total = len(ballots)
    result = TallyResult(
        question_id=question_id, total_ballots=total, winner_option_id=None
    )
    if total == 0 or not options:
        return result

    borda = _borda_scores(options, ballots)
    round1 = _count_round(ballots, set(options))

    remaining: set[str] = set(options)
    round_num = 0

    while True:
        round_num += 1
        counts = _count_round(ballots, remaining)

        # Step 2: outright majority (> 50% of active ballots) wins.
        for cand, c in counts.items():
            if c * 2 > total:
                result.rounds.append(Round(round=round_num, counts=counts))
                result.winner_option_id = cand
                return result

        # Step 3: final two-way exact tie -> pick winner via the tiebreak chain.
        if len(remaining) == 2:
            a, b = list(remaining)
            if counts[a] == counts[b]:
                loser, stage = _resolve_tiebreak(
                    sorted(remaining), borda, round1, poll_id, question_id
                )
                winner = a if loser == b else b
                result.rounds.append(
                    Round(
                        round=round_num,
                        counts=counts,
                        eliminated=loser,
                        tiebreak_used=stage,
                    )
                )
                result.winner_option_id = winner
                return result
            # Not tied but no majority is impossible with 2 candidates; guard anyway.
            winner = a if counts[a] > counts[b] else b
            result.rounds.append(Round(round=round_num, counts=counts))
            result.winner_option_id = winner
            return result

        # Step 4: eliminate exactly one lowest candidate (tiebreak if needed).
        min_count = min(counts.values())
        lowest = [c for c in counts if counts[c] == min_count]
        if len(lowest) == 1:
            eliminated, stage = lowest[0], None
        else:
            eliminated, stage = _resolve_tiebreak(
                lowest, borda, round1, poll_id, question_id
            )

        result.rounds.append(
            Round(
                round=round_num,
                counts=counts,
                eliminated=eliminated,
                tiebreak_used=stage,
            )
        )
        remaining.discard(eliminated)
