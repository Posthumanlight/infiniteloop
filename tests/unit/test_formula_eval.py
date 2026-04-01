"""Tests for the safe AST-based expression evaluator."""

import pytest

from game.core.formula_eval import ExprContext, ExprError, evaluate_expr


def test_literal():
    assert evaluate_expr("42", {}) == 42.0


def test_arithmetic():
    assert evaluate_expr("2 + 3", {}) == 5.0
    assert evaluate_expr("10 - 4", {}) == 6.0
    assert evaluate_expr("3 * 4", {}) == 12.0
    assert evaluate_expr("10 / 4", {}) == 2.5
    assert evaluate_expr("2 ** 3", {}) == 8.0
    assert evaluate_expr("7 % 3", {}) == 1.0
    assert evaluate_expr("7 // 2", {}) == 3.0


def test_variable():
    assert evaluate_expr("x", {"x": 5}) == 5.0


def test_dot_access():
    ctx = ExprContext(
        attack=15, hp=120, current_hp=100, speed=10,
        crit_chance=0.05, crit_dmg=1.5, resistance=8,
        energy=100, mastery=5,
    )
    assert evaluate_expr("target.hp", {"target": ctx}) == 120.0
    assert evaluate_expr("target.attack", {"target": ctx}) == 15.0


def test_expression_with_context():
    ctx = ExprContext(
        attack=15, hp=120, current_hp=100, speed=10,
        crit_chance=0.05, crit_dmg=1.5, resistance=8,
        energy=100, mastery=5,
    )
    result = evaluate_expr("target.hp * 0.05", {"target": ctx})
    assert result == 6.0


def test_negation():
    assert evaluate_expr("-5", {}) == -5.0
    assert evaluate_expr("+5", {}) == 5.0


def test_comparison():
    assert evaluate_expr("3 < 5", {}) == 1.0
    assert evaluate_expr("5 < 3", {}) == 0.0
    assert evaluate_expr("3 == 3", {}) == 1.0
    assert evaluate_expr("3 != 4", {}) == 1.0


def test_conditional():
    assert evaluate_expr("10 if 1 else 20", {}) == 10.0
    assert evaluate_expr("10 if 0 else 20", {}) == 20.0


def test_unknown_variable_raises():
    with pytest.raises(ExprError, match="Unknown variable"):
        evaluate_expr("missing", {})


def test_non_numeric_variable_raises():
    with pytest.raises(ExprError, match="not numeric"):
        evaluate_expr("x", {"x": "string"})


def test_unknown_attribute_raises():
    ctx = ExprContext(
        attack=15, hp=120, current_hp=100, speed=10,
        crit_chance=0.05, crit_dmg=1.5, resistance=8,
        energy=100, mastery=5,
    )
    with pytest.raises(ExprError, match="no attribute"):
        evaluate_expr("target.nonexistent", {"target": ctx})


def test_disallowed_syntax_raises():
    with pytest.raises(ExprError):
        evaluate_expr("__import__('os')", {})


def test_poison_formula():
    """Verify the actual poison effect expression from effects.toml."""
    ctx = ExprContext(
        attack=8, hp=40, current_hp=35, speed=14,
        crit_chance=0.08, crit_dmg=1.3, resistance=3,
        energy=50, mastery=2,
    )
    result = evaluate_expr("target.hp * 0.05", {"target": ctx})
    assert result == 2.0


def test_fortify_formula():
    """Verify the fortify effect expression."""
    result = evaluate_expr("0.75", {})
    assert result == 0.75
