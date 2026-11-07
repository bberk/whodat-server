"""Unit tests for the pure trade budget domain engine."""

from decimal import Decimal

import pytest

from app.domain.trade_budget import (
    BudgetDelta,
    InvalidConditionStatusError,
    TeamBudgetProjection,
    TradeCondition,
    ZeroSumViolationError,
    calculate_team_budget_projections,
    validate_zero_sum,
)


def test_budget_delta_quantization_and_validation() -> None:
    delta = BudgetDelta(team_id="team_1", draft_year=2027, amount=Decimal("15.5"))
    assert delta.amount == Decimal("15.50")
    assert delta.team_id == "team_1"
    assert delta.draft_year == 2027

    with pytest.raises(ValueError, match="team_id must not be empty"):
        BudgetDelta(team_id="", draft_year=2027, amount=Decimal("10.00"))


def test_trade_condition_validation() -> None:
    cond = TradeCondition(
        condition_id="c1",
        paying_team="team_bob",
        receiving_team="team_alice",
        draft_year=2027,
        amount=Decimal("5.00"),
        status="fulfilled",
    )
    assert cond.condition_id == "c1"
    assert cond.amount == Decimal("5.00")
    assert cond.status == "fulfilled"

    # Validation errors
    with pytest.raises(ValueError, match="condition_id must not be empty"):
        TradeCondition(
            condition_id="",
            paying_team="team_b",
            receiving_team="team_a",
            draft_year=2027,
            amount=Decimal("5.00"),
            status="pending",
        )

    with pytest.raises(ValueError, match="paying_team must not be empty"):
        TradeCondition(
            condition_id="c2",
            paying_team="",
            receiving_team="team_a",
            draft_year=2027,
            amount=Decimal("5.00"),
            status="pending",
        )

    with pytest.raises(ValueError, match="receiving_team must not be empty"):
        TradeCondition(
            condition_id="c3",
            paying_team="team_b",
            receiving_team="",
            draft_year=2027,
            amount=Decimal("5.00"),
            status="pending",
        )

    with pytest.raises(ValueError, match="paying_team and receiving_team must be distinct"):
        TradeCondition(
            condition_id="c4",
            paying_team="team_same",
            receiving_team="team_same",
            draft_year=2027,
            amount=Decimal("5.00"),
            status="pending",
        )

    with pytest.raises(ValueError, match="conditional amount must be non-negative"):
        TradeCondition(
            condition_id="c5",
            paying_team="team_b",
            receiving_team="team_a",
            draft_year=2027,
            amount=Decimal("-5.00"),
            status="pending",
        )

    msg = "Invalid condition status 'invalid_status'"
    with pytest.raises(InvalidConditionStatusError, match=msg):
        TradeCondition(
            condition_id="c6",
            paying_team="team_b",
            receiving_team="team_a",
            draft_year=2027,
            amount=Decimal("5.00"),
            status="invalid_status",  # type: ignore[arg-type]
        )


def test_validate_zero_sum_passes_for_balanced_trades() -> None:
    # Empty deltas
    validate_zero_sum([])

    # Balanced single year
    deltas = [
        BudgetDelta(team_id="team_a", draft_year=2027, amount=Decimal("-15.00")),
        BudgetDelta(team_id="team_b", draft_year=2027, amount=Decimal("15.00")),
    ]
    validate_zero_sum(deltas)

    # Balanced multiple draft years
    multi_year_deltas = [
        BudgetDelta(team_id="team_a", draft_year=2027, amount=Decimal("-5.00")),
        BudgetDelta(team_id="team_b", draft_year=2027, amount=Decimal("5.00")),
        BudgetDelta(team_id="team_a", draft_year=2028, amount=Decimal("-10.00")),
        BudgetDelta(team_id="team_b", draft_year=2028, amount=Decimal("10.00")),
    ]
    validate_zero_sum(multi_year_deltas)


def test_validate_zero_sum_fails_when_unbalanced() -> None:
    deltas = [
        BudgetDelta(team_id="team_a", draft_year=2027, amount=Decimal("-15.00")),
        BudgetDelta(team_id="team_b", draft_year=2027, amount=Decimal("10.00")),
    ]
    with pytest.raises(ZeroSumViolationError) as exc_info:
        validate_zero_sum(deltas)

    assert exc_info.value.draft_year == 2027
    assert exc_info.value.total_sum == Decimal("-5.00")
    assert "draft year 2027 must sum to 0.00" in str(exc_info.value)


def test_calculate_team_budget_projections_basic() -> None:
    deltas = [
        BudgetDelta(team_id="alice", draft_year=2027, amount=Decimal("-15.00")),
        BudgetDelta(team_id="bob", draft_year=2027, amount=Decimal("15.00")),
    ]
    known_teams = ["alice", "bob", "charlie"]

    projections = calculate_team_budget_projections(
        starting_budget=Decimal("200.00"),
        known_teams=known_teams,
        deltas=deltas,
        conditions=[],
        target_draft_year=2027,
    )

    proj_map = {p.team_id: p for p in projections}

    # Alice: 200 - 15 = 185
    assert proj_map["alice"].starting_budget == Decimal("200.00")
    assert proj_map["alice"].base_trade_delta == Decimal("-15.00")
    assert proj_map["alice"].fulfilled_conditional_delta == Decimal("0.00")
    assert proj_map["alice"].net_delta == Decimal("-15.00")
    assert proj_map["alice"].projected_budget == Decimal("185.00")
    assert proj_map["alice"].pending_conditional_delta == Decimal("0.00")
    assert not proj_map["alice"].is_negative_budget

    # Bob: 200 + 15 = 215
    assert proj_map["bob"].net_delta == Decimal("15.00")
    assert proj_map["bob"].projected_budget == Decimal("215.00")

    # Charlie: unchanged
    assert proj_map["charlie"].net_delta == Decimal("0.00")
    assert proj_map["charlie"].projected_budget == Decimal("200.00")


def test_calculate_team_budget_projections_multi_year() -> None:
    deltas = [
        BudgetDelta(team_id="alice", draft_year=2027, amount=Decimal("-5.00")),
        BudgetDelta(team_id="bob", draft_year=2027, amount=Decimal("5.00")),
        BudgetDelta(team_id="alice", draft_year=2028, amount=Decimal("-10.00")),
        BudgetDelta(team_id="bob", draft_year=2028, amount=Decimal("10.00")),
    ]
    known_teams = ["alice", "bob"]

    # In 2027
    proj_2027 = calculate_team_budget_projections(
        starting_budget=Decimal("200.00"),
        known_teams=known_teams,
        deltas=deltas,
        conditions=[],
        target_draft_year=2027,
    )
    map_2027 = {p.team_id: p for p in proj_2027}
    assert map_2027["alice"].projected_budget == Decimal("195.00")
    assert map_2027["bob"].projected_budget == Decimal("205.00")

    # In 2028
    proj_2028 = calculate_team_budget_projections(
        starting_budget=Decimal("200.00"),
        known_teams=known_teams,
        deltas=deltas,
        conditions=[],
        target_draft_year=2028,
    )
    map_2028 = {p.team_id: p for p in proj_2028}
    assert map_2028["alice"].projected_budget == Decimal("190.00")
    assert map_2028["bob"].projected_budget == Decimal("210.00")


def test_calculate_team_budget_projections_conditions() -> None:
    deltas = [
        BudgetDelta(team_id="alice", draft_year=2027, amount=Decimal("-5.00")),
        BudgetDelta(team_id="bob", draft_year=2027, amount=Decimal("5.00")),
    ]
    conditions = [
        # Fulfilled for 2027: Bob pays Alice $7
        TradeCondition(
            condition_id="c1",
            paying_team="bob",
            receiving_team="alice",
            draft_year=2027,
            amount=Decimal("7.00"),
            status="fulfilled",
        ),
        # Pending for 2027: Bob pays Alice $3
        TradeCondition(
            condition_id="c2",
            paying_team="bob",
            receiving_team="alice",
            draft_year=2027,
            amount=Decimal("3.00"),
            status="pending",
        ),
        # Void for 2027: Ignored
        TradeCondition(
            condition_id="c3",
            paying_team="alice",
            receiving_team="bob",
            draft_year=2027,
            amount=Decimal("10.00"),
            status="void",
        ),
        # Fulfilled for 2028: Ignored when target year is 2027
        TradeCondition(
            condition_id="c4",
            paying_team="bob",
            receiving_team="alice",
            draft_year=2028,
            amount=Decimal("20.00"),
            status="fulfilled",
        ),
    ]

    projections = calculate_team_budget_projections(
        starting_budget=Decimal("200.00"),
        known_teams=["alice", "bob"],
        deltas=deltas,
        conditions=conditions,
        target_draft_year=2027,
    )
    proj_map = {p.team_id: p for p in projections}

    # Alice: base -5, fulfilled +7 -> net +2 -> budget 202. Pending: +3
    assert proj_map["alice"].base_trade_delta == Decimal("-5.00")
    assert proj_map["alice"].fulfilled_conditional_delta == Decimal("7.00")
    assert proj_map["alice"].net_delta == Decimal("2.00")
    assert proj_map["alice"].projected_budget == Decimal("202.00")
    assert proj_map["alice"].pending_conditional_delta == Decimal("3.00")

    # Bob: base +5, fulfilled -7 -> net -2 -> budget 198. Pending: -3
    assert proj_map["bob"].base_trade_delta == Decimal("5.00")
    assert proj_map["bob"].fulfilled_conditional_delta == Decimal("-7.00")
    assert proj_map["bob"].net_delta == Decimal("-2.00")
    assert proj_map["bob"].projected_budget == Decimal("198.00")
    assert proj_map["bob"].pending_conditional_delta == Decimal("-3.00")


def test_calculate_team_budget_projections_negative_budget_flag() -> None:
    deltas = [
        BudgetDelta(team_id="reckless_team", draft_year=2027, amount=Decimal("-250.00")),
        BudgetDelta(team_id="hoarder_team", draft_year=2027, amount=Decimal("250.00")),
    ]
    projections = calculate_team_budget_projections(
        starting_budget=Decimal("200.00"),
        known_teams=["reckless_team", "hoarder_team"],
        deltas=deltas,
        conditions=[],
        target_draft_year=2027,
    )
    proj_map = {p.team_id: p for p in projections}

    assert proj_map["reckless_team"].projected_budget == Decimal("-50.00")
    assert proj_map["reckless_team"].is_negative_budget is True

    assert proj_map["hoarder_team"].projected_budget == Decimal("450.00")
    assert proj_map["hoarder_team"].is_negative_budget is False


def test_team_budget_projection_string_properties() -> None:
    projection = TeamBudgetProjection(
        team_id="team_alpha",
        starting_budget=Decimal("200.00"),
        base_trade_delta=Decimal("-15.50"),
        fulfilled_conditional_delta=Decimal("5.00"),
        net_delta=Decimal("-10.50"),
        projected_budget=Decimal("189.50"),
        pending_conditional_delta=Decimal("3.00"),
        is_negative_budget=False,
    )
    assert projection.starting_budget_str == "200.00"
    assert projection.base_trade_delta_str == "-15.50"
    assert projection.fulfilled_conditional_delta_str == "5.00"
    assert projection.net_delta_str == "-10.50"
    assert projection.projected_budget_str == "189.50"
    assert projection.pending_conditional_delta_str == "3.00"
