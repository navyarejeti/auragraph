"""
agents/prompts.py  — AuraGraph Prompt Registry

Every LLM prompt used in the system is registered here with:
  • name          — unique identifier
  • description   — what it does, when to use it
  • template      — raw SK-compatible template string
  • required_vars — list of {{$var}} names the template expects
  • output_format — what the model is expected to return

Validation: call validate_vars(name, provided_dict) before every LLM call
to get a list of missing vars. An empty list means you're good to go.

Usage example:
    from agents.prompts import registry, validate_vars

    missing = validate_vars("doubt_answer", {"doubt": q, "note_page": p, ...})
    if missing:
        raise ValueError(f"Missing prompt vars: {missing}")
"""

from __future__ import annotations
from dataclasses import dataclass, field


# ── Data structure ─────────────────────────────────────────────────────────────

@dataclass
class PromptSpec:
    name:          str
    description:   str
    template:      str
    required_vars: list[str]
    output_format: str
    # optional extras — informational only
    tags: list[str] = field(default_factory=list)


def validate_vars(prompt_name: str, provided: dict) -> list[str]:
    """
    Return a list of required variable names that are missing from *provided*.
    An empty return value means the call is safe to proceed.
    Raises KeyError if *prompt_name* is not in the registry.
    """
    spec = registry[prompt_name]
    return [v for v in spec.required_vars if v not in provided]


# ── Prompt templates ───────────────────────────────────────────────────────────

_DOUBT_ANSWER = r"""\
You are AuraGraph, an expert academic tutor for university students.
A student has a question. Answer it clearly, completely, and accurately.

════════════════════════════════════════════════════════
STUDENT'S QUESTION:
{{$doubt}}

════════════════════════════════════════════════════════
CONTEXT — STUDY NOTES (may be empty if not yet generated):
{{$note_page}}

════════════════════════════════════════════════════════
CONTEXT — LECTURE SLIDES:
{{$slide_context}}

════════════════════════════════════════════════════════
CONTEXT — TEXTBOOK:
{{$textbook_context}}

════════════════════════════════════════════════════════
INSTRUCTIONS:
1. Answer the student's question directly and fully, regardless of whether
   context is provided. If context is available, use it to personalise the
   answer to what they are studying — but NEVER refuse to answer just because
   a field is empty.
2. Structure your answer:
   a. One-sentence direct answer.
   b. Detailed explanation (2–4 paragraphs). Include key formulas in LaTeX.
   c. A concrete example or analogy that makes the concept click.
   d. Optionally one exam tip at the very end:
      > 📝 **Exam Tip:** …
3. RESPONSIBLE AI — SOURCE QUALITY RULE:
   The study notes and slide context may have been generated from blurry images
   or imperfect OCR. If you notice incorrect or garbled terminology in the context,
   silently use the correct term in your answer — NEVER write phrases like
   "⚠️ Note correction:", "the notes contain an error", "the correct spelling is",
   or any language that draws the student's attention to source defects.
   Simply answer with correct information. Students trust AuraGraph's output.

FORMATTING:
- Inline math: $...$
- Display math (own line): $$\n...\n$$
- NEVER use \( \) or \[ \]
- No preamble like "Great question!" — start immediately with the answer.

OUTPUT FORMAT — two sections split by |||VERIFY|||:

<Full answer to the student's question>
|||VERIFY|||
correct
"""

_MUTATION = r"""\
You are AuraGraph's Adaptive Mutation Agent.
A student is confused about a specific concept in their study note.

---
ORIGINAL NOTE SECTION:
{{$original_paragraph}}

STUDENT'S DOUBT:
{{$student_doubt}}

---
TASK:
1. Diagnose the student's conceptual gap in one clear sentence.
2. Rewrite the ORIGINAL NOTE SECTION so it directly resolves the doubt.
   - Add an intuition block (💡) explaining WHY it works using an analogy or
     concrete example.
   - Keep all original formulas. Use ONLY `$...$` for inline math and `$$` on
     its own line for display math. NEVER use \( \) or \[ \] delimiters.
   - Preserve the Markdown heading if present.
   - Add a `> 📝 **Exam Tip:**` if the doubt reveals a commonly tested
     misconception.
3. Output exactly THREE sections separated by `|||`:

<Fully rewritten section>
|||
<One sentence: the diagnosed conceptual gap>
|||
<Direct answer to the student's doubt (2–4 sentences, plain language)>

Do NOT write labels. Just the three sections separated by |||.
"""

_NOTE_SELF_REVIEW = r"""\
You are an expert academic editor reviewing AI-generated study notes.
Your job is to catch factual errors, wrong formulas, wrong signs, and
misleading explanations — then output a corrected version.

════════════════════════════════════════════════════════
STUDY NOTE TO REVIEW:
{{$note}}

════════════════════════════════════════════════════════
SOURCE SLIDES (professor's material):
{{$slide_context}}

════════════════════════════════════════════════════════
SOURCE TEXTBOOK (authoritative reference):
{{$textbook_context}}

════════════════════════════════════════════════════════
REVIEW PROCESS:
1. Cross-check every formula, definition, and claim against the source
   material and your own expert knowledge.
2. Fix any factual errors, wrong signs, or misleading descriptions.
3. Do NOT change correct content, and do NOT change the Markdown structure
   or section headings.
4. Preserve all LaTeX delimiters ($...$ and $$...$$).

OUTPUT — exactly one of these two formats:

If the note is accurate:
PASS|||<original note verbatim>

If you made corrections:
CORRECTED: <one-sentence summary of what you fixed>|||<corrected note>
"""

_VERIFICATION = r"""\
════════════════════════════════════════════════════════════════════════
STUDENT'S QUESTION:
{{$doubt}}

════════════════════════════════════════════════════════════════════════
RELEVANT NOTE PAGE (AI-generated — may contain errors):
{{$note_page}}

════════════════════════════════════════════════════════════════════════
LECTURE SLIDE CONTENT (professor's material — may have OCR noise):
{{$slide_context}}

════════════════════════════════════════════════════════════════════════
TEXTBOOK CONTENT (authoritative reference):
{{$textbook_context}}

════════════════════════════════════════════════════════════════════════
VERIFICATION PROCESS — follow every step:

STEP 1 — UNDERSTAND THE QUESTION
  • Identify the exact concept the student is asking about.

STEP 2 — CROSS-VERIFY the note's claim against:
  a) Slide content b) Textbook content c) Your own knowledge

STEP 3 — CLASSIFY the note's accuracy:
  • correct / partially_correct / incorrect

STEP 4 — RESPOND using EXACT separator tokens:

<Full explanation answering the student's question (2–4 paragraphs)>
|||VERIFY|||
<exactly one of: correct / partially_correct / incorrect>
|||CORRECT|||
<If NOT correct: provide the accurate explanation with correct terminology.
 Do NOT write "The notes contain an error" or similar — just state the correct information.
 If correct: NONE>
|||NOTE|||
<Optional one-sentence clarification or NONE>

FORMATTING: Inline math $...$  Display math $$\n...\n$$  NEVER use \( \)
"""

_EXAMINER = r"""\
You are an expert university exam setter for {{$subject}}.
Generate exam-quality practice questions for a student studying:

CONCEPT: {{$concept_name}}
DIFFICULTY LEVEL: {{$level}}
{{$custom_instruction}}

Generate 3 multiple-choice questions plus 1 short-answer problem.
Each MCQ must have:
  - stem: the question body
  - options A, B, C, D
  - correct: the correct option letter
  - explanation: 1–2 sentence explanation of why the answer is correct

Output as valid JSON array:
[
  {
    "type": "mcq",
    "concept": "<concept tag>",
    "question": "<question stem>",
    "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
    "correct": "A",
    "explanation": "..."
  },
  ...
]

After the JSON array, add the short-answer problem with a separator:
---SHORT-ANSWER---
<question>
---ANSWER---
<model answer>
"""


# ── Registry ───────────────────────────────────────────────────────────────────

registry: dict[str, PromptSpec] = {

    "doubt_answer": PromptSpec(
        name="doubt_answer",
        description=(
            "Tutor mode: answer any student question directly. Works even when "
            "note_page is empty. Used by /api/doubt."
        ),
        template=_DOUBT_ANSWER,
        required_vars=["doubt", "note_page", "slide_context", "textbook_context"],
        output_format="<answer>|||VERIFY|||correct",
        tags=["doubt", "tutor", "student-facing"],
    ),

    "mutation": PromptSpec(
        name="mutation",
        description=(
            "Rewrite a note section to resolve a student's confusion. "
            "Returns 3 sections: rewritten note | gap diagnosis | direct answer."
        ),
        template=_MUTATION,
        required_vars=["original_paragraph", "student_doubt"],
        output_format="<rewrite>|||<gap>|||<answer>",
        tags=["mutation", "note-editing"],
    ),

    "note_self_review": PromptSpec(
        name="note_self_review",
        description=(
            "Post-generation accuracy sweep. Cross-checks the AI note against "
            "source slides and textbook. Used after /api/fuse before serving to student."
        ),
        template=_NOTE_SELF_REVIEW,
        required_vars=["note", "slide_context", "textbook_context"],
        output_format="PASS|||<note>  OR  CORRECTED: <summary>|||<corrected note>",
        tags=["verification", "accuracy", "post-generation"],
    ),

    "verification": PromptSpec(
        name="verification",
        description=(
            "Legacy: verify a note page claim AND answer the student's question. "
            "Requires non-empty note_page to make sense. Prefer 'doubt_answer' "
            "when the note page may be empty."
        ),
        template=_VERIFICATION,
        required_vars=["doubt", "note_page", "slide_context", "textbook_context"],
        output_format="<answer>|||VERIFY|||<status>|||CORRECT|||<correction>|||NOTE|||<footnote>",
        tags=["verification", "legacy"],
    ),

    "examiner": PromptSpec(
        name="examiner",
        description=(
            "Generate practice MCQ + short-answer questions for a concept at a "
            "given difficulty level."
        ),
        template=_EXAMINER,
        required_vars=["concept_name", "subject", "level"],
        output_format="JSON array + ---SHORT-ANSWER--- section",
        tags=["practice", "exam", "student-facing"],
    ),
}
