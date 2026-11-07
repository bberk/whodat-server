"""Pure domain calculation engine for projected auction budgets and trade balance validation.

Follows ARCHITECTURE.md: pure standard library only, exact Decimal arithmetic (no floats),
and 100% line and branch test coverage.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

_TWO_PLACES = Decimal("0.01")
_ZERO = Decimal("0.00")

TradeConditionStatus = Literal["pending", "fulfilled", "void"]
VALID_CONDITION_STATUSES: frozenset[str] = frozenset({"pending", "fulfilled", "void"})


def _quantize_currency(value: Decimal) -> Decimal:
    """Quantize an auction currency value to exact two decimal places."""
    return value.quantize(_TWO_PLACES)


class TradeBudgetDomainError(Exception):
    """Base error for trade budget domain rules."""


class ZeroSumViolationError(TradeBudgetDomainError):
    """Raised when trade auction dollar deltas for a draft year do not sum to zero."""

    def __init__(self, draft_year: int, total_sum: Decimal) -> None:
        self.draft_year = draft_year
        self.total_sum = total_sum
        super().__init__(
            f"Trade auction dollars for draft year {draft_year} must sum to 0.00; "
            f"got {total_sum:+f}"
        )


class InvalidConditionStatusError(TradeBudgetDomainError):
    """Raised when a condition has an unrecognized status."""

    def __init__(self, status: str) -> None:
        self.status = status
        allowed = sorted(VALID_CONDITION_STATUSES)
        super().__init__(f"Invalid condition status {status!r}; expected one of {allowed}")


@dataclass(frozen=True)
class BudgetDelta:
    """An unconditional auction budget delta for one team in a target draft year."""

    team_id: str
    draft_year: int
    amount: Decimal

    def __post_init__(self) -> None:
        if not self.team_id:
            raise ValueError("team_id must not be empty")
        object.__setattr__(self, "amount", _quantize_currency(self.amount))


@dataclass(frozen=True)
class TradeCondition:
    """A conditional auction budget clause between two teams."""

    condition_id: str
    paying_team: str
    receiving_team: str
    draft_year: int
    amount: Decimal
    status: TradeConditionStatus

    def __post_init__(self) -> None:
        if not self.condition_id:
            raise ValueError("condition_id must not be empty")
        if not self.paying_team:
            raise ValueError("paying_team must not be empty")
        if not self.receiving_team:
            raise ValueError("receiving_team must not be empty")
        if self.paying_team == self.receiving_team:
            raise ValueError("paying_team and receiving_team must be distinct")
        if self.amount < _ZERO:
            raise ValueError("conditional amount must be non-negative")
        if self.status not in VALID_CONDITION_STATUSES:
            raise InvalidConditionStatusError(self.status)
        object.__setattr__(self, "amount", _quantize_currency(self.amount))


@dataclass(frozen=True)
class TeamBudgetProjection:
    """Calculated auction budget projection for one team in a target draft year."""

    team_id: str
    starting_budget: Decimal
    base_trade_delta: Decimal
    fulfilled_conditional_delta: Decimal
    net_delta: Decimal
    projected_budget: Decimal
    pending_conditional_delta: Decimal
    is_negative_budget: bool

    @property
    def starting_budget_str(self) -> str:
        return f"{self.starting_budget:.2f}"

    @property
    def base_trade_delta_str(self) -> str:
        return f"{self.base_trade_delta:.2f}"

    @property
    def fulfilled_conditional_delta_str(self) -> str:
        return f"{self.fulfilled_conditional_delta:.2f}"

    @property
    def net_delta_str(self) -> str:
        return f"{self.net_delta:.2f}"

    @property
    def projected_budget_str(self) -> str:
        return f"{self.projected_budget:.2f}"

    @property
    def pending_conditional_delta_str(self) -> str:
        return f"{self.pending_conditional_delta:.2f}"


def validate_zero_sum(deltas: Sequence[BudgetDelta]) -> None:
    """Verify that auction dollar deltas sum to 0.00 for each distinct draft year.

    Raises:
        ZeroSumViolationError: If any draft year's deltas do not sum to exactly zero.
    """
    year_totals: dict[int, Decimal] = defaultdict(lambda: _ZERO)
    for delta in deltas:
        year_totals[delta.draft_year] += delta.amount

    for year, total in sorted(year_totals.items()):
        if total != _ZERO:
            raise ZeroSumViolationError(year, total)


def calculate_team_budget_projections(
    *,
    starting_budget: Decimal,
    known_teams: Sequence[str],
    deltas: Sequence[BudgetDelta],
    conditions: Sequence[TradeCondition],
    target_draft_year: int,
) -> list[TeamBudgetProjection]:
    """Compute projected auction budgets for all known teams for a given draft year.

    Args:
        starting_budget: Base draft budget before any trade adjustments (e.g. 200.00).
        known_teams: List of all canonical team/owner identifiers in the league.
        deltas: All unconditional budget adjustments from confirmed trades.
        conditions: All conditional clauses from confirmed trades.
        target_draft_year: The draft year to calculate projections for.

    Returns:
        List of TeamBudgetProjection objects sorted by team_id.
    """
    base_budget = _quantize_currency(starting_budget)

    # Validate zero-sum rule across unconditional deltas
    validate_zero_sum(deltas)

    # Aggregate unconditional deltas for the target draft year
    base_deltas: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    for delta in deltas:
        if delta.draft_year == target_draft_year:
            base_deltas[delta.team_id] += delta.amount

    # Aggregate conditional clauses for the target draft year
    fulfilled_deltas: dict[str, Decimal] = defaultdict(lambda: _ZERO)
    pending_deltas: dict[str, Decimal] = defaultdict(lambda: _ZERO)

    for cond in conditions:
        if cond.draft_year != target_draft_year:
            continue

        if cond.status == "fulfilled":
            fulfilled_deltas[cond.receiving_team] += cond.amount
            fulfilled_deltas[cond.paying_team] -= cond.amount
        elif cond.status == "pending":
            pending_deltas[cond.receiving_team] += cond.amount
            pending_deltas[cond.paying_team] -= cond.amount
        # 'void' contributes zero

    # Build projections for every known team, preserving order or sorting deterministically
    projections: list[TeamBudgetProjection] = []
    # Ensure any team with deltas/conditions is represented even if omitted from known_teams
    all_team_ids = sorted(
        set(known_teams)
        | set(base_deltas.keys())
        | set(fulfilled_deltas.keys())
        | set(pending_deltas.keys())
    )

    for team_id in all_team_ids:
        team_base_delta = _quantize_currency(base_deltas[team_id])
        team_fulfilled_delta = _quantize_currency(fulfilled_deltas[team_id])
        team_net_delta = _quantize_currency(team_base_delta + team_fulfilled_delta)
        team_projected_budget = _quantize_currency(base_budget + team_net_delta)
        team_pending_delta = _quantize_currency(pending_deltas[team_id])
        is_negative = team_projected_budget < _ZERO

        projections.append(
            TeamBudgetProjection(
                team_id=team_id,
                starting_budget=base_budget,
                base_trade_delta=team_base_delta,
                fulfilled_conditional_delta=team_fulfilled_delta,
                net_delta=team_net_delta,
                projected_budget=team_projected_budget,
                pending_conditional_delta=team_pending_delta,
                is_negative_budget=is_negative,
            )
        )

    return projections
