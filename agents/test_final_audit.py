import sys, os, json
sys.path.insert(0, '.')

results = {}

# 1. Imports
try:
    from agents import Orchestrator, Task, Complexity
    results['imports'] = 'OK'
except Exception as e:
    results['imports'] = f'FAIL: {e}'

# 2. Session create/load/save
try:
    from agents.session import Session, list_sessions
    s = Session()
    sid = s.create('audit_test_v2')
    s.save_data({'biz': [{'name': 'TestCo'}]}, 'businesses.json')
    data = s.load_data('businesses.json')
    assert data['biz'][0]['name'] == 'TestCo'
    sessions = list_sessions()
    assert any(x['id'] == sid for x in sessions)
    results['session'] = 'OK'
except Exception as e:
    results['session'] = f'FAIL: {e}'

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
    assert '[[t2_ba' in c1
    assert '[[t2_bb' in c1
    assert '[[outreach_t2' in c1
    p2 = create_contact_note({'name': 'BA', 'category': 'food', 'phone': '', 'address': ''}, session_id='t2', project_name='TP')
    c2 = open(p2, encoding='utf-8').read()
    assert '[[t2_tp' in c2
    p3 = create_outreach_form('t2', [{'name': 'BA'}], 'TP')
    c3 = open(p3, encoding='utf-8').read()
    assert '[[t2_ba' in c3
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

# 12. Dead handler rejection
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

# Summary
print('\n=== FINAL AUDIT ===')
for k, v in results.items():
    status = 'PASS' if v.startswith('OK') else 'FAIL'
    print(f'  [{status}] {k}: {v}')

fails = sum(1 for v in results.values() if v.startswith('FAIL'))
print(f'\nTotal: {len(results)} checks, {len(results)-fails} passed, {fails} failed')
