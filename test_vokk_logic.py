#!/usr/bin/env python3
"""Tests for vokk_logic — the executable layer of VokkScript."""
from vokk_logic import run_logic, eval_expr


def check(label, got, want):
    ok = got == want
    print(("PASS" if ok else "FAIL"), label, "->", repr(got), "" if ok else f"(want {want!r})")
    return ok


def main():
    results = []

    # expressions: arithmetic + precedence
    results.append(check("arith precedence", eval_expr("3 + 4 * 2"), 11))
    results.append(check("grouping", eval_expr("(3 + 4) * 2"), 14))
    results.append(check("modulo", eval_expr("17 % 5"), 2))
    results.append(check("unary minus", eval_expr("-5 + 2"), -3))

    # strings
    results.append(check("string concat", eval_expr('"a" + "b"'), "ab"))
    results.append(check("string + num coerces", eval_expr('"n=" + 5'), "n=5"))
    results.append(check("upper builtin", eval_expr('upper("vokk")'), "VOKK"))
    results.append(check("contains builtin", eval_expr('contains("vokkscript", "script")'), True))

    # booleans + comparison + short-circuit
    results.append(check("comparison", eval_expr("5 > 3"), True))
    results.append(check("and", eval_expr("true and false"), False))
    results.append(check("or short-circuit", eval_expr('true or undefined_is_never_evaluated == 1'), True))
    results.append(check("not", eval_expr("not false"), True))

    # variables + reassignment
    r = run_logic("let x = 10\nset x = x + 5\nreturn x")
    results.append(check("let/set/return", (r.value, r.returned), (15, True)))

    # if / else control flow
    prog = '''
    let score = 7
    if score > 10 {
        return "high"
    } else {
        return "low"
    }
    '''
    results.append(check("if/else false branch", run_logic(prog).value, "low"))

    # realistic use: a classifier-style decision written in VokkScript
    router = '''
    let msg = lower(input)
    let pick = "chat"
    if contains(msg, "draw") or contains(msg, "portrait") {
        set pick = "image"
    }
    if contains(msg, "build") or contains(msg, "scaffold") {
        set pick = "agency"
    }
    return pick
    '''
    results.append(check("router: image", run_logic(router, {"input": "Draw a fox"}).value, "image"))
    results.append(check("router: agency", run_logic(router, {"input": "scaffold a todo app"}).value, "agency"))
    results.append(check("router: chat", run_logic(router, {"input": "hi there"}).value, "chat"))

    # sandbox: no Python escape hatches
    sandbox_ok = True
    for bad in ["__import__", "open", "eval", "exec", "1 .  __class__"]:
        try:
            eval_expr(bad)
            sandbox_ok = False
            print("FAIL sandbox allowed:", bad)
        except Exception:
            pass
    results.append(check("sandbox blocks python builtins/attrs", sandbox_ok, True))

    passed = sum(results)
    print(f"\n{passed}/{len(results)} passed")
    raise SystemExit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
