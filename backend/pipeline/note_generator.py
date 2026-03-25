"""
pipeline/note_generator.py
──────────────────────────
Step 6 + Step 7 + Step 8 — Note Generation, Merging, Refinement.

For each lecture topic:
  • Slide content (verbatim from slide_analyzer)
  • Retrieved textbook context (from topic_retriever)
  → One GPT call per topic → structured Markdown section

Then:
  • Merge all sections into one document (Step 7)
  • Optional single refinement pass (Step 8)

LLM call budget (as required by spec):
  1  call for slide analysis        (slide_analyzer.py)
  N  calls for per-topic generation (this file)
  1  call for refinement            (this file, optional)

Fallback: if Azure is unavailable, builds notes from slide content alone
using deterministic templates — same quality as local_summarizer.py.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

from pipeline.slide_analyzer import SlideTopic
from agents.latex_utils import fix_latex_delimiters

logger = logging.getLogger(__name__)


# ── Table repair ──────────────────────────────────────────────────────────────

def _fix_tables(text: str) -> str:
    """
    Repair common Groq/LLM table generation errors:
    1. Missing alignment row  (header row immediately followed by data row)
    2. Rows with inconsistent column counts — pad or trim to match header
    3. Strip accidental leading/trailing whitespace inside cells
    """
    import re
    lines = text.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Detect a pipe-table header row: starts and ends with |, has at least one |
        if re.match(r'^\s*\|.*\|\s*$', line) and '|' in line:
            # Count columns from header
            header_cells = [c.strip() for c in line.strip().strip('|').split('|')]
            ncols = len(header_cells)
            result.append(line)
            # Check if next non-empty line is already an alignment row
            j = i + 1
            if j < len(lines) and re.match(r'^\s*\|[\s|:\-]+\|\s*$', lines[j]):
                # Already has alignment row — just ensure column count matches
                align_cells = [c.strip() for c in lines[j].strip().strip('|').split('|')]
                if len(align_cells) != ncols:
                    # Rebuild alignment row
                    lines[j] = '| ' + ' | '.join(['---'] * ncols) + ' |'
                result.append(lines[j])
                i = j + 1
            else:
                # Insert missing alignment row
                result.append('| ' + ' | '.join(['---'] * ncols) + ' |')
                i += 1
            # Process data rows: normalise column count
            while i < len(lines):
                dline = lines[i]
                if not re.match(r'^\s*\|.*\|\s*$', dline):
                    break  # end of this table
                data_cells = [c.strip() for c in dline.strip().strip('|').split('|')]
                if len(data_cells) < ncols:
                    data_cells.extend([''] * (ncols - len(data_cells)))
                elif len(data_cells) > ncols:
                    data_cells = data_cells[:ncols]
                result.append('| ' + ' | '.join(data_cells) + ' |')
                i += 1
            continue
        result.append(line)
        i += 1
    return '\n'.join(result)


# ── Safe template substitution ──────────────────────────────────────────────

def _safe_format(template: str, **kwargs) -> str:
    """
    Substitute named placeholders like {topic} in a template string WITHOUT
    using str.format(), which chokes on LaTeX curly-braces in the values
    (e.g. '{x^2}' raises KeyError: 'x^2').
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


# -- Prompts ------------------------------------------------------------------

_NOTE_SYSTEM = """You are AuraGraph -- an AI study notes engine for engineering students.

YOUR ONLY JOB: Convert professor slides and lecture notes into study notes.

THE ONE RULE THAT OVERRIDES EVERYTHING ELSE:
Every single piece of content present in the input slides/notes MUST appear in the output.
Not a summary of it. Not a mention of it. The actual content -- every formula, every
definition, every algorithm step, every property, every condition, every exception,
every worked example, every edge case -- must be present in the generated notes.

THE SLIDE TEXT IS THE CONTRACT:
Read the SLIDE / LECTURE NOTES CONTENT section line by line.
Every line that is not a boundary marker (--- Slide N --- / --- Page N ---) is content
that MUST appear in your output. Think of each non-marker line as a separate obligation.

METADATA FILTER (CRITICAL — applies before everything else):
The following lines are ADMINISTRATIVE METADATA, not teaching content.
They must NEVER appear anywhere in the generated notes:
  • Course codes: anything matching "LETTERS-DIGITS: COURSE TITLE"
    e.g. "CSL-373: PROBABILITY THEORY FOR COMPUTER ENGINEERS" → ignore
  • Lecture/session headers: "Lecture N (date, time)" or "Lec N (...)"
    e.g. "Lecture 10 (05/02/2026, 2 − 3 PM)" → ignore
  • Professor names, institution names, department names
  • Any line that is only a date, time, or room number
These lines are infrastructure — treat them as invisible. They are NOT obligations.

Proficiency level NEVER controls what is included. It only controls HOW things are explained.
A concept present in the slides that is absent from the notes is always an error,
regardless of proficiency level.

ACCURACY RULE — RESPONSIBLE AI OUTPUT:
You are the ground truth for correctness. Before writing any formula, definition, or claim,
verify it against your knowledge. If the source has an error, write the correct version silently.
This covers:
  - Formula errors (wrong sign, wrong operator, missing factor, inverted fraction)
  - Incomplete definitions (e.g. "monotonic" without "strictly monotonic and differentiable")
  - Wrong theorem conditions or directions of implication
  - OCR artifacts (garbled math) — reconstruct correct LaTeX from context
  - OCR garbled words (e.g. "hyptvnse", "resistanc3", "eigenvalu3") — silently replace with
    the correct technical term; NEVER copy garbled text into notes verbatim
  - Ambiguous abbreviations — resolve to the standard full term

CRITICAL — NEVER EXPOSE ERRORS TO STUDENTS:
The following phrases and patterns are STRICTLY FORBIDDEN in your output:
  • "the slides contain an error"
  • "there is a mistake"  / "this is a mistake"
  • "the correct spelling is"  / "the correct term is"
  • "OCR error" / "OCR artifact" / "OCR noise"
  • "typo" / "misspelling" / "garbled" / "corrupted"
  • "should be" in the context of correcting source material
  • Any annotation that draws the student's attention to an error in the source
If the source material has an error, correct it in your output and say nothing about it.
Students trust these notes. Never undermine that trust by exposing source defects.

BANNED PHRASES (never write): "delve", "explore", "It is important to note",
"In conclusion", "In this section", "As we can see", "Please note", "Overview:".
"""

# Per-proficiency instruction blocks injected into the user prompt

_PROFICIENCY_BEGINNER = """PROFICIENCY: BEGINNER — Self-Paced Learner Starting From Scratch

GOAL: The student is encountering this topic for the very first time.
These notes must be completely self-contained — the student should need nothing else.
Every single concept from the slides must be explained as if teaching a smart but
uninitiated person who has never seen this material before.

══════════════════════════════════════════════════════
BEFORE WRITING ANYTHING — MANDATORY PRE-SCAN:
  Read the entire slide content. Mentally list every:
    - named concept or term
    - formula or equation
    - definition
    - algorithm or procedure
    - condition, constraint, or exception
    - worked example or numerical value
  This is your checklist. You CANNOT finish until every item is covered.
══════════════════════════════════════════════════════

FOR EVERY CONCEPT, FORMULA, DEFINITION, AND ALGORITHM, write in this exact order:

  STEP 1 — Plain-English opening (mandatory first sentence):
    "In simple terms, [X] means ..." — never start with a formula.

  STEP 2 — Real-world analogy (mandatory, in a blockquote):
    > Think of it like [analogy] — [one sentence connecting the analogy to the concept].

  STEP 3 — Formal definition:
    State precisely, only AFTER the student has intuition from Steps 1-2.

  STEP 4 — For EVERY formula without exception:
    a. Display equation:  $$  formula  $$
    b. Symbol table immediately below:
       | Symbol | Meaning | Units or Range |
       |--------|---------|----------------|
    c. Plain-English walkthrough: "This formula says [X] equals [Y] times [Z],
       meaning that when [Y] increases, [X] increases because ..."
    d. Fully worked numerical example — show EVERY arithmetic step.
       Label each step: "Step 1: substitute ... → Step 2: simplify ... → Step 3: ..."

  STEP 5 — For every algorithm or multi-step process:
    Numbered procedure. Each step gets one sentence explaining WHY it is done.

  STEP 6 — For every condition or constraint:
    "This condition is required because without it, [thing] would [fail/blow up/be undefined]."

  STEP 7 — For every edge case:
    "This special case arises when [X]. In this situation, [consequence/what changes]."

SAFETY RULE (coverage always beats depth):
  If running low on output space: give remaining concepts their name + formula +
  one-line definition. NEVER silently skip a concept to write more about another.

MINIMUM OUTPUT SIZE — NON-NEGOTIABLE:
  • Count the --- Slide N --- / --- Page N --- markers in the input.
    Each marker MUST produce at minimum one dedicated ### sub-section.
    FOUR slides in → FOUR ### sub-sections minimum. NEVER collapse them.
  • Each ### sub-section: minimum 500 words.
  • Every formula in that sub-section MUST complete all 7 Steps fully
    (plain English → analogy → formal definition → symbol table →
    worked example with every arithmetic step → conditions → edge cases).
  • Total output MUST be 8–10× the length of the raw slide text.
    A slide with 3 bullet points expands to 3–4 detailed paragraphs each.
    Short input = MORE explanation needed, not less.

LENGTH: These are the longest, most detailed notes of the three levels.
        Do not truncate. Do not compress. Do not skip.
"""

_PROFICIENCY_INTERMEDIATE = """PROFICIENCY: INTERMEDIATE — Knows the Basics, Building Full Fluency

GOAL: The student has seen this subject before but has gaps or shallow spots.
These notes must achieve three things simultaneously:
  (a) 100% of the slide content — every concept present, zero omissions
  (b) Topics that are hard, rushed, or only briefly mentioned in the slides get
      a deeper, more thorough explanation than the slides provided
  (c) Textbook analogies and explanations that the slides glossed over are
      actively brought in and integrated

══════════════════════════════════════════════════════
TWO-TIER TREATMENT — classify each slide item first:

TIER 1 — Clearly explained in the slides (full treatment, not rushed):
  • Concise formal definition.
  • Formula in display LaTeX with all symbols defined inline.
  • One sentence of intuition: what the formula is really saying.
  • Worked example using instructive numbers that reveal the formula's behaviour.
  • All conditions, exceptions, edge cases: state each + explain consequence of ignoring.

TIER 2 — Hard, briefly mentioned, glossed over, or just listed without explanation:
  (Signs: a short bullet with no explanation, a formula with no context, a term
   introduced without definition, a "see textbook" hint, a concept named and moved on)
  Give these topics the FULL treatment:
  • Explain from first principles — fill the exact gap the slide left.
  • Bring in the textbook's fuller explanation, better analogy, or cleaner notation.
    Label it [Textbook] inline whenever you draw from the textbook context.
  • Show WHY the formula or result holds, not just what it says.
  • Detailed worked example with non-obvious or illuminating numbers.
  • Comparison table wherever this concept is easily confused with another:
    | Concept | Formula | When to use | Key difference |
    |---------|---------|-------------|----------------|
══════════════════════════════════════════════════════

TEXTBOOK INTEGRATION:
  The textbook context is a PRIMARY resource — use it actively:
  • For Tier 2 topics especially: bring in the textbook's explanation, analogy, proof.
  • If the textbook has a worked example matching the topic: include or adapt it.
  • Do NOT introduce textbook topics that have no corresponding slide content.

MINIMUM OUTPUT SIZE — NON-NEGOTIABLE:
  • Count the --- Slide N --- / --- Page N --- markers in the input.
    Each marker MUST produce at minimum one dedicated ### sub-section.
    FOUR slides in → FOUR ### sub-sections minimum. NEVER collapse them.
  • Tier 1 sub-sections: minimum 350 words.
    Tier 2 sub-sections (rushed, hard, or briefly mentioned): minimum 500 words.
  • Total output MUST be 5–7× the length of the raw slide text.
    A slide that has only 2 lines still requires the full Tier 1 or Tier 2
    treatment — input brevity never justifies a brief output.

COVERAGE GUARANTEE: Every item from the slides MUST appear.
LENGTH: Comprehensive — every slide item covered; Tier 2 items covered in more depth.
"""

_PROFICIENCY_ADVANCED = """PROFICIENCY: ADVANCED — Exam-Ready, Pushing to Genuine Mastery

GOAL: The student knows the slides well. Push them to depth the slides didn't reach.
These notes must:
  (a) Include 100% of the slide content — nothing omitted
  (b) Go deeper on every non-trivial concept: proofs, generalisations, precise
      conditions, connections to related results, what breaks and why
  (c) Include hard, multi-concept problems with complete solutions

══════════════════════════════════════════════════════
FOR EVERY CONCEPT IN THE SLIDES:

  BASIC DEFINITIONS & STANDARD PROPERTIES:
    State concisely. One or two precise sentences. No hand-holding.

  EVERY FORMULA — mandatory:
    a. Display LaTeX: $$ formula $$
    b. Non-trivial derivation → show it in full.
       Terse algebra. No commentary between steps.
       Skip ONLY trivially obvious rearrangements.
    c. State every condition for validity explicitly:
       convergence criteria, domain restrictions, assumptions, boundary conditions.
       If the slide omits a mathematically necessary condition — ADD IT.

  GOING DEEPER (mandatory for every important concept):
    After the slide-level content, add at least one of:
    • The stronger or more general version of the theorem/result
    • The precise condition under which this result breaks down — and why
    • The connection to a related concept (how this is a special case, or generalises)
    • The key mathematical insight behind WHY this is true
    Draw from the textbook context as the source for this deeper layer.

  HARD WORKED PROBLEMS (mandatory — at least one per major concept):
    Use genuinely challenging problems, not plug-and-compute:
    • Require two or more slide concepts applied together
    • Non-standard parameters that expose edge-case or boundary behaviour
    • Problems that appear simple but need a key insight to crack
    • Derivation or proof-based questions where the concept warrants it
    Show FULL solutions with every non-trivial step.
    End each: "Key insight: [the non-obvious thing that unlocks this]"

  EDGE CASES & EXCEPTIONS:
    Explain the mathematical REASON each one arises — not just that it exists.
══════════════════════════════════════════════════════

MINIMUM OUTPUT SIZE — NON-NEGOTIABLE:
  • Count the --- Slide N --- / --- Page N --- markers in the input.
    Each marker MUST produce at minimum one dedicated ### sub-section.
    FOUR slides in → FOUR ### sub-sections minimum. NEVER collapse them.
  • Each sub-section: minimum 400 words PLUS at least one derivation or
    hard multi-concept problem with a full solution.
  • Total output MUST be 4–6× the length of the raw slide text.

COVERAGE GUARANTEE: Every slide item MUST appear. Advanced treatment adds depth
AROUND each item — it never removes or condenses slide content for extra material.
LENGTH: As long as needed. Never truncate a derivation or a problem solution.
"""

_NOTE_USER_TEMPLATE = """Generate study notes for the following lecture topic.

TOPIC: {topic}

═════════════════════════════════════════════════════════════════
MANDATORY COVERAGE CHECKLIST — YOU MUST ADDRESS EVERY ITEM
═════════════════════════════════════════════════════════════════
Before you write a single word, read this checklist. Before you finish,
verify every item is in your output. A missing item is a hard error.

{key_points_block}
═════════════════════════════════════════════════════════════════
SLIDE / LECTURE NOTES CONTENT (primary source — every non-marker line is an obligation):
{slide_text}

═════════════════════════════════════════════════════════════════
LINE-BY-LINE OBLIGATION:
First, IGNORE these metadata lines — they are NOT content obligations:
  • Course code headers (e.g. "CSL-373: PROBABILITY THEORY FOR COMPUTER ENGINEERS")
  • Lecture headers (e.g. "Lecture 10 (05/02/2026, 2 − 3 PM)")
  • Professor names, institution names, dates, room numbers
Then, for every remaining non-marker line:
Each such line is a SEPARATE MANDATORY ITEM that must appear in your notes.
If a line is a formula: the formula must appear.
If a line is a definition: the definition must appear.
If a line is a property or condition: it must appear.
If a line is a worked step or example value: it must appear.
If a line starts with "Exercise N." or "Example N.": it is TEACHING CONTENT.
  These must appear in notes with the full statement and a worked solution / hint.
  "Exercise" lines show students what skills to practice — they are obligations, not optional.
  "Example" lines show concepts applied to concrete cases — they are obligations, not optional.
There are NO exceptions. Depth and style are adjustable. Omission is not.
═════════════════════════════════════════════════════════════════

PER-SLIDE SUB-SECTIONS (STRUCTURAL REQUIREMENT):
Count the --- Slide N --- / --- Page N --- markers in the SLIDE CONTENT above.
Each such marker = one slide of teaching content = one ### sub-heading in your output.
NEVER collapse multiple slides into a single undivided paragraph block.
Only exception: two consecutive slides that are an identical concept continued
(e.g. "Proof — Part 2") may share one ### heading.
All other slides → separate ### sub-sections, each with its own full treatment.

{textbook_instruction}

{proficiency_block}

COVERAGE RULES (absolute — apply at ALL proficiency levels)
===========================================================
1. Every item in the MANDATORY COVERAGE CHECKLIST above MUST appear.
2. Every formula, definition, algorithm, theorem, condition, edge case and
   worked example in the SLIDE CONTENT above MUST appear.
3. Every non-marker line of the SLIDE CONTENT is a separate obligation.
4. Proficiency controls HOW deeply you explain each item. It never controls
   WHETHER an item appears. Depth is adjustable. Omission is not.
5. If you are running low on output budget: give each remaining concept
   a brief name + formula + one-line definition. Never silently drop an item.

STRUCTURE
=========
  - Start with: ## {topic}
  - Use ### sub-headings for distinct sub-topics within the section.
  - NEVER use # (h1) headings anywhere in your output.
  - For EXERCISES and EXAMPLES: use a blockquote callout, NOT a heading:
      > **Exercise N:** [full problem statement]
      > *Hint / Solution:* [worked answer or clear hint]
    Never write "# Exercise", "## Exercise", or "### Exercise" — always blockquote.
  - End the section with:
      > 📝 **Exam Tip:** [the single most-tested fact or most common exam mistake for this topic]

MATHEMATICS
===========
  - ALL math in LaTeX. Never write "integral", "sigma", "omega", "delta" as English.
  - Inline math: $expression$
  - Display math: $$
    formula
    $$
  - NEVER use \\\\( \\\\) or \\\\[ \\\\]. Only $ and $$.
  - OCR garbled math: reconstruct the correct LaTeX from your knowledge.
  - ^ is ALWAYS superscript (power/exponent). _ is ALWAYS subscript (index/element).
    NEVER swap them. $p^j$ = p raised to the power j. $p_j$ = the j-th element of p.
    Common errors to avoid: $e_{j\\omega}$ → must be $e^{j\\omega}$; $z_{-1}$ → must be $z^{-1}$.

TABLES
======
  - Pipe-tables only: header row + |---|---| alignment row + data rows.
  - Never use HTML tables.

OUTPUT: Start immediately with ## {topic}. End with the Exam Tip.
"""
_REFINEMENT_SYSTEM = """\
You are an expert academic editor improving engineering study notes.
Your job is to enhance clarity, completeness, and structure without removing content.
"""

_REFINEMENT_USER = """\
Below are draft study notes. Improve them strictly according to these rules:

RULES:
• Do NOT remove any ## sections or change their order.
• Do NOT shorten notes — if anything, add missing detail.
• Fix awkward phrasing, redundancy, and unclear explanations.
• Ensure all formulas use $...$ or $$ ... $$ LaTeX — never \\( \\) or \\[ \\].
• Ensure every ## section ends with > 📝 **Exam Tip:** ...
• Remove any preamble or conclusion text (e.g. "Here are your notes").• Do NOT add new topics that were not already present.• Output ONLY the improved notes — no commentary, no labels.

NOTES:
{notes}
"""

# ── Post-generation self-verification prompts ─────────────────────────────────

_VERIFY_NOTES_SYSTEM = """\
You are a senior engineering professor and fact-checker performing a Responsible AI
quality review of AI-generated study notes before they are shown to a student.

You are the ground truth. Your own knowledge overrides whatever the notes say.

TWO-PHASE REVIEW:

PHASE 1 — FACTUAL ACCURACY:
Check every single claim against your knowledge:
  FORMULAS        — sign, operator (+/−/×/÷), exponent, argument, fraction orientation,
                    missing factors, extra factors.
                    Common LLM error: using division where multiplication is required,
                    e.g.  f_Y(y) = f_X(f⁻¹(y)) / |...|   →  must be  × |...|
  DEFINITIONS     — are all conditions present? (e.g. "monotonic" → "strictly monotonic
                    and differentiable"; "linear" → "linear and time-invariant")
  THEOREM STATEMENTS — direction of implication correct? equality vs inequality correct?
                    all hypotheses listed?
  CONCEPTUAL CLAIMS — cause/effect, direction, units, domains, convergence conditions.
  WORKED EXAMPLES — re-run every calculation. If the answer or any step is wrong, fix it.

PHASE 2 — RESPONSIBLE AI OUTPUT SAFETY:
Scan the ENTIRE output for any language that exposes source defects to the student.
The following patterns must NEVER appear in notes shown to a student.
If found, silently remove or rewrite them:
  • Any sentence mentioning "the slides contain an error" or "there is a mistake in the source"
  • Any sentence containing "OCR", "garbled", "corrupted", "typo", "misspelling"
  • Phrases like "the correct spelling is", "the correct term is", "should be X instead of Y"
    when used to comment on source material rather than explain a concept
  • Any text that looks like a garbled word (non-word sequences like "hyptvnse", "resistanc3")
    — replace with the correct technical term
  • The phrases "Note correction:", "⚠️ Note correction:" — remove them; students should
    never see acknowledgements that their notes were wrong
If any such content is found, rewrite the affected sentence to simply state the correct
information cleanly, as if it were always written that way.

RULES:
  • Fix errors silently — do NOT say "the original notes said X" or "I corrected".
  • Do NOT remove any ## sections, alter the order, or shorten any section.
  • Do NOT change correct content.
  • Ensure every formula remains in valid LaTeX ($...$ or $$...$$).
  • Output ONLY the corrected notes — no preamble, no commentary, no labels.

If no errors are found and the output safety scan passes, output the notes unchanged.
"""

_VERIFY_NOTES_USER = """\
These are AI-generated study notes. Fact-check every formula, definition,
theorem statement, conceptual claim, and worked example against your knowledge.
Fix all errors silently. Return the complete corrected notes.

NOTES:
{notes}
"""

# ── Textbook instruction builder ─────────────────────────────────────────────

def _resolve_proficiency_block(proficiency: str) -> str:
    """
    Map a proficiency string to the matching instruction block.
    Accepted values (case-insensitive):
      Beginner / Foundations / Basic / Foundation
      Intermediate / Practitioner / Medium
      Advanced / Expert
    Falls back to Intermediate for unknown values.
    """
    p = proficiency.strip().lower()
    if p in ("beginner", "foundations", "foundation", "basic"):
        return _PROFICIENCY_BEGINNER
    if p in ("advanced", "expert"):
        return _PROFICIENCY_ADVANCED
    # default: intermediate
    return _PROFICIENCY_INTERMEDIATE


def _textbook_instruction_block(textbook_context: str, max_chars: int = 10_000) -> str:
    """Build the textbook context block for the note generation prompt."""
    has_tb = bool(textbook_context) and textbook_context.strip() not in ("", "(none)")
    if has_tb:
        return (
            "TEXTBOOK CONTEXT (use this aggressively — it is a high-quality academic source):\n"
            + textbook_context[:max_chars]
            + "\n\n"
            "TEXTBOOK USAGE RULES:\n"
            "• Pull precise definitions, full theorem statements, and complete proofs directly from the textbook.\n"
            "• If the textbook has a worked example that matches the topic, reproduce or adapt it — cite [Textbook] inline.\n"
            "• If the textbook shows a derivation, include it step-by-step in the notes.\n"
            "• Prefer the textbook's notation when it is cleaner than the slide notation.\n"
            "• Use textbook chapter/section headings as sub-heading hints where relevant.\n"
            "• Do NOT introduce topics that appear ONLY in the textbook but NOT in the slides."
        )
    return (
        "TEXTBOOK CONTEXT: None provided.\n"
        "→ Generate SELF-CONTAINED notes from slides alone. Be thorough:\n"
        "  define every term used, show full derivations, and make the worked example"
        " doubly clear since the student has no other reference."
    )


# ── Post-processor ────────────────────────────────────────────────────────────

_PREAMBLE_RE = re.compile(
    r'^(?:here(?:\s+are|is)|sure[,!]?|certainly[,!]?|below|of course[,!]?'
    r'|the\s+following|these\s+are)\b.*?\n+',
    re.IGNORECASE | re.DOTALL,
)

def _post_process_section(text: str, topic: str) -> str:
    """
    Clean up a single generated ## section:
    1. Strip any LLM preamble before the ## heading
    2. Ensure the section starts with ## topic
    3. Ensure it ends with an Exam Tip blockquote
    """
    # 1. strip preamble lines before the ## heading
    lines = text.split('\n')
    start = 0
    for i, line in enumerate(lines):
        if line.lstrip().startswith('##'):
            start = i
            break
    text = '\n'.join(lines[start:]).strip()

    # 2. ensure heading present
    if not text.lstrip().startswith('##'):
        text = f'## {topic}\n\n{text}'

    # 3. ensure exam tip present at end
    if '📝' not in text and 'Exam Tip' not in text:
        text = text.rstrip() + f'\n\n> 📝 **Exam Tip:** Review the definition and key formula for {topic}.'

    return text.strip()

# ── LLM availability + call helpers ──────────────────────────────────────────

def _azure_available() -> bool:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    api_key  = os.environ.get("AZURE_OPENAI_API_KEY",  "")
    # FIX (round 4): mirror main.py — also reject "placeholder" endpoints/keys
    return (
        bool(endpoint) and bool(api_key)
        and "mock"        not in endpoint.lower()
        and "placeholder" not in endpoint.lower()
        and "placeholder" not in api_key.lower()
    )


def _groq_available() -> bool:
    key = os.environ.get("GROQ_API_KEY", "")
    return key not in ("", "your-groq-api-key-here")


async def _call_azure(
    system: str,
    user:   str,
    max_tokens: int = 16000,
) -> Optional[str]:
    """
    Azure OpenAI call via httpx async client (true async — no thread pool).
    FIX C1: was asyncio.to_thread(_sync) which blocked thread pool under load.
    Includes one 429 retry with Retry-After back-off.
    If finish_reason=length (output truncated), retries once with the hard ceiling (16,000).
    """
    if not _azure_available():
        return None
    try:
        import httpx
        endpoint   = os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
        api_key    = os.environ.get("AZURE_OPENAI_API_KEY",  "")
        api_ver    = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_ver}"
        headers = {"api-key": api_key, "Content-Type": "application/json"}

        # First attempt with requested budget; second attempt (if truncated) with hard ceiling
        _AZURE_HARD_CEILING = 16_000   # GPT-4o supports 16,384 output tokens
        for attempt_tokens in [max_tokens, _AZURE_HARD_CEILING]:
            payload = {
                "messages":   [{"role": "system", "content": system},
                               {"role": "user",   "content": user}],
                "max_tokens": attempt_tokens,
                "temperature": 0.3,
            }
            for rate_attempt in range(2):
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 429 and rate_attempt == 0:
                    wait = int(resp.headers.get("Retry-After", "10"))
                    logger.warning("note_generator Azure 429 — retrying in %d s", wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                data   = resp.json()
                choice = data["choices"][0]
                if choice.get("finish_reason") == "length":
                    if attempt_tokens < _AZURE_HARD_CEILING:
                        logger.warning(
                            "note_generator Azure: output truncated at %d tokens — "
                            "retrying with hard ceiling %d", attempt_tokens, _AZURE_HARD_CEILING
                        )
                        break   # break inner rate-retry loop → outer loop increases tokens
                    else:
                        logger.warning(
                            "note_generator Azure: output still truncated at hard ceiling "
                            "%d tokens — returning partial result", _AZURE_HARD_CEILING
                        )
                return choice["message"]["content"].strip()
    except Exception as e:
        logger.warning("note_generator Azure async call failed: %s", e)
    return None


async def _call_groq(
    system: str,
    user:   str,
    max_tokens: int = 16000,
) -> Optional[str]:
    """
    Groq call via httpx async client (true async — no thread pool).
    FIX C1: was asyncio.to_thread(_sync) which blocked thread pool under load.
    Includes one 429 retry with Retry-After back-off.
    If finish_reason=length (output truncated), retries once with hard ceiling (16,000).
    """
    if not _groq_available():
        return None
    try:
        import httpx
        api_key = os.environ.get("GROQ_API_KEY", "")
        model   = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        _GROQ_HARD_CEILING = 16_000   # llama-3.3-70b supports 32k output; 16k is safe
        for attempt_tokens in [max_tokens, _GROQ_HARD_CEILING]:
            payload = {
                "model":       model,
                "messages":    [{"role": "system", "content": system},
                                {"role": "user",   "content": user}],
                "max_tokens":  attempt_tokens,
                "temperature": 0.3,
            }
            for rate_attempt in range(2):
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        json=payload, headers=headers,
                    )
                if resp.status_code == 429 and rate_attempt == 0:
                    wait = int(resp.headers.get("Retry-After", "6"))
                    logger.warning("note_generator Groq 429 — retrying in %d s", wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                data   = resp.json()
                choice = data["choices"][0]
                if choice.get("finish_reason") == "length":
                    if attempt_tokens < _GROQ_HARD_CEILING:
                        logger.warning(
                            "note_generator Groq: output truncated at %d tokens — "
                            "retrying with hard ceiling %d", attempt_tokens, _GROQ_HARD_CEILING
                        )
                        break   # break inner rate-retry loop → outer loop increases tokens
                    else:
                        logger.warning(
                            "note_generator Groq: output still truncated at hard ceiling "
                            "%d tokens — returning partial result", _GROQ_HARD_CEILING
                        )
                return choice["message"]["content"].strip()
    except Exception as e:
        logger.warning("note_generator Groq async call failed: %s", e)
    return None


# ── Post-generation coverage audit ───────────────────────────────────────────────

_PATCH_SYSTEM = """\
You are AuraGraph — filling in missing concepts from a slide deck into an existing note section.
The main note was already written but some slide content was not covered.
Your ONLY job: write concise, accurate notes for each missing item listed below.
Follow the same proficiency level as the existing note. Use the same LaTeX conventions.
Do NOT repeat content already in the note. Do NOT add an ## heading. Do NOT add an Exam Tip.
Start immediately with ### sub-headings for each missing item. No preamble.
"""

_PATCH_USER = """\
TOPIC: {topic}
PROFICIENCY: {proficiency}

THE FOLLOWING ITEMS FROM THE SLIDES WERE NOT COVERED IN THE GENERATED NOTE:
{missing_block}

ORIGINAL SLIDE CONTENT (for context — only cover the MISSING items above):
{slide_snippet}

Write brief but complete notes for each missing item. Use display LaTeX for all formulas.
"""


def _coverage_check(key_points: list[str], generated_text: str) -> list[str]:
    """
    Return key_points whose content is not reflected in generated_text.

    Strategy: for each key_point, extract words of length >= 3 as "signal words"
    (lowered from 5 so domain terms like DFT, FFT, ROC, norm, pole, gain are
    captured). If fewer than 75% of signal words appear in the generated text,
    the concept is considered missing.

    The 75% threshold (raised from 50%) avoids false-negatives where the LLM
    paraphrased one word but skipped the rest of the concept.
    """
    gen_lower = generated_text.lower()
    missing: list[str] = []
    # ONLY true function words — never domain/engineering terms.
    # Previous list included "function", "value", "system", "signal" which are
    # the primary distinguishing words in engineering key_points ("transfer function",
    # "unit step signal", etc.) and caused them to have 0 signal words → always
    # treated as "covered" even when completely absent from the generated text.
    _STOP = {
        "which", "where", "there", "their", "these", "those",
        "given", "since", "using", "defined", "called",
        "with", "from", "that", "this", "have", "been",
        "when", "into", "each", "for", "the", "and", "are", "its", "not",
    }
    for kp in key_points:
        # Use words of length >= 3 so short domain terms (DFT, FFT, ROC, etc.)
        # are included as signal words.
        sig = [w for w in re.findall(r'[a-zA-Z]{3,}', kp.lower())
               if w not in _STOP]
        if not sig:
            continue
        found = sum(1 for w in sig if w in gen_lower)
        # 75% threshold: at least 3/4 signal words must appear
        if found < max(1, int(len(sig) * 0.75)):
            missing.append(kp)
    return missing


async def _patch_missing_coverage(
    topic_name:       str,
    slide_text:       str,
    missing_kps:      list[str],
    proficiency:      str,
    provider:         str,
    api_sem:          asyncio.Semaphore | None = None,
) -> str | None:
    """
    Generate a targeted supplement covering key_points that were missed in the
    first-pass note. Returns a Markdown fragment (no ## heading) to append.
    """
    if not missing_kps:
        return None
    missing_block = "\n".join(f"{i+1}. {kp}" for i, kp in enumerate(missing_kps))
    user = _safe_format(
        _PATCH_USER,
        topic=topic_name,
        proficiency=proficiency,
        missing_block=missing_block,
        slide_snippet=slide_text,   # pass FULL slide text — truncation caused missing formulas
    )
    budget = _budget_for_topic(" " * (len(missing_kps) * 200), provider, proficiency)
    async def _call():
        if provider == "azure":
            return await _call_azure(_PATCH_SYSTEM, user, max_tokens=budget)
        return await _call_groq(_PATCH_SYSTEM, user, max_tokens=budget)
    if api_sem:
        async with api_sem:
            return await _call()
    return await _call()


def _extract_slide_lines(slide_text: str) -> list[str]:
    """
    Extract every meaningful content line from raw slide_text as coverage obligations.
    This supplements key_points (which are LLM-extracted and may be incomplete).
    Skips slide boundary markers, trivially short lines, and administrative metadata
    lines (course codes, lecture headers, professor names) that are explicitly filtered
    from the generated notes by the prompts — including them would create phantom
    obligations that force the coverage-patch LLM to re-insert administrative text.
    """
    # Pre-compiled metadata patterns — mirror what the prompts filter out.
    _META_LINE = re.compile(
        r'^[A-Z]{2,6}-\d{3,4}[:\s]'           # course code: CSL-373:
        r'|^Lec(?:ture)?\s+\d+'                # Lecture 10 / Lec 10
        r'|^\d{2}/\d{2}/\d{4}'                 # date: 05/02/2026
        r'|^\d{1,2}\s*[-–]\s*\d{1,2}\s*(am|pm|AM|PM)'  # time: 2 - 3 PM
        r'|^(Dr|Prof|Professor|Department|Institute|IIT|NIT|BITS)\b',  # institution
        re.IGNORECASE,
    )
    lines = []
    seen: set[str] = set()
    for line in slide_text.split('\n'):
        stripped = line.strip()
        # Skip blank lines, boundary markers, very short lines, and metadata
        if not stripped or stripped.startswith('---') or len(stripped) < 10:
            continue
        # Skip [Figure: ...] annotations — these are image context injected for the
        # LLM to read, not content obligations that must appear verbatim in the notes.
        if stripped.startswith('[Figure:') or stripped.startswith('[Textbook Figure:'):
            continue
        if _META_LINE.match(stripped):
            continue
        norm = stripped.lower()
        if norm in seen:
            continue
        seen.add(norm)
        # Strip bullet markers for cleaner signal
        clean = stripped.lstrip('–-*•-> ').strip()
        if clean:
            lines.append(clean)
    return lines


async def _ensure_full_coverage(
    text:       str,
    provider:   str,
    topic,                           # SlideTopic
    proficiency: str,
    api_sem:    asyncio.Semaphore | None = None,
) -> tuple[str, str]:
    """
    Run coverage audit on *text*.

    Two-pass audit:
      Pass 1 — Check LLM-extracted key_points (semantic, concept-level)
      Pass 2 — Check raw slide_text lines (literal, line-level)

    Both passes use the same _coverage_check logic. Missing items from BOTH
    passes are merged and patched in a single LLM call to avoid redundant API calls.

    Always returns (final_text, provider).
    """
    # Build the combined checklist: key_points + raw slide lines.
    # Filter [Figure:] annotations — the LLM may include them in key_points if it
    # saw the annotation in slide_text, but they are image context, not academic
    # content obligations that must appear verbatim in the generated notes.
    all_obligations: list[str] = [
        kp for kp in (topic.key_points or [])
        if not kp.strip().startswith('[Figure:')
        and not kp.strip().startswith('[Textbook Figure:')
    ]

    # Add raw slide lines that are NOT already represented in key_points
    slide_lines = _extract_slide_lines(topic.slide_text)
    kp_lower = {kp.lower() for kp in all_obligations}
    for line in slide_lines:
        if line.lower() not in kp_lower:
            all_obligations.append(line)

    if not all_obligations:
        return text, provider

    missing = _coverage_check(all_obligations, text)
    if not missing:
        return text, provider

    logger.info(
        "coverage_check: '%s' — %d/%d obligations missing, patching: %s",
        topic.topic, len(missing), len(all_obligations), missing[:5],
    )
    patch = await _patch_missing_coverage(
        topic.topic, topic.slide_text, missing, proficiency, provider, api_sem
    )
    if patch and len(patch.strip()) > 30:
        return text.rstrip() + "\n\n" + patch.strip(), provider
    return text, provider


# ── Per-topic generation ───────────────────────────────────────────────────

def _budget_for_topic(slide_text: str, provider: str, proficiency: str = "Practitioner") -> int:
    """
    Return the token budget for a single topic LLM call.

    Single-user quality mode: always use the MAXIMUM available ceiling.
    No limits — give every topic the full output window.

    Hard ceilings:
      Azure GPT-4o  — 16,384 output tokens  (we use 16,000)
      Groq llama-3  — 32,768 output tokens  (we use 16,000)
    """
    # Always return the maximum — no per-proficiency throttling.
    # More tokens = longer, more thorough notes. Truncation is the enemy.
    if provider == "azure":
        return 16_000
    else:
        return 16_000


# ── Sub-chunk sizes (chars of slide_text per LLM call) ───────────────────────
# Single-user quality mode: use LARGER sub-chunks so that the final merge call
# receives fewer drafts and can include everything without truncation.
# With 16k output tokens available, even 6 000 chars (~1 500 tokens input)
# leaves a 10:1 expansion ratio — more than enough for Beginner (7×).
_SUBCHUNK_AZURE = 6_000   # ~1500 tokens input → 16k output budget = 10× headroom
_SUBCHUNK_GROQ  = 5_000   # Groq now has 16k output budget too

# Split threshold: topics shorter than this go through a SINGLE LLM call
# (no splitting needed). Only truly large topics need split→merge.
# 6 000 chars ≈ 1 500 input tokens — well within the 16k output ceiling.
_SPLIT_THRESHOLD = 6_000


def _split_slide_text(slide_text: str, chunk_size: int) -> list[str]:
    """
    Split slide_text at slide/page boundary markers so we never cut mid-slide.
    Falls back to splitting at blank lines if no markers exist.
    """
    # Try to split on explicit slide markers: "--- Slide N ---" or "=== PAGE N ==="
    marker_re = re.compile(r'(?=^(?:---|\s*={3,})\s*(?:Slide|Page)\s+\d+', re.MULTILINE | re.IGNORECASE)
    parts = marker_re.split(slide_text)
    if len(parts) <= 1:
        # No slide markers — split on double newlines (paragraph boundaries)
        parts = re.split(r'\n{2,}', slide_text)

    chunks: list[str] = []
    buf = ""
    for part in parts:
        if buf and len(buf) + len(part) > chunk_size:
            if buf.strip():
                chunks.append(buf.strip())
            buf = part
        else:
            buf = buf + ("\n\n" if buf else "") + part
    if buf.strip():
        chunks.append(buf.strip())

    return chunks if chunks else [slide_text]


# Sub-chunk generation prompt — focused: cover THIS chunk exhaustively, no intro/conclusion
_SUBCHUNK_SYSTEM = """\
You are AuraGraph — India's sharpest AI exam coach writing a PARTIAL DRAFT of study notes.
You are writing notes for ONE chunk of slides that is part of a larger topic.

YOUR ONLY JOB: Extract and explain EVERY piece of content in the slide chunk below.
Do NOT write an introduction, conclusion, exam tip, or mnemonic — those go in the final merge.
Do NOT skip anything — formulas, definitions, algorithms, properties, examples — all of it.

THE SLIDE TEXT IS YOUR CONTRACT — LINE BY LINE:
Every non-marker line (i.e., every line that is NOT "--- Slide N ---" or "--- Page N ---")
is a separate, mandatory coverage item. Read every such line. Cover every such line.
A concept present in the slide that is absent from your draft is always a failure,
no matter how minor it seems.

Laws you NEVER break:
- Every formula, definition, and algorithm from this chunk MUST appear.
- All math in LaTeX ($...$ inline, $$...$$ display). Never write "integral", "sigma" as English.
- If the source has OCR artifacts or garbled math, reconstruct the correct LaTeX.
- ^ is ALWAYS superscript (power/exponent). _ is ALWAYS subscript (index/element).
  Never swap them: $e^{j\\omega}$ NOT $e_{j\\omega}$; $z^{-1}$ NOT $z_{-1}$.
- Write in clear prose with ### sub-headings where the chunk has distinct sub-topics.
- No preamble ("Here are the notes..."). Start immediately with content.
"""

_SUBCHUNK_USER = """\
TOPIC (overall): {topic}
CHUNK NUMBER: {chunk_num} of {total_chunks}

SLIDE CONTENT FOR THIS CHUNK (every non-marker line is a MANDATORY ITEM):
{slide_text}

LINE-BY-LINE OBLIGATION:
METADATA FILTER (apply first — before covering any content):
The following types of lines are ADMINISTRATIVE METADATA, not teaching content.
They must NEVER appear in your output:
  • Course code headers: e.g. "CSL-373: PROBABILITY THEORY FOR COMPUTER ENGINEERS"
  • Lecture/session headers: e.g. "Lecture 10 (05/02/2026, 2 − 3 PM)" or "Lec 12 (...)"
  • Professor names, institution names, department names
  • Dates, room numbers, times
Treat these lines as invisible — they are NOT mandatory items.
For every remaining non-marker line:
  • formula line → the formula MUST appear in your notes
  • definition line → the definition MUST appear
  • property/condition line → it MUST appear
  • example/step line → it MUST appear
No exceptions. Never drop a line to add more depth to another.

PER-SLIDE SUB-SECTIONS (STRUCTURAL REQUIREMENT):
Count the --- Slide N --- / --- Page N --- markers above.
Each marker = one ### sub-heading in your output.
NEVER collapse multiple slides into one undivided block.

{textbook_instruction}

{proficiency_block}

Write exhaustive notes covering EVERY item in this chunk. Use ### sub-headings freely.
No introduction, no conclusion, no exam tip -- just thorough content coverage.
Output ONLY the notes content. Nothing else.
"""

# Merge prompt -- takes N sub-drafts and produces one polished ## section
_MERGE_SYSTEM = """\
You are AuraGraph -- assembling partial note drafts into ONE polished study notes section.

You will receive multiple DRAFT CHUNKS covering different slides for the same topic,
plus a PROFICIENCY BLOCK that defines exactly how to explain everything.

Your job: combine all drafts into one coherent ## section, following the proficiency instructions.

NON-NEGOTIABLE LAWS:
1. ZERO OMISSIONS -- every formula, definition, algorithm, property, condition,
   exception, and example from ALL drafts MUST appear in the output.
   Do not drop anything. Do not summarise away a concept.
2. NO DUPLICATION -- if the same concept appears in multiple drafts, merge it cleanly.
3. PROFICIENCY -- apply the proficiency instructions to determine HOW each concept
   is explained. Coverage is fixed; depth and style are what the proficiency controls.
4. STRUCTURE -- one ## section with ### sub-headings where needed.
   End with: > Exam Tip: [most-tested fact or most common mistake]
5. ALL MATH in LaTeX ($...$ inline, $$...$$ display). Never use English words for symbols.
6. Start immediately with ## [topic]. Nothing before it. Nothing after the Exam Tip.
"""

_MERGE_USER = """\
TOPIC: {topic}

{proficiency_block}

{student_context}
DRAFT CHUNKS ({n} total) -- combine these into one complete ## section:
{drafts_block}

TEXTBOOK CONTEXT (use to enrich explanations per the proficiency level above):
{textbook_context}

NON-NEGOTIABLE: Every formula, definition, algorithm, condition, exception, and example
from ALL draft chunks MUST appear in your output. Do not drop anything.

Output ONLY the complete ## {topic} section. Start with ## {topic}. End with the Exam Tip.
"""


async def _generate_subchunk(
    topic:       str,
    chunk_text:  str,
    chunk_num:   int,
    total:       int,
    textbook_instruction: str,
    proficiency: str,
    provider:    str,
    api_sem:     asyncio.Semaphore | None = None,
) -> str | None:
    """Generate notes for one sub-chunk of a topic's slides."""
    user = _safe_format(
        _SUBCHUNK_USER,
        topic=topic,
        chunk_num=str(chunk_num),
        total_chunks=str(total),
        slide_text=chunk_text,
        textbook_instruction=textbook_instruction,
        proficiency_block=_resolve_proficiency_block(proficiency),
    )
    tokens = _budget_for_topic(chunk_text, provider, proficiency)
    async def _call():
        if provider == "azure":
            return await _call_azure(_SUBCHUNK_SYSTEM, user, max_tokens=tokens)
        else:
            return await _call_groq(_SUBCHUNK_SYSTEM, user, max_tokens=tokens)
    if api_sem:
        async with api_sem:
            return await _call()
    return await _call()


async def _merge_drafts(
    topic:            str,
    drafts:           list[str],
    textbook_context: str,
    proficiency:      str,
    provider:         str,
    api_sem:          asyncio.Semaphore | None = None,
    student_context:  str = "",
) -> str | None:
    """Merge N sub-chunk drafts into one polished ## section."""
    drafts_block = "\n\n".join(
        f"=== DRAFT {i+1} ===\n{d}" for i, d in enumerate(drafts)
    )
    user = _safe_format(
        _MERGE_USER,
        topic=topic,
        student_context=student_context + "\n" if student_context else "",
        proficiency_block=_resolve_proficiency_block(proficiency),
        n=str(len(drafts)),
        drafts_block=drafts_block,
        textbook_context=textbook_context[:10_000] if textbook_context else "(none)",
    )
    total_draft_chars = sum(len(d) for d in drafts)
    tokens = _budget_for_topic(" " * total_draft_chars, provider, proficiency)
    system = _MERGE_SYSTEM.replace("{topic}", topic)
    async def _call():
        if provider == "azure":
            return await _call_azure(system, user, max_tokens=tokens)
        else:
            return await _call_groq(system, user, max_tokens=tokens)
    if api_sem:
        async with api_sem:
            return await _call()
    return await _call()


async def generate_topic_note(
    topic:            SlideTopic,
    textbook_context: str,
    proficiency:      str = "Practitioner",
    api_sem:          asyncio.Semaphore | None = None,
    student_context:  str = "",
) -> tuple[str, str]:
    """
    Generate one ## section for a single lecture topic.
    Returns (section_text, source) where source is 'azure' | 'groq' | 'local'.

    Architecture:
      - If slide_text <= _SPLIT_THRESHOLD: single LLM call (cheap, fast)
      - If slide_text > _SPLIT_THRESHOLD:
          1. Split slide_text into sub-chunks at slide boundaries
          2. Generate notes for each sub-chunk in parallel
          3. Merge all sub-chunk drafts into one polished section
        This guarantees EVERY slide's content appears in the final notes,
        regardless of how dense the topic is.
    """
    # Build the mandatory coverage checklist.
    # Filter out pure-noise key_points that are OCR artifacts (only digits/symbols,
    # very short fragments, or lines that are just whitespace noise). These items
    # can't be verified by the LLM and clutter the checklist with phantom obligations.
    # The full slide_text (primary source) still contains the correct content.
    def _is_meaningful_kp(kp: str) -> bool:
        kp = kp.strip()
        if len(kp) < 5:
            return False  # too short to be a real concept
        # pure math noise: all digits, spaces, operators, single letters
        if re.fullmatch(r'[\d\s\+\-\*\/\=\.\,\(\)\[\]\{\}i=nij\^]*', kp):
            return False
        return True

    clean_kps = [kp for kp in topic.key_points if _is_meaningful_kp(kp)]

    if clean_kps:
        key_points_block = (
            "NOTE: Some items below may be OCR-reconstructed. If a formula looks "
            "garbled, use your knowledge to interpret and correctly render it in LaTeX.\n"
            + "\n".join(f"{i+1}. {kp}" for i, kp in enumerate(clean_kps))
        )
    else:
        key_points_block = "(see slide content below — cover every formula, definition, algorithm, exercise, and example)"

    # ── Determine provider ────────────────────────────────────────────────────
    provider = "azure" if _azure_available() else ("groq" if _groq_available() else None)
    if provider is None:
        return _build_fallback_section(topic, textbook_context, proficiency), "local"

    chunk_size   = _SUBCHUNK_AZURE if provider == "azure" else _SUBCHUNK_GROQ
    tb_per_chunk = 5_000            if provider == "azure" else 3_500

    # Single-user quality mode: use _SPLIT_THRESHOLD universally across all proficiency
    # levels. The threshold is set aggressively low so virtually every topic goes through
    # the split→parallel→merge path, guaranteeing full coverage via smaller focused calls.

    # ── Short topic: single call path ────────────────────────────────────────
    if len(topic.slide_text) <= _SPLIT_THRESHOLD:
        tb_instr = _textbook_instruction_block(textbook_context, tb_per_chunk)
        user = _safe_format(
            _NOTE_USER_TEMPLATE,
            topic=topic.topic,
            key_points_block=key_points_block,
            slide_text=topic.slide_text,
            textbook_instruction=tb_instr,
            proficiency_block=_resolve_proficiency_block(proficiency),
        )
        tokens = _budget_for_topic(topic.slide_text, provider, proficiency)
        async def _single_call():
            if provider == "azure":
                return await _call_azure(_NOTE_SYSTEM, user, max_tokens=tokens)
            return await _call_groq(_NOTE_SYSTEM, user, max_tokens=tokens)
        if api_sem:
            async with api_sem:
                result = await _single_call()
        else:
            result = await _single_call()
        if result:
            result = _post_process_section(result, topic.topic)
            result = fix_latex_delimiters(_fix_tables(result))
            return await _ensure_full_coverage(result, provider, topic, proficiency, api_sem)
        return _build_fallback_section(topic, textbook_context, proficiency), "local"

    # ── Long topic: split → parallel generate → merge ────────────────────────
    sub_chunks = _split_slide_text(topic.slide_text, chunk_size)
    logger.info(
        "generate_topic_note: '%s' split into %d sub-chunks (%d chars total)",
        topic.topic, len(sub_chunks), len(topic.slide_text)
    )

    tb_instr_full  = _textbook_instruction_block(textbook_context, tb_per_chunk)
    tb_instr_brief = "TEXTBOOK CONTEXT: (provided to first chunk — focus on slide content here)"

    # Generate all sub-chunks concurrently (each call is throttled by api_sem)
    tasks = [
        _generate_subchunk(
            topic        = topic.topic,
            chunk_text   = chunk,
            chunk_num    = i + 1,
            total        = len(sub_chunks),
            textbook_instruction = tb_instr_full if i == 0 else tb_instr_brief,
            proficiency  = proficiency,
            provider     = provider,
            api_sem      = api_sem,
        )
        for i, chunk in enumerate(sub_chunks)
    ]
    drafts_raw = await asyncio.gather(*tasks)

    drafts = [d for d in drafts_raw if d and len(d.strip()) > 50]
    logger.info(
        "generate_topic_note: '%s' — %d/%d sub-chunks succeeded",
        topic.topic, len(drafts), len(sub_chunks)
    )

    if not drafts:
        logger.warning("generate_topic_note: all sub-chunks failed for '%s' — using fallback", topic.topic)
        return _build_fallback_section(topic, textbook_context, proficiency), "local"

    if len(drafts) == 1:
        result = _post_process_section(drafts[0], topic.topic)
        result = fix_latex_delimiters(_fix_tables(result))
        return await _ensure_full_coverage(result, provider, topic, proficiency, api_sem)

    # Merge all drafts into one polished section.
    # KEY INSIGHT: If total draft text is very large, the merge LLM call will
    # inevitably truncate/summarize because 16k output tokens ≈ 48k-64k chars.
    # When drafts are larger than what the merge can plausibly output, we
    # concatenate them directly (they're already in slide order and coherent).
    total_draft_chars = sum(len(d) for d in drafts)

    # Heuristic: 16k tokens ≈ ~48k chars of output. If drafts exceed this,
    # skip the merge — concatenation preserves more content than a truncating merge.
    _MERGE_OUTPUT_CHARS_LIMIT = 45_000

    if total_draft_chars > _MERGE_OUTPUT_CHARS_LIMIT:
        logger.info(
            "generate_topic_note: '%s' — %d draft chars > %d limit, skipping merge (concatenating drafts)",
            topic.topic, total_draft_chars, _MERGE_OUTPUT_CHARS_LIMIT,
        )
        combined = f"## {topic.topic}\n\n" + "\n\n".join(drafts)
        combined = _post_process_section(combined, topic.topic)
        combined = fix_latex_delimiters(_fix_tables(combined))
        return await _ensure_full_coverage(combined, provider, topic, proficiency, api_sem)

    # Acceptance rule: merged result must be at least 40% of total draft chars
    # (previously accepted anything > 100 chars, allowing the LLM to silently
    # summarize 15k chars of drafts into 200 chars and have it go undetected).
    merged = await _merge_drafts(topic.topic, drafts, textbook_context, proficiency, provider, api_sem=api_sem, student_context=student_context)
    if merged and len(merged.strip()) >= max(100, int(total_draft_chars * 0.40)):
        merged = _post_process_section(merged, topic.topic)
        merged = fix_latex_delimiters(_fix_tables(merged))
        return await _ensure_full_coverage(merged, provider, topic, proficiency, api_sem)

    # Merge failed or produced a suspiciously short result — concatenate drafts directly.
    if merged:
        logger.warning(
            "generate_topic_note: merge for '%s' shrank from %d → %d chars (<40%%) — concatenating drafts",
            topic.topic, total_draft_chars, len(merged),
        )
    else:
        logger.warning("generate_topic_note: merge failed for '%s' — concatenating drafts", topic.topic)
    combined = f"## {topic.topic}\n\n" + "\n\n".join(drafts)
    combined = _post_process_section(combined, topic.topic)
    combined = fix_latex_delimiters(_fix_tables(combined))
    return await _ensure_full_coverage(combined, provider, topic, proficiency, api_sem)


def _build_fallback_section(
    topic:            SlideTopic,
    textbook_context: str,
    proficiency:      str,
) -> str:
    """
    Build a note section without LLM.
    Preserves all slide content and inlines a snippet of textbook context.
    """
    from agents.local_summarizer import _build_section

    body = topic.slide_text
    # Strip slide/page boundary markers for the body
    body = re.sub(r'^---\s*(?:Slide|Page)\s+\d+[^\n]*---\s*\n?', '', body, flags=re.MULTILINE).strip()
    enrichment = textbook_context[:300] if textbook_context else ""

    section = _build_section(topic.topic, body, enrichment, 8, proficiency)
    if section:
        return fix_latex_delimiters(section)

    # Absolute fallback: just wrap slide text
    return fix_latex_delimiters(f"## {topic.topic}\n\n{body}\n\n> 📝 **Exam Tip:** Review the definition and key formula for {topic.topic}.")


# ── Merge + Refinement ─────────────────────────────────────────────────────

def merge_sections(sections: list[str]) -> str:
    """Concatenate all topic sections in order with clean spacing."""
    cleaned = []
    for s in sections:
        s = s.strip()
        if s:
            cleaned.append(s)
    return "\n\n".join(cleaned)


# ── Section-chunked LLM pass ─────────────────────────────────────────────────
# Used by both refine_notes and verify_notes so that large note sets
# (170k chars for 25 topics) are processed section-by-section instead of
# being silently truncated at 28 000 chars.

_CHUNK_BUDGET = 12_000
# 12 000 chars ≈ 3 000 tokens of input per batch.
# Azure GPT-4o has a 16 384 output-token ceiling.
# With ~300 tokens of prompt overhead, each batch uses ~3 300 input tokens,
# leaving ~13 000 tokens (~52 000 chars) for output — well above the 1×
# expansion needed for refinement/verification passes.
#
# The previous value (50 000 chars ≈ 12 500 input tokens) left only ~3 800
# output tokens (~15 000 chars) for a 50 000-char batch. The model truncated
# the output to ~25% of the input, which failed the 50% shrink guard and was
# discarded, making refinement and verification complete no-ops on any note
# set larger than ~15 000 chars. That is exactly what the logs showed:
#   29 610-char notes → 7 555-char output → rejected → original kept.


def _split_into_section_batches(notes: str, budget: int = _CHUNK_BUDGET) -> list[str]:
    """Split notes on '## ' headings and group sections into budget-sized batches."""
    sections = re.split(r'(?m)(?=^## )', notes)
    batches, buf = [], ""
    for sec in sections:
        if buf and len(buf) + len(sec) > budget:
            batches.append(buf)
            buf = sec
        else:
            buf += sec
    if buf:
        batches.append(buf)
    return batches or [notes]


def _sections_ok(result: str, batch: str, batch_section_count: int, label: str, batch_num: int, total_batches: int) -> bool:
    """
    Validate that an LLM result for a batch is acceptable:
    - not shorter than 50% of the original batch  (was 30% — too permissive)
    - contains at least as many ## headings as the original batch
    - contains at least 75% as many ### sub-headings as the original batch
      (catches silent subsection drops that the ## check misses)
    """
    if len(result) < len(batch) * 0.50:
        logger.warning(
            "%s batch %d/%d: result (%d chars) is less than 50%% of original (%d chars) — keeping original",
            label, batch_num, total_batches, len(result), len(batch),
        )
        return False
    if batch_section_count > 0:
        result_sections = len(re.findall(r'^## ', result, re.MULTILINE))
        if result_sections < batch_section_count:
            logger.warning(
                "%s batch %d/%d: LLM dropped %d/%d ## sections — keeping original",
                label, batch_num, total_batches,
                batch_section_count - result_sections, batch_section_count,
            )
            return False
    # Also guard against subsection (###) drops — a sign the LLM compressed content.
    batch_subsections = len(re.findall(r'^### ', batch, re.MULTILINE))
    if batch_subsections >= 3:   # only enforce when there are enough to be meaningful
        result_subsections = len(re.findall(r'^### ', result, re.MULTILINE))
        if result_subsections < int(batch_subsections * 0.75):
            logger.warning(
                "%s batch %d/%d: LLM dropped too many ### sub-sections (%d → %d, need ≥ %d) — keeping original",
                label, batch_num, total_batches,
                batch_subsections, result_subsections, int(batch_subsections * 0.75),
            )
            return False
    return True


async def _apply_llm_in_chunks(
    notes:  str,
    system: str,
    user_template: str,
    min_len: int = 500,
    label:  str = "pass",
) -> str:
    """
    Run an LLM pass (refinement or verification) section-by-section so that
    no content is dropped when notes exceed the 28 k char prompt budget.
    Azure is preferred; Groq is used only for batches ≤ 12 k chars.
    Returns the original notes if all batches fail.
    """
    if len(notes) < min_len:
        return notes

    batches = _split_into_section_batches(notes)
    logger.info("%s: %d chars → %d batch(es)", label, len(notes), len(batches))

    refined_batches: list[str] = []
    changed = False

    for i, batch in enumerate(batches):
        user = _safe_format(user_template, notes=batch)
        result: str | None = None
        batch_section_count = len(re.findall(r'^## ', batch, re.MULTILINE))

        if _azure_available():
            result = await _call_azure(system, user, max_tokens=16000)
            if result and not _sections_ok(result, batch, batch_section_count, label, i+1, len(batches)):
                logger.info("%s batch %d/%d: Azure output rejected — keeping original", label, i+1, len(batches))
                result = None

        if result is None and _groq_available() and len(batch) <= 12_000:
            result = await _call_groq(system, user, max_tokens=16000)
            if result and not _sections_ok(result, batch, batch_section_count, label, i+1, len(batches)):
                logger.info("%s batch %d/%d: Groq output rejected — keeping original", label, i+1, len(batches))
                result = None

        if result:
            refined_batches.append(fix_latex_delimiters(_fix_tables(result)))
            changed = True
        else:
            refined_batches.append(batch)  # keep original batch on failure

    if not changed:
        logger.info("%s: all batches failed — keeping original %d-char notes", label, len(notes))
        return notes

    return "\n\n".join(refined_batches)


async def refine_notes(notes: str) -> str:
    """
    Single refinement pass to improve clarity (Step 8).
    Processes notes section-by-section to avoid truncating large note sets.
    Returns original notes on failure.
    """
    return await _apply_llm_in_chunks(
        notes, _REFINEMENT_SYSTEM, _REFINEMENT_USER, min_len=500, label="refinement"
    )


# ── Post-generation fact-verification pass ────────────────────────────────────

async def verify_notes(notes: str) -> str:
    """
    Step 9 — Self-verification pass.

    Processes notes section-by-section (see _apply_llm_in_chunks) so that
    the full note set is fact-checked even for large (170k char) outputs.
    Returns original notes untouched on any failure.
    """
    return await _apply_llm_in_chunks(
        notes, _VERIFY_NOTES_SYSTEM, _VERIFY_NOTES_USER, min_len=500, label="verification"
    )


# ── Full pipeline orchestration ────────────────────────────────────────────

async def run_generation_pipeline(
    topics:           list[SlideTopic],
    topic_contexts:   dict[str, str],   # topic_name → textbook context string
    proficiency:      str = "Practitioner",
    refine:           bool = True,
    student_context:  str = "",         # personalisation profile from behaviour_store
) -> tuple[str, str]:
    """
    Run Step 6 (N topic calls) + Step 7 (merge) + Step 8 (refinement).

    Topic notes are generated CONCURRENTLY (up to 4 at a time) to avoid
    making the student wait 30-50 seconds for a sequential loop.

    Returns:
        Tuple of (merged_notes, source) where source is
        'azure' | 'groq' | 'local'.
    """
    if not topics:
        return "", "local"

    # Filter out metadata/cover topics that have NO real teaching content (slide_text is empty or near-empty)
    # Only skip topics where the topic name is a metadata keyword AND the slide has no usable content.
    # Do NOT skip topics just because their name contains "overview" or "introduction" — those may have content.
    _HARD_SKIP_RE = re.compile(
        r'^(table of contents|references|bibliography|acknowledgement|acknowledgements|'
        r'thank you|q&a|title page|cover page|about this course)$',
        re.I,
    )
    def _should_skip(t: SlideTopic) -> bool:
        # Always skip hard metadata
        if _HARD_SKIP_RE.match(t.topic.strip()):
            return True
        # Skip if topic name is a metadata keyword AND slide has no real content (< 60 chars)
        _SOFT_SKIP = re.compile(r'\b(agenda|outline|questions|learning objectives|lecture overview|course overview|course introduction)\b', re.I)
        if _SOFT_SKIP.search(t.topic) and len(t.slide_text.strip()) < 60:
            return True
        return False

    topics = [t for t in topics if not _should_skip(t)]
    if not topics:
        return "", "local"

    # Single-user quality mode: high concurrency — all topics generate in parallel.
    # For one user there is no rate-sharing concern, so we can fire all topic calls
    # simultaneously. Set LLM_CONCURRENCY env var to limit if needed.
    _concurrency = int(os.environ.get("LLM_CONCURRENCY", "20"))
    _api_sem = asyncio.Semaphore(_concurrency)

    async def _generate_with_sem(topic: SlideTopic) -> tuple[str, str]:
        context = topic_contexts.get(topic.topic, "")
        logger.info("Generating note for topic: %s", topic.topic)
        return await generate_topic_note(topic, context, proficiency, api_sem=_api_sem, student_context=student_context)

    # Generate all topics concurrently
    results = await asyncio.gather(*[_generate_with_sem(t) for t in topics])
    sections     = [r[0] for r in results]
    topic_sources = [r[1] for r in results]

    merged = merge_sections(sections)

    # Determine source from what was actually used across all topic calls
    if "azure" in topic_sources:
        source = "azure"
    elif "groq" in topic_sources:
        source = "groq"
    else:
        source = "local"

    # Refinement pass: always run for single-user quality mode.
    # The 80k-char skip limit is removed — one user can wait for a polished result.
    if refine and (_azure_available() or _groq_available()):
        logger.info("Running refinement pass on %d chars (source=%s)", len(merged), source)
        merged = await refine_notes(merged)

    # Verification pass: fact-checks formulas, definitions, and claims.
    # Run always -- correctness is non-negotiable regardless of output size.
    if _azure_available() or _groq_available():
        logger.info("Running verification pass on %d chars", len(merged))
        merged = await verify_notes(merged)

    return merged, source


async def run_generation_pipeline_stream(
    topics:         list[SlideTopic],
    topic_contexts: dict[str, str],
    proficiency:    str = "Practitioner",
    student_context: str = "",
):
    """
    Streaming variant of run_generation_pipeline.

    Async generator that yields SSE-ready dicts as each topic finishes:
      {"type": "start",   "total": <N>}
      {"type": "section", "topic": <str>, "content": <str>, "index": <int>}
      ...
      {"type": "done",    "note": <full_merged_str>, "source": <str>}

    Topics are generated concurrently (respects LLM_CONCURRENCY).
    The final "done" event contains the merged + refined + verified note.
    """
    _HARD_SKIP_RE = re.compile(
        r'^(table of contents|references|bibliography|acknowledgement|acknowledgements|'
        r'thank you|q&a|title page|cover page|about this course)$',
        re.I,
    )
    def _should_skip(t: SlideTopic) -> bool:
        if _HARD_SKIP_RE.match(t.topic.strip()):
            return True
        _SOFT_SKIP = re.compile(r'\b(agenda|outline|questions|learning objectives|lecture overview|course overview|course introduction)\b', re.I)
        if _SOFT_SKIP.search(t.topic) and len(t.slide_text.strip()) < 60:
            return True
        return False

    filtered = [t for t in topics if not _should_skip(t)]
    if not filtered:
        yield {"type": "done", "note": "", "source": "local"}
        return

    yield {"type": "start", "total": len(filtered)}

    _concurrency = int(os.environ.get("LLM_CONCURRENCY", "20"))
    api_sem = asyncio.Semaphore(_concurrency)

    async def _wrapped(t: SlideTopic, idx: int):
        ctx = topic_contexts.get(t.topic, "")
        section, src = await generate_topic_note(t, ctx, proficiency, api_sem=api_sem)
        return idx, t.topic, section, src

    # Launch all tasks; use asyncio.Queue to yield results as they arrive
    queue: asyncio.Queue = asyncio.Queue()

    async def _run_task(t, idx):
        result = await _wrapped(t, idx)
        await queue.put(result)

    tasks = [asyncio.create_task(_run_task(t, i)) for i, t in enumerate(filtered)]

    ordered_sections: list[str | None] = [None] * len(filtered)
    last_source = "local"

    # Emit sections in LECTURE ORDER, not completion order.
    # When topic at index i finishes, hold it in ordered_sections[i].
    # Then flush any contiguous run from the front (next_emit pointer).
    # This way the user always sees topics in the correct slide order,
    # even though they are generated in parallel.
    next_emit = 0  # next index that should be emitted

    for _ in range(len(filtered)):
        idx, topic_name, section, src = await queue.get()
        ordered_sections[idx] = section
        if src != "local":
            last_source = src

        # Flush any contiguous ready sections from next_emit forward
        while next_emit < len(filtered) and ordered_sections[next_emit] is not None:
            emit_topic = filtered[next_emit].topic
            emit_section = ordered_sections[next_emit]
            yield {"type": "section", "topic": emit_topic, "content": emit_section, "index": next_emit}
            next_emit += 1

    # Flush any remaining (should be empty after the loop, but be safe)
    while next_emit < len(filtered) and ordered_sections[next_emit] is not None:
        emit_topic = filtered[next_emit].topic
        emit_section = ordered_sections[next_emit]
        yield {"type": "section", "topic": emit_topic, "content": emit_section, "index": next_emit}
        next_emit += 1

    await asyncio.gather(*tasks, return_exceptions=True)  # ensure all done

    # Merge in original topic order
    merged = merge_sections(ordered_sections)

    # Refinement pass — emit heartbeats every 8 s so the frontend stall-detector
    # never fires while the LLM is working silently.
    if _azure_available() or _groq_available():
        yield {"type": "status", "message": "Refining notes for depth and clarity…"}
        try:
            _refine_task = asyncio.create_task(refine_notes(merged))
            while not _refine_task.done():
                await asyncio.sleep(8)
                if not _refine_task.done():
                    yield {"type": "heartbeat"}
            refined = _refine_task.result()   # .result() re-raises if task raised
            if refined and len(refined.strip()) > 100:
                merged = refined
        except Exception as e:
            logger.warning("Stream refinement pass failed (keeping original): %s", e)

    # Verification pass
    if _azure_available() or _groq_available():
        yield {"type": "status", "message": "Verifying all formulas and definitions…"}
        try:
            _verify_task = asyncio.create_task(verify_notes(merged))
            while not _verify_task.done():
                await asyncio.sleep(8)
                if not _verify_task.done():
                    yield {"type": "heartbeat"}
            verified = _verify_task.result()
            if verified and len(verified.strip()) > 100:
                merged = verified
        except Exception as e:
            logger.warning("Stream verification pass failed (keeping original): %s", e)

    yield {"type": "done", "note": merged, "source": last_source}
