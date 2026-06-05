#!/usr/bin/env python3
"""
vokk_logic.py — the executable layer of VokkScript.

VokkScript started as a DECLARATIVE language: it described visuals, music, agents,
routes. That is enough to CONFIGURE VOKK, but not enough to express BEHAVIOR — you
cannot re-author real logic (decisions, computation, control flow) with static
blocks alone.

This module adds the missing half: a small but real interpreter for VokkScript
expressions and statements, so logic can be written in VokkScript and executed by
the Python runtime. It is the foundation for moving VOKK's own behavior out of
hardcoded Python and into VokkScript ("the heavy path").

It is deliberately sandboxed: no imports, no attribute access, no file/network
access, no Python eval. Only the values, operators, and builtins defined here.

Grammar (statements, newline- or brace-delimited):
    let NAME = EXPR        # define a new variable
    set NAME = EXPR        # reassign an existing variable
    if EXPR { ... } else { ... }
    return EXPR
    EXPR                   # bare expression statement (its value becomes "last")

Expressions: numbers, "strings", true/false/null, identifiers, function calls,
( ) grouping, and operators (precedence high→low):
    not / unary -   *  /  %   +  -   < <= > >=   == !=   and(&&)   or(||)

Public API:
    run_logic(source, env=None) -> RunResult(value, env, returned)
    eval_expr(source, env=None) -> the value of a single expression
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


# ── lexer ──────────────────────────────────────────────────────────────────
_KEYWORDS = {"let", "set", "if", "else", "return", "true", "false", "null",
             "and", "or", "not"}

_TOKEN_RE = re.compile(r"""
    \s+
  | \#[^\n]*                         # comments
  | (?P<num>\d+\.\d+|\d+)
  | "(?P<str>(?:\\.|[^"\\])*)"       # double-quoted string with escapes
  | (?P<op><=|>=|==|!=|&&|\|\||[-+*/%<>(){}=,])
  | (?P<name>[A-Za-z_]\w*)
""", re.VERBOSE)


@dataclass
class Tok:
    kind: str   # 'num' | 'str' | 'op' | 'name' | 'kw' | 'eof'
    val: Any


def _lex(src: str) -> List[Tok]:
    toks: List[Tok] = []
    i, n = 0, len(src)
    while i < n:
        m = _TOKEN_RE.match(src, i)
        if not m:
            raise SyntaxError(f"VokkScript: unexpected character {src[i]!r} at {i}")
        i = m.end()
        if m.lastgroup is None:           # whitespace / comment
            continue
        if m.lastgroup == "num":
            v = m.group("num")
            toks.append(Tok("num", float(v) if "." in v else int(v)))
        elif m.lastgroup == "str":
            toks.append(Tok("str", _unescape(m.group("str"))))
        elif m.lastgroup == "op":
            toks.append(Tok("op", m.group("op")))
        elif m.lastgroup == "name":
            w = m.group("name")
            toks.append(Tok("kw", w) if w in _KEYWORDS else Tok("name", w))
    toks.append(Tok("eof", None))
    return toks


def _unescape(s: str) -> str:
    return (s.replace(r"\n", "\n").replace(r"\t", "\t")
             .replace(r'\"', '"').replace(r"\\", "\\"))


# ── AST nodes (kept as plain tuples for compactness) ───────────────────────
# expression nodes: ('num',v) ('str',v) ('bool',v) ('null',) ('var',name)
#   ('unary',op,node) ('bin',op,a,b) ('call',name,[args])
# statement nodes: ('let',name,expr) ('set',name,expr) ('return',expr)
#   ('if',cond,then_block,else_block) ('expr',expr)


class _Parser:
    def __init__(self, toks: List[Tok]):
        self.toks = toks
        self.p = 0

    def _peek(self) -> Tok:
        return self.toks[self.p]

    def _next(self) -> Tok:
        t = self.toks[self.p]
        self.p += 1
        return t

    def _eat_op(self, op: str):
        t = self._peek()
        if t.kind == "op" and t.val == op:
            self.p += 1
            return
        raise SyntaxError(f"VokkScript: expected {op!r}, got {t.kind}:{t.val!r}")

    # program / blocks ------------------------------------------------------
    def parse_program(self) -> List[tuple]:
        stmts = []
        while self._peek().kind != "eof":
            stmts.append(self._statement())
        return stmts

    def _block(self) -> List[tuple]:
        self._eat_op("{")
        stmts = []
        while not (self._peek().kind == "op" and self._peek().val == "}"):
            if self._peek().kind == "eof":
                raise SyntaxError("VokkScript: unterminated block")
            stmts.append(self._statement())
        self._eat_op("}")
        return stmts

    def _statement(self) -> tuple:
        t = self._peek()
        if t.kind == "kw" and t.val in ("let", "set"):
            self._next()
            name = self._next()
            if name.kind != "name":
                raise SyntaxError("VokkScript: expected name after let/set")
            self._eat_op("=")
            return (t.val, name.val, self._expr())
        if t.kind == "kw" and t.val == "return":
            self._next()
            return ("return", self._expr())
        if t.kind == "kw" and t.val == "if":
            self._next()
            cond = self._expr()
            then_b = self._block()
            else_b: List[tuple] = []
            if self._peek().kind == "kw" and self._peek().val == "else":
                self._next()
                else_b = self._block()
            return ("if", cond, then_b, else_b)
        return ("expr", self._expr())

    # expressions (precedence climbing) -------------------------------------
    def _expr(self) -> tuple:
        return self._or()

    def _or(self) -> tuple:
        node = self._and()
        while self._is_op("||") or self._is_kw("or"):
            self._next()
            node = ("bin", "or", node, self._and())
        return node

    def _and(self) -> tuple:
        node = self._equality()
        while self._is_op("&&") or self._is_kw("and"):
            self._next()
            node = ("bin", "and", node, self._equality())
        return node

    def _equality(self) -> tuple:
        node = self._comparison()
        while self._is_op("==") or self._is_op("!="):
            op = self._next().val
            node = ("bin", op, node, self._comparison())
        return node

    def _comparison(self) -> tuple:
        node = self._additive()
        while any(self._is_op(o) for o in ("<", "<=", ">", ">=")):
            op = self._next().val
            node = ("bin", op, node, self._additive())
        return node

    def _additive(self) -> tuple:
        node = self._multiplicative()
        while self._is_op("+") or self._is_op("-"):
            op = self._next().val
            node = ("bin", op, node, self._multiplicative())
        return node

    def _multiplicative(self) -> tuple:
        node = self._unary()
        while any(self._is_op(o) for o in ("*", "/", "%")):
            op = self._next().val
            node = ("bin", op, node, self._unary())
        return node

    def _unary(self) -> tuple:
        if self._is_kw("not") or self._is_op("!"):
            self._next()
            return ("unary", "not", self._unary())
        if self._is_op("-"):
            self._next()
            return ("unary", "-", self._unary())
        return self._primary()

    def _primary(self) -> tuple:
        t = self._next()
        if t.kind == "num":
            return ("num", t.val)
        if t.kind == "str":
            return ("str", t.val)
        if t.kind == "kw" and t.val in ("true", "false"):
            return ("bool", t.val == "true")
        if t.kind == "kw" and t.val == "null":
            return ("null",)
        if t.kind == "op" and t.val == "(":
            node = self._expr()
            self._eat_op(")")
            return node
        if t.kind == "name":
            if self._peek().kind == "op" and self._peek().val == "(":
                self._next()
                args = []
                if not (self._peek().kind == "op" and self._peek().val == ")"):
                    args.append(self._expr())
                    while self._peek().kind == "op" and self._peek().val == ",":
                        self._next()
                        args.append(self._expr())
                self._eat_op(")")
                return ("call", t.val, args)
            return ("var", t.val)
        raise SyntaxError(f"VokkScript: unexpected token {t.kind}:{t.val!r}")

    def _is_op(self, op: str) -> bool:
        t = self._peek()
        return t.kind == "op" and t.val == op

    def _is_kw(self, kw: str) -> bool:
        t = self._peek()
        return t.kind == "kw" and t.val == kw


# ── sandboxed builtins ─────────────────────────────────────────────────────
def _contains(s, sub) -> bool:
    try:
        return sub in s
    except TypeError:
        return False


BUILTINS: Dict[str, Callable[..., Any]] = {
    "len": lambda x: len(x),
    "upper": lambda s: str(s).upper(),
    "lower": lambda s: str(s).lower(),
    "trim": lambda s: str(s).strip(),
    "contains": _contains,
    "startswith": lambda s, p: str(s).startswith(str(p)),
    "endswith": lambda s, p: str(s).endswith(str(p)),
    "min": min,
    "max": max,
    "abs": abs,
    "round": lambda x, n=0: round(x, int(n)),
    "int": lambda x: int(x),
    "float": lambda x: float(x),
    "str": lambda x: _to_str(x),
    "bool": lambda x: bool(x),
}


def _to_str(x: Any) -> str:
    if x is True:
        return "true"
    if x is False:
        return "false"
    if x is None:
        return "null"
    return str(x)


# ── evaluator ──────────────────────────────────────────────────────────────
class _Return(Exception):
    def __init__(self, value): self.value = value


@dataclass
class RunResult:
    value: Any                              # value of the last expression statement
    env: Dict[str, Any] = field(default_factory=dict)
    returned: bool = False                  # whether a `return` fired


def _truthy(v: Any) -> bool:
    return bool(v)


def _eval(node: tuple, env: Dict[str, Any]) -> Any:
    k = node[0]
    if k == "num" or k == "str" or k == "bool":
        return node[1]
    if k == "null":
        return None
    if k == "var":
        if node[1] not in env:
            raise NameError(f"VokkScript: undefined variable {node[1]!r}")
        return env[node[1]]
    if k == "unary":
        v = _eval(node[2], env)
        return (not _truthy(v)) if node[1] == "not" else -v
    if k == "call":
        fn = BUILTINS.get(node[1])
        if not fn:
            raise NameError(f"VokkScript: unknown function {node[1]!r}")
        return fn(*[_eval(a, env) for a in node[2]])
    if k == "bin":
        op = node[1]
        if op == "and":
            a = _eval(node[2], env)
            return a if not _truthy(a) else _eval(node[3], env)
        if op == "or":
            a = _eval(node[2], env)
            return a if _truthy(a) else _eval(node[3], env)
        a, b = _eval(node[2], env), _eval(node[3], env)
        if op == "+":
            if isinstance(a, str) or isinstance(b, str):
                return _to_str(a) + _to_str(b)
            return a + b
        if op == "-": return a - b
        if op == "*": return a * b
        if op == "/": return a / b
        if op == "%": return a % b
        if op == "==": return a == b
        if op == "!=": return a != b
        if op == "<": return a < b
        if op == "<=": return a <= b
        if op == ">": return a > b
        if op == ">=": return a >= b
    raise SyntaxError(f"VokkScript: cannot evaluate {node!r}")


def _exec_block(stmts: List[tuple], env: Dict[str, Any]) -> Any:
    last: Any = None
    for st in stmts:
        kind = st[0]
        if kind == "let":
            env[st[1]] = _eval(st[2], env)
        elif kind == "set":
            if st[1] not in env:
                raise NameError(f"VokkScript: cannot set undefined variable {st[1]!r} (use let)")
            env[st[1]] = _eval(st[2], env)
        elif kind == "return":
            raise _Return(_eval(st[1], env))
        elif kind == "if":
            branch = st[2] if _truthy(_eval(st[1], env)) else st[3]
            last = _exec_block(branch, env)
        elif kind == "expr":
            last = _eval(st[1], env)
    return last


# ── public API ─────────────────────────────────────────────────────────────
def run_logic(source: str, env: Optional[Dict[str, Any]] = None) -> RunResult:
    """Execute a VokkScript logic program. `env` seeds/receives variables."""
    env = dict(env or {})
    stmts = _Parser(_lex(source)).parse_program()
    try:
        value = _exec_block(stmts, env)
        return RunResult(value=value, env=env, returned=False)
    except _Return as r:
        return RunResult(value=r.value, env=env, returned=True)


def eval_expr(source: str, env: Optional[Dict[str, Any]] = None) -> Any:
    """Evaluate a single VokkScript expression and return its value."""
    return _eval(_Parser(_lex(source))._expr(), dict(env or {}))


if __name__ == "__main__":
    demo = '''
    let name = "vokk"
    let score = 3 + 4 * 2
    if score > 10 and contains(name, "vok") {
        return upper(name) + " wins with " + str(score)
    } else {
        return "no"
    }
    '''
    res = run_logic(demo)
    print("returned:", res.returned, "value:", res.value)
    print("env:", res.env)
