"""Dashboard handler — learning dashboard display."""
from agents.config import get_ai_model
from agents.ui import (
    C, p, error, clear, banner,
)


def run_learning_dashboard():
    """Show what the AI has learned — categories, hooks, email stats."""
    from agents.learn import get_learning_dashboard

    clear()
    banner()

    print(f"\n  {C.BOLD}{C.CYAN}J.A.R.V.I.S Learning Dashboard{C.RESET}")
    print(f"  {C.DIM}What the AI has learned from your outreach sessions{C.RESET}")
    print("  " + "="*55)

    try:
        dashboard = get_learning_dashboard()
    except Exception as e:
        error(f"Failed to load dashboard: {e}")
        return

    # Overview
    s = dashboard["summary"]
    print(f"\n  {C.BOLD}Overview{C.RESET}")
    p(f"  Businesses analyzed:    {s['total_businesses_seen']}", C.WHITE)
    p(f"  Categories learned:     {s['categories_learned']}", C.WHITE)
    p(f"  Locations explored:     {s['locations_explored']}", C.WHITE)
    p(f"  Emails drafted:         {s['emails_sent']}", C.WHITE)
    p(f"  Open rate:              {s['open_rate']}", C.GREEN if s['open_rate'] != 'N/A' else C.DIM)
    p(f"  Reply rate:             {s['reply_rate']}", C.GREEN if s['reply_rate'] != 'N/A' else C.DIM)
    p(f"  Feedback entries:       {s['feedback_entries']}", C.WHITE)
    if dashboard["avg_feedback_rating"] > 0:
        rating = dashboard["avg_feedback_rating"]
        stars = "*" * int(rating) + "-" * (5 - int(rating))
        p(f"  Avg draft rating:       [{stars}] {rating:.1f}/5", C.YELLOW)

    # Categories
    cats = dashboard["categories"]
    if cats:
        print(f"\n  {C.BOLD}Industry Knowledge{C.RESET}")
        for cat in cats:
            print(f"\n  {C.CYAN}{cat['name'].upper()}{C.RESET}")
            p(f"    Businesses seen:    {cat['count']}", C.WHITE)
            p(f"    Have website:       {cat['website_pct']:.0f}%", C.GREEN if cat['website_pct'] > 50 else C.YELLOW)
            p(f"    Have email:         {cat['email_pct']:.0f}%", C.GREEN if cat['email_pct'] > 50 else C.YELLOW)
            if cat["emails_sent"] > 0:
                p(f"    Emails drafted:     {cat['emails_sent']}", C.WHITE)
            if cat["emails_rejected"] > 0:
                p(f"    Rejected:           {cat['emails_rejected']}", C.RED)
            if cat["common_tags"]:
                p(f"    Common attributes:  {', '.join(cat['common_tags'])}", C.DIM)
            if cat["sample_names"]:
                p(f"    Example businesses: {', '.join(cat['sample_names'][:3])}", C.DIM)
            if cat["top_hooks"]:
                p(f"    Best hooks:", C.BOLD)
                for hook in cat["top_hooks"][:2]:
                    p(f"      \"{hook[:70]}\"", C.GREEN)
            if cat["top_subjects"]:
                p(f"    Top subjects:", C.BOLD)
                for subj in cat["top_subjects"][:2]:
                    p(f"      \"{subj[:70]}\"", C.GREEN)

    # Email Performance
    templates = dashboard["email_templates"]
    if templates:
        print(f"\n  {C.BOLD}Email Performance{C.RESET}")
        for t in templates[:5]:
            p(f"  [{t['category']}] {t['subject'][:50]}", C.WHITE)
            p(f"    Sent: {t['sent']}  Opened: {t['opened']}  Replied: {t['replied']}  Rejected: {t['rejected']}", C.DIM)

    # Locations
    locs = dashboard["locations"]
    if locs:
        print(f"\n  {C.BOLD}Locations Explored{C.RESET}")
        for loc in locs:
            p(f"  {loc['name']}", C.WHITE)
            p(f"    Sessions: {loc['sessions']}  Found: {loc['total_found']}  No-site: {loc['no_site_pct']:.0f}%", C.DIM)
            if loc["categories"]:
                p(f"    Categories: {', '.join(loc['categories'][:5])}", C.DIM)

    # Recent Feedback
    feedback = dashboard["recent_feedback"]
    if feedback:
        print(f"\n  {C.BOLD}Recent Feedback{C.RESET}")
        for f in feedback[-3:]:
            stars = "*" * f.get("rating", 0) + "-" * (5 - f.get("rating", 0))
            p(f"  [{stars}] {f.get('business', '?')} ({f.get('category', '?')})", C.WHITE)
            if f.get("notes"):
                p(f"    {f['notes']}", C.DIM)

    # AI Status
    print(f"\n  {C.BOLD}AI Status{C.RESET}")
    from agents import ai_engine
    from agents.ai import providers
    st = providers.status()
    if st["active"]:
        p(f"  Provider:    {C.GREEN}{st['provider']}{C.RESET} (routing all AI calls)")
        p(f"  Model:       {st['model'] or '(unset)'}", C.DIM)
        if ai_engine.is_available():
            p(f"  Fallback:    Gemini online ({get_ai_model()})", C.DIM)
    elif ai_engine.is_available():
        p(f"  Gemini AI:   {C.GREEN}ONLINE{C.RESET} (emails + websites generated)")
        p(f"  Model:       {get_ai_model()}", C.DIM)
    else:
        p(f"  Gemini AI:   {C.YELLOW}OFFLINE{C.RESET} (using templates)")
        p(f"  Tip: Press [S] to configure Gemini API key", C.DIM)

    print(f"\n  {C.DIM}Knowledge base: F:/jodiac/agent_output/knowledge_base/{C.RESET}")
    print(f"  {C.DIM}Data improves with each outreach session.{C.RESET}")
