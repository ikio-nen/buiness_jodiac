"""Goal-state regression tests — the user's selling goal is pinned state.

The bug this pins: JARVIS kept believing "we sell websites" because the goal
was GUESSED from each search's wording ('web design clients in pune' reads as
goal=websites) with nothing user-settable to override it. The contract now:

  1. Pinning a goal beats search-wording inference ('web design clients' is
     WHO we target, not WHAT we sell).
  2. Direct statements ('i sell X' / 'goal is X' / 'clear the goal') parse
     locally as GOAL actions — no API call, and never eaten by brainstorm.
  3. A custom goal phrase ('laptops') is stored verbatim and resolves as the
     custom goal carrying that product; the profile product is untouched.
  4. resolve_goal stamps _source on a COPY — the GOALS registry is shared
     module state and must never be mutated by resolution.

Run: "E:/python.exe" -X utf8 agents/test_goal_state.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.chatbot import parse_intent, ActionType
from agents.action_registry import row_for_gemini, row_for_action
from agents.config import get_active_goal, set_active_goal, get_business_profile
from agents.icp import resolve_goal, goal_of, GOALS
from agents.action_dispatch import handle_goal

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def main() -> int:
    saved_goal = get_active_goal()
    saved_product = get_business_profile().get("product")
    try:
        # ── 1. Local parsing of goal statements ──────────────────────────
        print("Parsing:")
        a = parse_intent("i sell autocad keys")
        check("'i sell autocad keys' is a GOAL action",
              a.type == ActionType.GOAL and "autocad keys" in (a.params.get("goal") or ""),
              f"got {a.type.value}:{a.params}")

        a = parse_intent("we are selling websites now")
        check("'we are selling websites now' -> GOAL(websites...)",
              a.type == ActionType.GOAL and "websites" in (a.params.get("goal") or ""))

        a = parse_intent("clear the goal")
        check("'clear the goal' -> GOAL with empty goal (clear)",
              a.type == ActionType.GOAL and (a.params.get("goal") or "") == "")

        a = parse_intent("goal back to auto")
        check("'goal back to auto' clears too",
              a.type == ActionType.GOAL and (a.params.get("goal") or "") == "")

        a = parse_intent("my goal is what?")
        check("a question about the goal is NOT a set",
              a.type != ActionType.GOAL, f"got {a.type.value}")

        # Contractions: the most natural phrasings must hit the fastpath too
        # (the first regex version required a SPACE before 'm/'re, so
        # "i'm selling X" silently fell through to the API path).
        a = parse_intent("i'm selling autocad keys")
        check("contraction 'i'm selling X' parses locally",
              a.type == ActionType.GOAL and "autocad keys" in (a.params.get("goal") or ""),
              f"got {a.type.value}:{a.params}")
        a = parse_intent("we're selling websites now")
        check("contraction 'we're selling websites now' parses locally",
              a.type == ActionType.GOAL and "websites" in (a.params.get("goal") or ""),
              f"got {a.type.value}:{a.params}")
        a = parse_intent("i'm selling laptops now")
        check("discourse tail 'now' is not part of the goal",
              a.type == ActionType.GOAL and (a.params.get("goal") or "").lower() == "laptops",
              f"got {a.params}")

        # 'goal' + bare whitespace is a SEARCH about goals, not a statement:
        # 'goal keeper gloves supplier' must reach Gemini, never pin a goal.
        a = parse_intent("goal keeper gloves supplier")
        check("'goal keeper gloves supplier' stays a SEARCH",
              a.type != ActionType.GOAL, f"got {a.type.value}")
        a = parse_intent("best goal scorers in football")
        check("'best goal scorers' stays a SEARCH",
              a.type != ActionType.GOAL, f"got {a.type.value}")

        # AI backstop: a Gemini goal-call on a message with NO statement
        # shape is dropped (the model misreads searches containing 'goal').
        from agents.chatbot import _handle_function_call, _has_goal_statement_shape
        from agents.chatbot import Action as _A
        check("shape gate: 'goal keeper gloves supplier' has no statement shape",
              not _has_goal_statement_shape("goal keeper gloves supplier"))
        check("shape gate: embedded statement still passes",
              _has_goal_statement_shape("i'm selling laptops now, find clients in pune"))
        a = _handle_function_call("set_selling_goal", {"goal": "keeper gloves"},
                                  "goal keeper gloves supplier")
        check("AI goal-call on a search is still built (gate lives at emit)",
              a.type == ActionType.GOAL)

        # The full emit-path gate: simulate the collect list the parser keeps.
        collect = [_A(type=ActionType.SEARCH, params={}, response="")]
        goal_call = _A(type=ActionType.GOAL,
                       params={"goal": "keeper gloves", "source": "ai"},
                       response="")
        if (any(x.type == ActionType.GOAL and x.params.get("source") == "ai"
                for x in collect + [goal_call])
                and not _has_goal_statement_shape("goal keeper gloves supplier")):
            collect = [x for x in collect
                       if not (x.type == ActionType.GOAL
                               and x.params.get("source") == "ai")]
        check("emit-path gate drops the misread goal call, keeps the search",
              len(collect) == 1 and collect[0].type == ActionType.SEARCH)

        # A search must never be eaten by the goal fastpath — and brainstorm
        # triggers ("my product") must not shadow a real statement.
        a = parse_intent("find autocad training institutes in kolkata remove schools colleges auditoriums and libraries")
        check("search phrasing stays a SEARCH",
              a.type == ActionType.SEARCH, f"got {a.type.value}")

        # ── 2. Registry wiring (the three-surface spine) ─────────────────
        print("Registry:")
        row = row_for_gemini("set_selling_goal")
        check("Gemini tool set_selling_goal has a registry row", row is not None)
        check("GOAL row reachable by action too",
              row_for_action(ActionType.GOAL) is not None)

        # ── 3. Precedence: pin beats search wording ──────────────────────
        print("Precedence:")
        r = handle_goal({"goal": "websites"})
        check("pin 'websites' stores the canonical key",
              r["data"]["goal"] == "website", f"got {r['data']}")

        g = resolve_goal(request="web design clients in pune")
        check("pinned goal outranks 'web design clients' wording",
              g["key"] == "website" and g.get("_source") == "active goal",
              f"got {g['key']}:{g.get('_source')}")

        handle_goal({"goal": ""})
        check("clear returns to auto", get_active_goal() == "")
        g = resolve_goal(request="web design clients in pune")
        check("after clear, wording infers again (with source)",
              g["key"] == "website" and g.get("_source") == "search wording",
              f"got {g['key']}:{g.get('_source')}")
        g = resolve_goal(request="autocad training centres near me")
        check("autocad wording infers cad_licensing",
              g["key"] == "cad_licensing", f"got {g['key']}")

        # ── 4. Custom goal phrase ────────────────────────────────────────
        print("Custom goals:")
        r = handle_goal({"goal": "laptops"})
        check("custom phrase stored verbatim", r["data"]["goal"] == "laptops")
        check("profile product untouched by pinning",
              get_business_profile().get("product") == saved_product)
        g = resolve_goal(request="find laptop shops in delhi")
        check("custom pin resolves as custom goal with the phrase as product",
              g["key"] == "custom" and g.get("product") == "laptops"
              and g.get("_source") == "active goal",
              f"got {g['key']}:{g.get('product')}:{g.get('_source')}")
        handle_goal({"goal": ""})

        # ── 5. resolve_goal never mutates the shared registry ────────────
        print("Registry isolation:")
        before = dict(GOALS["website"])
        g = resolve_goal(request="anything")
        g["_source"] = "tampered"
        g["label"] = "tampered"
        check("stamping/mutating the resolved copy leaves GOALS intact",
              GOALS["website"]["label"] == before["label"]
              and "_source" not in GOALS["website"])
    finally:
        set_active_goal(saved_goal)

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s): {', '.join(FAILURES)}")
        return 1
    print("All goal-state checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
