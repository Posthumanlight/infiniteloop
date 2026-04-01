"""Safe AST-based expression evaluator for the effect/formula DSL.

Allows: numeric literals, variable access (dot notation), arithmetic (+,-,*,/,**),
negation, comparisons (<,>,<=,>=,==,!=), and conditional expressions (a if cond else b).

No function calls, no imports, no attribute assignment — safe by construction.
"""

import ast
import operator
from dataclasses import dataclass
from typing import Any


_BIN_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}

_CMP_OPS: dict[type, Any] = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
}


@dataclass(frozen=True)
class ExprContext:
    """Flattened view of an entity's stats for DSL evaluation.

    Built from MajorStats + current entity state so that expressions
    like ``target.hp`` or ``attacker.mastery`` resolve correctly.
    """

    attack: int
    hp: int
    current_hp: int
    speed: int
    crit_chance: float
    crit_dmg: float
    resistance: int
    energy: int
    mastery: int


class ExprError(Exception):
    """Raised when an expression is invalid or uses disallowed syntax."""


def evaluate_expr(expr: str, context: dict[str, Any]) -> float:
    """Safely evaluate a math expression with context variables.

    Args:
        expr: The expression string, e.g. ``"target.hp * 0.05"``.
        context: Mapping of variable names to values. Values can be
                 numbers, ``ExprContext`` instances, or any object
                 whose attributes are numeric.

    Returns:
        The evaluated result as a float.

    Raises:
        ExprError: If the expression uses disallowed syntax or
                   references unknown variables.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"Invalid expression syntax: {expr}") from exc
    return float(_eval_node(tree.body, context))


def _eval_node(node: ast.expr, ctx: dict[str, Any]) -> float:
    match node:
        case ast.Constant(value=v) if isinstance(v, (int, float)):
            return float(v)

        case ast.Name(id=name):
            if name not in ctx:
                raise ExprError(f"Unknown variable: {name}")
            val = ctx[name]
            if isinstance(val, (int, float)):
                return float(val)
            raise ExprError(
                f"Variable '{name}' is not numeric (got {type(val).__name__}). "
                "Use dot notation to access attributes, e.g. target.hp"
            )

        case ast.Attribute(value=obj_node, attr=attr):
            obj = _resolve_object(obj_node, ctx)
            if not hasattr(obj, attr):
                raise ExprError(
                    f"Object has no attribute '{attr}'"
                )
            val = getattr(obj, attr)
            if not isinstance(val, (int, float)):
                raise ExprError(
                    f"Attribute '{attr}' is not numeric (got {type(val).__name__})"
                )
            return float(val)

        case ast.BinOp(left=left, op=op, right=right):
            op_func = _BIN_OPS.get(type(op))
            if op_func is None:
                raise ExprError(f"Unsupported operator: {type(op).__name__}")
            return op_func(_eval_node(left, ctx), _eval_node(right, ctx))

        case ast.UnaryOp(op=ast.USub(), operand=operand):
            return -_eval_node(operand, ctx)

        case ast.UnaryOp(op=ast.UAdd(), operand=operand):
            return _eval_node(operand, ctx)

        case ast.Compare(left=left, ops=ops, comparators=comparators):
            # Support chained comparisons: a < b < c
            result = True
            current = _eval_node(left, ctx)
            for op, comparator in zip(ops, comparators):
                op_func = _CMP_OPS.get(type(op))
                if op_func is None:
                    raise ExprError(f"Unsupported comparison: {type(op).__name__}")
                right_val = _eval_node(comparator, ctx)
                if not op_func(current, right_val):
                    result = False
                    break
                current = right_val
            return 1.0 if result else 0.0

        case ast.IfExp(test=test, body=body, orelse=orelse):
            return (
                _eval_node(body, ctx)
                if _eval_node(test, ctx)
                else _eval_node(orelse, ctx)
            )

        case _:
            raise ExprError(
                f"Unsupported expression node: {type(node).__name__}. "
                "Only literals, variables, arithmetic, comparisons, and "
                "conditionals are allowed."
            )


def _resolve_object(node: ast.expr, ctx: dict[str, Any]) -> Any:
    """Resolve an object node (the part before the dot in ``obj.attr``)."""
    match node:
        case ast.Name(id=name):
            if name not in ctx:
                raise ExprError(f"Unknown variable: {name}")
            return ctx[name]
        case ast.Attribute(value=inner, attr=attr):
            obj = _resolve_object(inner, ctx)
            if not hasattr(obj, attr):
                raise ExprError(f"Object has no attribute '{attr}'")
            return getattr(obj, attr)
        case _:
            raise ExprError(
                f"Cannot resolve object from node type: {type(node).__name__}"
            )
