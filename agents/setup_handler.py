"""Setup handler — setup menu and business profile configuration."""
from agents.config import (
    get_gmail_user, set_gmail, get_sender_name, set_sender_name,
    get_gemini_key, set_gemini_key, get_ai_model,
    get_business_profile, set_business_profile, get_hunter_key,
)
from agents.workflows import setup_hunter_key
from agents.ui import (
    C, p, success, error, info, warn, prompt,
)


def run_setup():
    """Run the setup menu — configure Gmail, profile, API keys."""
    info("Setup")

    # Gmail
    gmail = get_gmail_user()
    if not gmail:
        user = prompt("Gmail address: ")
        pw = prompt("Gmail app password (16 chars): ")
        if user and pw:
            set_gmail(user, pw)
            success("Gmail configured!")
    else:
        success(f"Gmail: {gmail}")

    # Sender name
    name = get_sender_name()
    new_name = prompt(f"Sender name [{name}]: ")
    if new_name:
        set_sender_name(new_name)
        success(f"Sender name: {new_name}")

    # Business Profile
    profile = get_business_profile()
    print(f"\n  {C.BOLD}Business Profile:{C.RESET} {C.DIM}(tells AI what you sell){C.RESET}")
    if profile.get("product"):
        success(f"Product: {profile['product']}")
        success(f"Target: {profile.get('target_customers', 'Not set')}")
        update = prompt("Update business profile? (y/N): ").strip().lower()
        if update == "y":
            product = prompt(f"What do you sell? [{profile.get('product', '')}]: ")
            target = prompt(f"Who are your target customers? [{profile.get('target_customers', '')}]: ")
            value = prompt(f"What's your value proposition? [{profile.get('value_proposition', '')}]: ")
            new_profile = {
                "company_name": profile.get("company_name", ""),
                "product": product or profile.get("product", ""),
                "target_customers": target or profile.get("target_customers", ""),
                "value_proposition": value or profile.get("value_proposition", ""),
                "sender_name": get_sender_name(),
            }
            set_business_profile(new_profile)
            success("Business profile updated!")
    else:
        info("No business profile configured yet.")
        p("  This tells the AI what you sell so emails are personalized.", C.DIM)
        company = prompt("Company name: ")
        product = prompt("What do you sell? (e.g. AutoCAD product keys): ")
        target = prompt("Who are your target customers? (e.g. educational centers): ")
        value = prompt("What's your value proposition? (one sentence): ")
        if product:
            set_business_profile({
                "company_name": company,
                "product": product,
                "target_customers": target,
                "value_proposition": value,
                "sender_name": get_sender_name(),
            })
            success("Business profile saved! Emails will now be personalized.")
        else:
            warn("Skipped. You can set this later with [S].")

    # Hunter.io
    if not get_hunter_key():
        key = prompt("Hunter.io API key (Enter to skip): ")
        if key:
            setup_hunter_key(key)
            success("Hunter.io key saved!")

    # Gemini AI
    gemini = get_gemini_key()
    if gemini:
        success(f"Gemini AI: configured ({get_ai_model()})")
    else:
        info("Gemini AI - free AI for emails, websites, code")
        p("  Get a free key at: https://aistudio.google.com/apikey", C.DIM)
        gkey = prompt("Gemini API key (Enter to skip): ")
        if gkey:
            set_gemini_key(gkey)
            success("Gemini AI configured!")
            from agents import ai_engine
            if ai_engine.is_available():
                success("AI engine online")
            else:
                warn("AI engine failed to connect - check key")

    success("Setup complete!")
