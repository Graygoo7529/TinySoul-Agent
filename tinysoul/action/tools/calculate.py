"""
Calculate tool - safe mathematical evaluation.
"""

import ast
import operator
from typing import Any, Callable

# Supported operators for safe evaluation
_SAFE_OPS: dict[type, Callable[..., Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}


def _eval_node(node: ast.AST) -> Any:
    """Safely evaluate an AST node."""
    if isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPS:
            raise ValueError(f"Unsupported binary operator: {op_type.__name__}")
        return _SAFE_OPS[op_type](_eval_node(node.left), _eval_node(node.right))
    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        return _SAFE_OPS[op_type](_eval_node(node.operand))
    elif isinstance(node, ast.Expression):
        return _eval_node(node.body)
    else:
        raise ValueError(f"Unsupported expression type: {type(node).__name__}")


def calculate(what: str):
    """
    Safely evaluate a mathematical expression.

    Args:
        what: Mathematical expression string (e.g., "4 * 7 / 3")

    Returns:
        Numerical result

    Raises:
        ValueError: If expression contains unsupported operations
    """
    tree = ast.parse(what, mode="eval")
    return _eval_node(tree)
