<!-- version: 1 -->
This capability's prompt lives in agents/ai_design.py (AIEmailDesigner._draft_email):
it already carries the goal, product line, ICP context, industry research, learning
context and web reputation sections, and it is versioned with the code.

The service's draft_email() delegates there so there is exactly ONE draft prompt.
When that prompt is next revised, promote its text here and inline it in the
service — do not fork a second drafting prompt.

Return shape (produced by the delegated prompt):
{"subject", "body", "greeting", "hook", "ai_powered"}
