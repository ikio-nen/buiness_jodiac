#!/usr/bin/env python3
"""The outreach email gate: short, plain, human, with an opt-out.

Covers three things the guides/03 redesign asks for:
  1. the linter rejects long, salesy, opt-out-less drafts and accepts a good one;
  2. ten composed drafts across different institution types all pass, inside the
     60-110 word target, with no grey-market vocabulary;
  3. the AI path regenerates once on a failing draft and then raises, so the
     caller falls back to the template instead of showing a bad email.

Run: "E:/python.exe" -X utf8 tests/test_email_lint.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import email_copy, email_lint  # noqa: E402

GOOD_SUBJECT = "AutoCAD seats for your labs"
GOOD_BODY = (
    "Hi Priya,\n\n"
    "I noticed your institute runs AutoCAD and drafting courses, and licence "
    "renewals for lab machines can be costly and fiddly to manage across "
    "batches of students.\n\n"
    "We supply official Autodesk licences with invoicing and set-up help, so "
    "each new batch can start on time without delays or paperwork.\n\n"
    "Would it be useful if I sent a short price sheet?\n\n"
    "Regards,\nAsha | Zyphr | asha@example.com\n"
    'If this is not relevant, reply "no thanks" and I will not contact you again.'
)

# (name, category) → the deterministic draft both paths produce.
SAMPLES = [
    ("Hooghly Institute of Technology", "college"),
    ("Bandel Youth Computer Training Centre", "training"),
    ("M3 Engineering Academy", "polytechnic"),
    ("St. Xavier's High School", "school"),
    ("Calcutta University", "university"),
    ("CAD & Design Academy", "training"),
    ("National Youth Computer Academy", "training"),
    ("Technoworld Polytechnic", "polytechnic"),
    ("Sunrise Public School", "school"),
    ("Animation & Multimedia Classes", "training"),
]


def _composed(name, category):
    greeting = email_copy.greeting_for("", name)
    issue = email_copy.issue_line(name, category)
    body = email_copy.compose_body(issue, greeting=greeting,
                                  sender="Autodesk Educational Solutions",
                                  whatsapp=email_copy.WHATSAPP)
    return issue, body


def check_linter_rejects_the_bad_draft():
    problems = email_lint.lint(
        "URGENT: FREE Game-Changing AutoCAD Offer!!!",
        "Dear sir, I hope this email finds you well. " + "Buy now. " * 5)
    joined = " | ".join(problems).lower()
    assert problems, "a spammy, opt-out-less draft passed the gate"
    for expected in ("spam word", "opt-out", "stock phrase", "too short"):
        assert expected in joined, (expected, problems)


def check_linter_rejects_an_all_caps_subject():
    problems = email_lint.lint("AUTOCAD SEATS FOR YOUR LABS", GOOD_BODY)
    assert any("caps" in p.lower() for p in problems), problems


def check_linter_accepts_a_good_draft():
    assert email_lint.lint(GOOD_SUBJECT, GOOD_BODY) == []


def check_linter_counts_the_message_not_the_signature():
    # Only the signature and opt-out are dropped, so a long issue paragraph
    # still fails: the gate is not bypassed by appending a big signature.
    long_issue = "word " * 130
    problems = email_lint.lint(GOOD_SUBJECT, f"Hi there,\n\n{long_issue}\n\n"
                                            "Regards,\nA | B\n" + email_copy.OPT_OUT)
    assert any("too long" in p for p in problems), problems


def check_ten_samples_pass_and_are_short():
    word_counts = []
    for name, category in SAMPLES:
        issue, body = _composed(name, category)
        problems = email_lint.lint(_composed_subject(), body)
        assert not problems, f"{name}: {problems}"
        words = email_lint._body_words(body)
        word_counts.append(words)
        assert 55 <= words <= 115, f"{name}: {words} words"
        assert "keys" not in body.lower(), f"{name}: grey-market vocabulary"
        assert body.rstrip().endswith(email_copy.OPT_OUT), f"{name}: no opt-out"
        assert body.count("?") == 1, f"{name}: more than one question"
        assert issue.split(".")[0] in body, f"{name}: issue paragraph missing"
    print(f"       words per sample: {word_counts}")
    return word_counts


def _composed_subject():
    from agents.medium import SUBJECTS_BY_GOAL
    return SUBJECTS_BY_GOAL["cad_licensing"][0]


def check_template_subjects_are_short():
    from agents.medium import SUBJECTS_BY_GOAL
    for goal, subjects in SUBJECTS_BY_GOAL.items():
        for subject in subjects:
            assert len(subject) <= 45, (goal, subject, len(subject))
            assert 3 <= len(subject.split()) <= 7, (goal, subject)
            assert ":" not in subject, (goal, subject)


def _stub_ai(replies):
    """Patch the AI engine to return canned JSON, and count the calls."""
    import agents.ai_engine as ai_engine
    calls = []

    def fake_generate_json(prompt, system="", temperature=0.3):
        calls.append(prompt)
        return replies[min(len(calls) - 1, len(replies) - 1)]

    original = (ai_engine.generate_json, ai_engine.is_available)
    ai_engine.generate_json = fake_generate_json
    ai_engine.is_available = lambda: True
    # Keep the draft offline: no web search, no industry research.
    import agents.agent_team as agent_team
    import agents.industry_learner as industry_learner
    saved = (agent_team.web_search, industry_learner.build_industry_context)
    agent_team.web_search = lambda *a, **k: ""
    industry_learner.build_industry_context = lambda *a, **k: ""
    return calls, (original, saved)


def _restore(state):
    import agents.ai_engine as ai_engine
    import agents.agent_team as agent_team
    import agents.industry_learner as industry_learner
    (gen, avail), (web, industry) = state
    ai_engine.generate_json, ai_engine.is_available = gen, avail
    agent_team.web_search, industry_learner.build_industry_context = web, industry


def check_ai_draft_is_gated_and_retried_once():
    from agents.ai_design import AIDesignAgent

    bad = {"subject": "URGENT FREE OFFER: buy now", "issue": "Buy now. " * 20}
    good = {"subject": "AutoCAD seats for your labs",
            "issue": ("I looked at your drafting batches, where every intake needs "
                      "a licensed seat before the first class.")}
    calls, state = _stub_ai([bad, good])
    try:
        out = AIDesignAgent()._draft_email(
            {"business_name": "Bodge Institute", "category": "training"}, {})
    finally:
        _restore(state)
    assert len(calls) == 2, f"expected one regeneration, saw {len(calls)}"
    assert "failed these checks" in calls[1], calls[1][-400:]
    assert email_lint.lint(out["subject"], out["body"]) == [], out["body"]


def check_ai_draft_raises_when_it_keeps_failing():
    from agents.ai_design import AIDesignAgent

    bad = {"subject": "URGENT FREE OFFER: buy now", "issue": "Buy now. " * 20}
    calls, state = _stub_ai([bad, bad, bad])
    try:
        AIDesignAgent()._draft_email(
            {"business_name": "Bodge Institute", "category": "training"}, {})
    except ValueError as exc:
        assert "email gate" in str(exc), exc
        assert len(calls) == 2, f"expected one retry, saw {len(calls)}"
    else:
        raise AssertionError("a draft that fails twice was returned anyway")
    finally:
        _restore(state)


def check_map_template_draft_is_sendable():
    """The map route's own drafter must use the deck, not a drifted subject."""
    from agents.web.api import _map_template_draft

    subject, body = _map_template_draft(
        {"name": "Hooghly Institute of Technology", "category": "college"},
        "Autodesk Educational Solutions")
    assert email_lint.lint(subject, body) == [], (subject, body)


def check_template_fallback_is_sendable():
    """The template path is what a failing AI draft lands on; it must pass."""
    from agents.ai.schemas import BusinessProfile, ContactCandidate
    from agents.ai import fallbacks

    draft = fallbacks.draft_email(BusinessProfile(industry="training"),
                                 ContactCandidate(name=""),
                                 product="licensed Autodesk seats",
                                 tone="professional")
    assert email_lint.lint(draft.subject, draft.body) == [], draft.body


CHECKS = [
    ("linter_rejects_the_bad_draft", check_linter_rejects_the_bad_draft),
    ("linter_rejects_an_all_caps_subject", check_linter_rejects_an_all_caps_subject),
    ("linter_accepts_a_good_draft", check_linter_accepts_a_good_draft),
    ("linter_counts_the_message_not_the_signature",
     check_linter_counts_the_message_not_the_signature),
    ("ten_samples_pass_and_are_short", check_ten_samples_pass_and_are_short),
    ("template_subjects_are_short", check_template_subjects_are_short),
    ("ai_draft_is_gated_and_retried_once", check_ai_draft_is_gated_and_retried_once),
    ("ai_draft_raises_when_it_keeps_failing",
     check_ai_draft_raises_when_it_keeps_failing),
    ("template_fallback_is_sendable", check_template_fallback_is_sendable),
    ("map_template_draft_is_sendable", check_map_template_draft_is_sendable),
]


def main() -> int:
    passed = 0
    for name, fn in CHECKS:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - a suite reports, it does not crash
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
        else:
            passed += 1
            print(f"[ok]   {name}")
    print(f"\nTotal: {len(CHECKS)} checks, {passed} passed, "
          f"{len(CHECKS) - passed} failed")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
