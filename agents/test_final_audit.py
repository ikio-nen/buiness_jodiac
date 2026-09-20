import sys, os, json, shutil
from unittest import mock
sys.path.insert(0, '.')

results = {}

# 1. Imports
try:
    from agents import Orchestrator, Task, Complexity
    results['imports'] = 'OK'
except Exception as e:
    results['imports'] = f'FAIL: {e}'

# 2. Session create/load/save
# The session this check creates is DELETED before the run ends: it is the
# newest session on disk while it exists, and the web layer resumes the newest
# one, so leaving it behind silently switched the office to an empty session
# and made a finished search look like it had found nothing.
sid_session = None
try:
    from agents.session import Session, list_sessions
    s = Session()
    sid_session = s.create('audit_test_v2')
    s.save_data({'biz': [{'name': 'TestCo'}]}, 'businesses.json')
    data = s.load_data('businesses.json')
    assert data['biz'][0]['name'] == 'TestCo'
    sessions = list_sessions()
    assert any(x['id'] == sid_session for x in sessions)
    results['session'] = 'OK'
except Exception as e:
    results['session'] = f'FAIL: {e}'
finally:
    if sid_session:
        shutil.rmtree(os.path.join('F:/jodiac/agent_output/sessions', sid_session),
                      ignore_errors=True)

# 3. Map search + filter
try:
    from agents.map_search import search_businesses, filter_no_website, geocode
    geo = geocode('Manchester')
    assert geo is not None
    all_biz = search_businesses(geo['lat'], geo['lon'], 3000)
    no_site = filter_no_website(all_biz)
    for b in no_site:
        assert not b.get('website'), f"{b['name']} has website"
    results['map_search'] = f'OK ({len(no_site)}/{len(all_biz)} no-site)'
except Exception as e:
    results['map_search'] = f'FAIL: {e}'

# 4. Email draft (via medium agent directly)
try:
    from agents.base import Task, Complexity
    from agents.medium import MediumAgent
    md = MediumAgent()
    task = Task(id='d1', name='draft_email', complexity=Complexity.MEDIUM,
                payload={'business_name': 'Joe Pizza', 'category': 'food_and_drink', 'contact_name': 'Joe'},
                context={'sender_name': 'The Team'})
    r = md.handle(task)
    assert r.success, f'draft_email failed: {r.error}'
    assert '<script>' not in r.output['body']
    assert 'Joe Pizza' in r.output['body']
    results['email_draft'] = 'OK'
except Exception as e:
    results['email_draft'] = f'FAIL: {e}'

# 5. PDF generation
try:
    from agents.pdf_gen import generate_proposal_pdf
    p = generate_proposal_pdf({'name': 'Test Biz', 'address': '123 Main', 'category': 'restaurant'})
    assert os.path.exists(p)
    results['pdf_gen'] = 'OK'
except Exception as e:
    results['pdf_gen'] = f'FAIL: {e}'

# 6. Mailer empty-to guard
try:
    from agents.mailer import send_email
    r = send_email(to='', subject='test', body='test', sender_name='Test')
    assert not r['success']
    results['mailer_guard'] = 'OK'
except Exception as e:
    results['mailer_guard'] = f'FAIL: {e}'

# 7. Obsidian wikilinks
try:
    from agents.obsidian_sync import create_project_note, create_contact_note, create_outreach_form, update_vault_index
    p1 = create_project_note('t2', 'TP', [{'name': 'BA', 'category': 'food', 'phone': '', 'address': ''}, {'name': 'BB', 'category': 'retail', 'phone': '', 'address': ''}])
    c1 = open(p1, encoding='utf-8').read()
    assert '[[ba.md|BA]]' in c1, 'project note should link contact as [[ba.md|BA]]'
    assert '[[bb.md|BB]]' in c1
    assert '[[outreach_t2' in c1
    p2 = create_contact_note({'name': 'BA', 'category': 'food', 'phone': '', 'address': ''}, session_id='t2', project_name='TP')
    c2 = open(p2, encoding='utf-8').read()
    assert '[[t2_tp' in c2
    p3 = create_outreach_form('t2', [{'name': 'BA'}], 'TP')
    c3 = open(p3, encoding='utf-8').read()
    assert '[[ba.md|BA]]' in c3, 'outreach form should link contact as [[ba.md|BA]]'
    idx = update_vault_index()
    ci = open(idx, encoding='utf-8').read()
    assert '[[t2_tp' in ci
    results['obsidian_sync'] = 'OK (links verified)'
except Exception as e:
    results['obsidian_sync'] = f'FAIL: {e}'

# 8. UI imports
try:
    from agents.ui import boot_sequence, status_badge, step_header, typing_print, prompt_choice, prompt_yes_no, show_sessions, show_search_results, show_send_summary, show_draft_summary, gmail_troubleshoot, C, show_main_menu, farewell, show_select_list, show_drafts, banner, show_stats
    results['ui'] = 'OK'
except Exception as e:
    results['ui'] = f'FAIL: {e}'

# 9. Workflows
try:
    from agents.workflows import search_businesses_workflow, enrich_workflow, select_businesses_workflow, draft_and_pdf_workflow, send_emails_workflow, obsidian_sync_workflow, setup_hunter_key, parse_send_numbers
    results['workflows'] = 'OK'
except Exception as e:
    results['workflows'] = f'FAIL: {e}'

# 10. Heavy agent
try:
    from agents.heavy import HeavyAgent
    h = HeavyAgent()
    task = Task(id='h1', name='generate_website', complexity=Complexity.HEAVY,
                payload={'business': {'name': 'Test', 'address': '123', 'category': 'food'}, 'session_id': 'test'})
    r = h.handle(task)
    assert r.success, f'Heavy agent failed: {r.error}'
    results['heavy_agent'] = 'OK'
except Exception as e:
    results['heavy_agent'] = f'FAIL: {e}'

# 11. Jarvis entry
try:
    from agents.jarvis import main
    results['jarvis_entry'] = 'OK'
except Exception as e:
    results['jarvis_entry'] = f'FAIL: {e}'

# 12b. Retry survives API blips (2 failures then success)
try:
    from agents import ai_engine
    calls = {'n': 0}
    class _FakeModels:
        def generate_content(self, **kw):
            calls['n'] += 1
            if calls['n'] <= 2:
                raise Exception('503 overloaded')
            return type('R', (), {'text': 'ok'})()
    fake = type('C', (), {'models': _FakeModels()})()
    with mock.patch.object(ai_engine, '_get_client', return_value=fake), \
         mock.patch.object(ai_engine.time, 'sleep'):
        assert ai_engine.generate('p') == 'ok'
        assert calls['n'] == 3, f'expected 3 attempts, got {calls["n"]}'
    results['ai_retry'] = 'OK (2 blips then success)'
except Exception as e:
    results['ai_retry'] = f'FAIL: {e}'

# 12c. AI failure -> raise -> orchestrator template fallback (no empty draft)
try:
    from agents.ai_design import AIDesignAgent
    ai_agent = AIDesignAgent()
    bad = Task(id='ai1', name='ai_draft_email', complexity=Complexity.HEAVY,
               payload={'business_name': 'Fallback Co', 'category': 'retail',
                        'email': 'x@y.com', 'learning_context': ''},
               context={'sender_name': 'The Team'})
    with mock.patch('agents.ai_engine.generate_json', return_value={}):
        r = ai_agent.handle(bad)
        # _draft_email must RAISE (so handle() reports failure), not return
        # an {"error": ...} dict that would pass as a fake success.
        assert not r.success, 'ai_draft_email should fail when AI output is empty'
    # Orchestrator-level fallback: with AI 'unavailable', run() must land on
    # the template drafter, not return an empty draft.
    o3 = Orchestrator()
    with mock.patch('agents.ai_engine.is_available', return_value=False):
        r2 = o3.run('ai_draft_email', {
            'business_name': 'Fallback Co', 'category': 'retail',
            'email': 'x@y.com', 'learning_context': ''},
            context={'sender_name': 'The Team'})
    assert r2.success, f'ai->template fallback failed: {r2.error}'
    assert r2.output.get('body'), 'fallback draft has no body'
    assert 'Fallback Co' in r2.output['body']
    results['ai_fallback_chain'] = 'OK (raise->template verified)'
except Exception as e:
    results['ai_fallback_chain'] = f'FAIL: {e}'

# 12d. complete_outreach: real caller shape (research passed in, drafts saved)
sid = None
try:
    from agents.config import load_session_data
    from agents.workflows import complete_outreach
    import agents.workflows as wf
    s = Session()
    sid = s.create('audit_co_test')
    research = [{'name': 'PersistCo', 'rating': 4.2, 'review_count': 11,
                 'strengths': ['great service'], 'gaps': ['no website'],
                 'email_hook': 'Nice reviews!', 'improvement_suggestion': 'site'}]
    with mock.patch.object(
            wf, 'draft_and_pdf_workflow',
            return_value={'drafts': [{'to': 'a@b.c', 'subject': 'Hi', 'body': 'Test',
                                      'business': {'name': 'PersistCo', 'category': 'retail'}}],
                          'errors': [], 'ai_used': 0}) as m:
        complete_outreach([{'name': 'PersistCo'}], sid, 'proj', 'Tester',
                          research_data=research)
        # The caller's research must reach drafting (quick-outreach contract)
        assert m.call_args.args[2] == research, 'research_data not passed through'
    persisted = load_session_data(sid, 'email_drafts.json')
    assert persisted.get('drafts'), 'drafts were not saved to the session'
    assert persisted['drafts'][0]['subject'] == 'Hi'
    results['complete_outreach_persistence'] = 'OK (research in, drafts saved)'
except Exception as e:
    results['complete_outreach_persistence'] = f'FAIL: {e}'
finally:
    if sid:
        shutil.rmtree(os.path.join('F:/jodiac/agent_output/sessions', sid),
                      ignore_errors=True)

# 12e. Category filter: tag kill-list beats misleading names (no AI needed)
try:
    from agents.category_filter import filter_by_category
    biz = [
        {'name': 'Calcutta Medical College & Hospital', 'category': 'hospital'},
        {'name': 'Kolkata University Post Office', 'category': 'post_office'},
        {'name': 'Cyber Internet Cafe', 'category': 'computer'},
        {'name': 'Dell Exclusive Store', 'category': 'computer'},
        {'name': 'Loreto Convent', 'category': 'school'},
        {'name': 'NIST Training Institute', 'category': 'training'},
    ]
    with mock.patch('agents.ai_engine.is_available', return_value=False):
        kept, rep = filter_by_category(biz, 'educational centers that teach AutoCAD')
    names = [b['name'] for b in kept]
    assert 'Calcutta Medical College & Hospital' not in names, 'hospital passed via name substring'
    assert 'Kolkata University Post Office' not in names, 'post office passed'
    assert 'Loreto Convent' in names and 'NIST Training Institute' in names
    assert 'AI unavailable' in rep, f'report should state strict mode: {rep}'
    results['filter_killlist'] = f'OK ({len(kept)}/{len(biz)} kept, strict mode)'
except Exception as e:
    results['filter_killlist'] = f'FAIL: {e}'

# 12f. Category filter: AI tiered judgment + fail-closed on AI failure
try:
    from agents.category_filter import filter_by_category
    biz = [{'name': f'B{i}', 'category': 'school'} for i in range(1, 8)]
    verdicts = {'fits': [1, 2, 3], 'plausible': [4], 'unlikely': [5, 6, 7]}
    with mock.patch('agents.ai_engine.is_available', return_value=True), \
         mock.patch('agents.ai_engine.generate_json', return_value=verdicts) as gj:
        kept, rep = filter_by_category(biz, 'engineering colleges')
    assert [b['name'] for b in kept] == ['B1', 'B2', 'B3', 'B4'], f'keeps should be fits+plausible: {kept}'
    assert 'AI dropped 3 school' in rep, f'report wrong: {rep}'
    # Fail-closed: AI errors -> strict tags, never the unfiltered pile
    with mock.patch('agents.ai_engine.is_available', return_value=True), \
         mock.patch('agents.ai_engine.generate_json', side_effect=RuntimeError('503')):
        kept2, rep2 = filter_by_category(biz, 'engineering colleges')
    assert len(kept2) == 7, 'strict school tags should keep schools'
    assert 'AI unavailable' in rep2
    # Malformed AI output (wrong counts) -> fail closed too
    with mock.patch('agents.ai_engine.is_available', return_value=True), \
         mock.patch('agents.ai_engine.generate_json', return_value={'fits': [1]}):
        kept3, rep3 = filter_by_category(biz, 'engineering colleges')
    assert 'AI unavailable' in rep3, 'malformed verdicts must fail closed'
    results['filter_ai_tiers'] = 'OK (tiers + fail-closed x2)'
except Exception as e:
    results['filter_ai_tiers'] = f'FAIL: {e}'

# 13. Dead handler rejection
try:
    o2 = Orchestrator()
    task1 = Task(id='dr1', name='generate_proposal', complexity=Complexity.HEAVY, payload={})
    r1 = o2.run('generate_proposal', {})
    assert not r1.success
    r2 = o2.run('draft_followup', {})
    assert not r2.success
    results['dead_rejection'] = 'OK'
except Exception as e:
    results['dead_rejection'] = f'FAIL: {e}'

# 13. Routing correctness
try:
    from agents.base import Complexity, Task
    from agents.lightweight import LightweightAgent
    from agents.medium import MediumAgent
    from agents.heavy import HeavyAgent
    lw = LightweightAgent()
    md = MediumAgent()
    hv = HeavyAgent()
    # Lightweight should NOT accept HEAVY tasks
    assert not lw.can_handle(Task(id='x', name='generate_website', complexity=Complexity.HEAVY, payload={}))
    # Heavy should NOT accept LIGHT tasks
    assert not hv.can_handle(Task(id='x', name='classify_text', complexity=Complexity.LIGHT, payload={}))
    results['routing'] = 'OK'
except Exception as e:
    results['routing'] = f'FAIL: {e}'

# 14. Classification word-boundary (barber != bar)
try:
    from agents.lightweight import LightweightAgent
    lw = LightweightAgent()
    task = Task(id='cl1', name='classify_text', complexity=Complexity.LIGHT, payload={'text': 'Mike Barber Shop'})
    r = lw.handle(task)
    cat = r.output['category']
    assert cat != 'food_and_drink', f"Barber classified as food: {cat}"
    results['classification'] = 'OK'
except Exception as e:
    results['classification'] = f'FAIL: {e}'

# 15. Parser multi-action chaining (the "enrich and draft" truncation bug)
try:
    from agents.chatbot import parse_intents, parse_intent, ActionType, Action

    # Deterministic supplement: enrich -> draft chaining without any AI call.
    acts = parse_intents('x', context=None)
    # (unknown input path covered by fallback; now test the supplement core)
    from agents.chatbot import _requested_steps, _make_chain_action, _NEXT_STEP

    steps = _requested_steps("find emails for them and draft an email for each")
    assert ActionType.ENRICH in steps, f"enrich keyword missed: {steps}"
    assert ActionType.DRAFT in steps, f"draft keyword missed: {steps}"

    # Simulate Gemini having emitted only enrich: supplement appends draft.
    seen = {ActionType.ENRICH}
    collected = [Action(type=ActionType.ENRICH, response="Looking up...")]
    nxt = _NEXT_STEP.get(ActionType.ENRICH)
    assert nxt == ActionType.DRAFT
    assert nxt in steps and nxt not in seen
    chained = _make_chain_action(nxt)
    assert chained and chained.type == ActionType.DRAFT
    assert chained.params.get("selection") == "all"

    # SEND must never be auto-chained.
    assert _make_chain_action(ActionType.SEND) is None
    assert ActionType.SEND not in steps

    # Back-compat: single-action wrapper returns an Action, not a list.
    one = parse_intent("hello")
    assert hasattr(one, "type"), "parse_intent must return a single Action"
    results['parser_chaining'] = 'OK'
except Exception as e:
    results['parser_chaining'] = f'FAIL: {e}'

# Summary
print('\n=== FINAL AUDIT ===')
for k, v in results.items():
    status = 'PASS' if v.startswith('OK') else 'FAIL'
    print(f'  [{status}] {k}: {v}')

fails = sum(1 for v in results.values() if v.startswith('FAIL'))
print(f'\nTotal: {len(results)} checks, {len(results)-fails} passed, {fails} failed')
