"""Brainstorming -- structured conversation that builds the AI's brain.

When the user starts a new session or says "let's brainstorm", JARVIS
asks a series of questions to understand their business, goals, and
target market. Answers are saved to the brain and used to personalize
all future emails and strategies.

The brainstorm is designed to be conversational, not a form. JARVIS
asks one question at a time, listens to the answer, and follows up
based on what it learns.
"""
from dataclasses import dataclass, field
from typing import Optional

from agents.brain import get_brain


# ── Brainstorm steps ────────────────────────────────────────────────

@dataclass
class BrainstormStep:
    """One question in the brainstorm flow."""
    key: str           # Field name in the brain profile
    question: str      # What to ask the user
    follow_ups: dict = field(default_factory=dict)  # {answer_keyword: follow_up_question}
    required: bool = False
    category: str = "profile"  # Where to save: profile, industry, strategy


BRAINSTORM_STEPS = [
    BrainstormStep(
        key="what_we_sell",
        question="What do you sell? (e.g., AutoCAD product keys, web design services, consulting)",
        required=True,
    ),
    BrainstormStep(
        key="product_details",
        question="Tell me more about your product. What makes it special? Why would someone buy it from you?",
        category="profile",
    ),
    BrainstormStep(
        key="target_customers",
        question="Who are your ideal customers? (e.g., educational centers, restaurants, shops)",
        required=True,
    ),
    BrainstormStep(
        key="ideal_customer_profile",
        question="Describe your perfect customer. What size are they? What's their budget? What problem do they have that you solve?",
        category="profile",
    ),
    BrainstormStep(
        key="our_story",
        question="What's your story? How did you start? What's your mission?",
        category="profile",
    ),
    BrainstormStep(
        key="competitors",
        question="Who are your competitors? What do they do better than you? What do you do better than them?",
        category="profile",
    ),
    BrainstormStep(
        key="goals",
        question="What are your goals for the next 3 months? How many customers do you want to reach?",
        category="profile",
    ),
    BrainstormStep(
        key="email_tone",
        question="What tone should emails have? (professional / friendly / casual / bold)",
        follow_ups={
            "professional": "Got it -- formal and respectful.",
            "friendly": "Got it -- warm and approachable.",
            "casual": "Got it -- relaxed and conversational.",
            "bold": "Got it -- confident and direct.",
        },
        category="profile",
    ),
    BrainstormStep(
        key="communication_style",
        question="Anything else about how you want to communicate? Any phrases to use or avoid?",
        category="profile",
    ),
    BrainstormStep(
        key="industry_pain_points",
        question="What problems do your customers typically have? What keeps them up at night?",
        category="industry",
    ),
    BrainstormStep(
        key="industry_hooks",
        question="What's the one thing that gets their attention? What makes them stop and read an email?",
        category="industry",
    ),
    BrainstormStep(
        key="past_outreach",
        question="Have you done outreach before? What worked? What didn't?",
        category="strategy",
    ),
    BrainstormStep(
        key="attachments",
        question="Do you have any files to attach to emails? (brochures, price lists, catalogs) If yes, paste the path. If no, skip.",
        category="profile",
    ),
]


class BrainstormSession:
    """Manages a brainstorming conversation with the user."""

    def __init__(self):
        self.brain = get_brain()
        self.step_index = 0
        self.answers = {}
        self.industry_name = ""
        self.complete = False

    def get_current_question(self) -> str:
        """Get the current question to ask the user."""
        if self.step_index >= len(BRAINSTORM_STEPS):
            self.complete = True
            return ""

        step = BRAINSTORM_STEPS[self.step_index]

        # Skip optional steps if user seems in a hurry
        if self.step_index > 0 and not step.required:
            # Every 3rd optional step, ask if they want to skip the rest
            if self.step_index % 4 == 0 and len(self.answers) > 2:
                return (f"{step.question}\n\n"
                        f"(Reply 'skip' to skip remaining questions, or 'done' to finish)")

        return step.question

    def process_answer(self, answer: str) -> str:
        """Process the user's answer and return a response."""
        if self.step_index >= len(BRAINSTORM_STEPS):
            self.complete = True
            return ""

        step = BRAINSTORM_STEPS[self.step_index]
        answer = answer.strip()

        # Handle skip/done
        if answer.lower() in ("skip", "done", "next", "s", "d"):
            self.step_index += 1
            if self.step_index >= len(BRAINSTORM_STEPS):
                self.complete = True
                return self._finish()
            return ""

        # Save the answer
        self.answers[step.key] = answer

        # First answer sets the industry name
        if step.key == "what_we_sell":
            self.industry_name = answer.split(",")[0].strip().lower()

        # Build response
        response = ""

        # Check for follow-up
        answer_lower = answer.lower()
        for keyword, follow_up in step.follow_ups.items():
            if keyword in answer_lower:
                response = follow_up
                break

        # Save to brain immediately
        self._save_answer(step, answer)

        # Move to next step
        self.step_index += 1
        if self.step_index >= len(BRAINSTORM_STEPS):
            self.complete = True
            if not response:
                response = self._finish()
            else:
                response += "\n\n" + self._finish()

        return response

    def _save_answer(self, step: BrainstormStep, answer: str):
        """Save an answer to the brain."""
        if step.category == "profile":
            profile = self.brain.get_profile()
            profile[step.key] = answer
            self.brain.save_profile(profile)

        elif step.category == "industry" and self.industry_name:
            if step.key == "industry_pain_points":
                points = [p.strip() for p in answer.split("\n") if p.strip()]
                self.brain.learn_industry(self.industry_name, pain_points=points)
            elif step.key == "industry_hooks":
                hooks = [h.strip() for h in answer.split("\n") if h.strip()]
                self.brain.learn_industry(self.industry_name, hooks=hooks)

        elif step.category == "strategy":
            if step.key == "past_outreach":
                self.brain.learn_industry(self.industry_name, notes=f"Past outreach: {answer}")

    def _finish(self) -> str:
        """Build the completion message."""
        stats = self.brain.get_stats()
        lines = [
            "Brain setup complete! Here's what I learned:",
            "",
        ]
        if self.answers.get("what_we_sell"):
            lines.append(f"  Product: {self.answers['what_we_sell']}")
        if self.answers.get("target_customers"):
            lines.append(f"  Target: {self.answers['target_customers']}")
        if self.answers.get("email_tone"):
            lines.append(f"  Tone: {self.answers['email_tone']}")
        if self.industry_name:
            lines.append(f"  Industry: {self.industry_name}")

        lines.extend([
            "",
            f"Brain now has {stats['total_files']} knowledge files.",
            "I'll use this to write better emails and find better leads.",
            "",
            "Ready to search for businesses? Tell me a location!",
        ])

        return "\n".join(lines)

    def get_progress(self) -> str:
        """Get a progress indicator."""
        total = len(BRAINSTORM_STEPS)
        done = min(self.step_index, total)
        pct = int(done / total * 100)
        bar_len = 20
        filled = int(bar_len * done / total)
        bar = "=" * filled + "-" * (bar_len - filled)
        return f"  [{bar}] {pct}% ({done}/{total} questions)"


def run_brainstorm_chat(session=None) -> dict:
    """Run a brainstorm session interactively (CLI mode).

    Returns the collected answers.
    """
    from agents.ui import C, p, success, typing_print, prompt

    bs = BrainstormSession()

    print()
    print(f"  {C.BOLD}{C.CYAN}BRAINSTORM SESSION{C.RESET}")
    print(f"  {C.DIM}I'll ask you a few questions to understand your business.{C.RESET}")
    print(f"  {C.DIM}This helps me write better emails and find better leads.{C.RESET}")
    print(f"  {C.DIM}Type 'skip' to skip any question, 'done' to finish early.{C.RESET}")
    print()

    while not bs.complete:
        question = bs.get_current_question()
        if not question:
            break

        # Show progress
        progress = bs.get_progress()
        print(f"  {C.DIM}{progress}{C.RESET}")
        print()

        # Ask
        typing_print(f"JARVIS: {question}", C.RED, delay=0.03)
        print()

        # Get answer
        try:
            answer = input(f"  {C.WHITE}You: {C.RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if not answer:
            continue

        if answer.lower() in ("exit", "quit", "back", "menu", "q"):
            break

        # Process
        response = bs.process_answer(answer)
        if response:
            typing_print(f"JARVIS: {response}", C.RED, delay=0.03)
            print()

    if not bs.complete:
        print(f"\n  {C.DIM}Brainstorm paused. You can continue anytime by saying 'brainstorm'.{C.RESET}")

    return bs.answers
