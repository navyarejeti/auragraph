"""
agents/verifier_agent.py

Two pipelines:
  1. DOUBT_ANSWER_PROMPT — tutor the student directly (used by /api/doubt).
  2. VERIFICATION_PROMPT — cross-verify a note page claim (legacy, kept for reference).
  3. NOTE_SELF_REVIEW_PROMPT — post-generation accuracy sweep (used after /api/fuse).
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field


# ── Structured result ─────────────────────────────────────────────────────────

@dataclass
class VerificationResult:
    answer:              str = ""          # direct answer to the student
    verification_status: str = "correct"  # correct | partially_correct | incorrect
    correction:          str = ""          # filled only when status != correct
    footnote:            str = ""          # optional short clarification


# ── Primary doubt-answering prompt (tutor mode) ───────────────────────────────

DOUBT_ANSWER_PROMPT = r"""\
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

{{$student_context}}
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

Do not include |||CORRECT||| or |||NOTE||| sections unless the notes
contain a genuine factual error — in that case append:
|||CORRECT|||
The notes contain an error. <corrected explanation>
|||NOTE|||
NONE
"""

# ── Legacy verification prompt (kept for parse_verification_response) ─────────
VERIFICATION_PROMPT = r"""\
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
  • Identify which claim in the note page this question relates to.

STEP 2 — CROSS-VERIFY the note's claim against:
  a) Slide content (treat as a rough guide; OCR may be imperfect).
  b) Textbook content (treat as more reliable than slides).
  c) Your own knowledge (treat as ground truth for established theory).
  If slide content contradicts the textbook or your knowledge, trust the
  textbook and your knowledge over the slides.

STEP 3 — CLASSIFY the note's accuracy:
  • correct          — the note's explanation is fully accurate.
  • partially_correct — the note is mostly right but has a gap or
                        imprecise wording that could mislead.
  • incorrect        — the note contains a factual error (wrong formula,
                       wrong sign, wrong operation, wrong definition, etc.)

STEP 4 — DETERMINE YOUR RESPONSE STRATEGY:

  Case: correct
    Answer the question clearly and confirm the notes.

  Case: partially_correct
    Answer the question, noting which part is right and what needs
    clarification.

  Case: incorrect
    Give the fully corrected explanation with the right formula /
    definition / statement. Do NOT write "The notes contain an error" or
    similar phrases — simply state the correct information directly.
    Students trust AuraGraph's output; exposing source errors undermines that trust.

STEP 5 — HANDLE SLIDE OCR NOISE
  If slide text looks truncated, garbled, or contradicts basic theory:
  • Do not use it as the primary source.
  • Fall back to textbook context and your own knowledge.
  • Infer the intended concept from context.

STEP 6 — FORMAT YOUR RESPONSE

Use the EXACT separator tokens below (no extra spaces or punctuation):

<Write a FULL, DIRECT explanation answering the student's question. This
 MUST contain at minimum 2-4 paragraphs of real explanation — never reduce
 this to a single tip line. Structure as follows:
   1. One-sentence direct answer to the question.
   2. Detailed explanation with any relevant formulas in display LaTeX.
   3. A concrete example that illustrates the concept.
   OPTIONAL: If the question touches a commonly tested misconception ONLY,
   you MAY add ONE exam tip line at the very end using this exact format:
     > 📝 **Exam Tip:** …
   CRITICAL: DO NOT make the Exam Tip the entire answer. The exam tip is
   a brief addendum, NOT a substitute for the explanation above.>
|||VERIFY|||
<One word only — exactly one of: correct / partially_correct / incorrect>
|||CORRECT|||
<If status is NOT correct: start with "The notes contain an error." then
 give the full corrected explanation with correct formulas or definitions.
 If status IS correct: write the single word NONE>
|||NOTE|||
<Optional one-sentence clarification visible to the student, or NONE>

FORMATTING RULES:
- Inline math: $...$
- Display math: $$\n...\n$$  (on its own line)
- NEVER use \( \) or \[ \]
- No preamble like "Great question!" or "Sure!"
"""


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_verification_response(text: str) -> VerificationResult:
    """
    Split on |||VERIFY||| / |||CORRECT||| / |||NOTE|||.
    Falls back gracefully if the LLM drifts from the format.
    """
    result = VerificationResult()

    # --- Strategy 1: exact separator tokens ------------------------------------
    parts = re.split(r'\|\|\|VERIFY\|\|\|', text, maxsplit=1)
    if len(parts) == 2:
        raw_answer = parts[0].strip()
        # Strip leaked prompt instruction block e.g. "<Direct answer to ...>\n\n actual answer"
        if raw_answer.startswith('<'):
            gt_nl = raw_answer.find('>\n')
            if gt_nl != -1:
                raw_answer = raw_answer[gt_nl + 2:].lstrip()
        result.answer = raw_answer
        remainder     = parts[1]

        correct_split = re.split(r'\|\|\|CORRECT\|\|\|', remainder, maxsplit=1)
        raw_status    = correct_split[0].strip().lower()
        result.verification_status = _normalise_status(raw_status)

        if len(correct_split) == 2:
            note_split     = re.split(r'\|\|\|NOTE\|\|\|', correct_split[1], maxsplit=1)
            raw_correction = note_split[0].strip()
            result.correction = "" if raw_correction.upper() == "NONE" else raw_correction

            if len(note_split) == 2:
                raw_note      = note_split[1].strip()
                result.footnote = "" if raw_note.upper() == "NONE" else raw_note

        return result

    # --- Strategy 2: look for embedded labels ----------------------------------
    status_m = re.search(
        r'(?:Verification\s+(?:Result|Status)|STATUS)[:\s]+'
        r'(correct|partially[_\s]correct|incorrect)',
        text, re.IGNORECASE,
    )
    correction_m = re.search(
        r'(?:Correction|Corrected\s+Explanation)[:\s]+([\s\S]+?)(?=\n(?:Notes?|NOTE|$)|$)',
        text, re.IGNORECASE,
    )
    answer_m = re.search(
        r'(?:Answer)[:\s]+([\s\S]+?)(?=\n(?:Verification|STATUS|$)|$)',
        text, re.IGNORECASE,
    )
    if answer_m:
        result.answer = answer_m.group(1).strip()
    else:
        result.answer = text.strip()   # best-effort: entire text

    if status_m:
        result.verification_status = _normalise_status(status_m.group(1))
    if correction_m:
        raw = correction_m.group(1).strip()
        result.correction = "" if raw.upper() == "NONE" else raw

    return result


def _normalise_status(raw: str) -> str:
    raw = raw.replace(" ", "_").lower().strip(".:; ")
    if "incorrect" in raw:
        return "incorrect"
    if "partial" in raw:
        return "partially_correct"
    return "correct"


# ── Post-generation self-review ───────────────────────────────────────────────

NOTE_SELF_REVIEW_PROMPT = r"""\
You are AuraGraph's Accuracy Checker. A study note was auto-generated from lecture slides and a textbook.
Your ONLY job is to catch factual and mathematical errors BEFORE the student sees it.

════════════════════════════════════════════════════════════════
GENERATED NOTE (review this — may contain errors):
{{$note}}

════════════════════════════════════════════════════════════════
LECTURE SLIDES (course source of truth):
{{$slide_context}}

════════════════════════════════════════════════════════════════
TEXTBOOK (authoritative reference):
{{$textbook_context}}

════════════════════════════════════════════════════════════════
REVIEW CHECKLIST — verify each item against sources and your own knowledge:
  □ Every formula is mathematically correct (signs, operations, variables, limits).
  □ Every definition matches standard academic usage.
  □ No factual statement contradicts the source material.
  □ LaTeX uses $...$ inline and $$...$$ display — never \( \) or \[ \].

OUTPUT FORMAT — choose exactly one form and output NOTHING else:

If NO errors were found:
PASS|||<the original note, completely unchanged — copy it verbatim>

If errors were corrected:
CORRECTED: <one sentence listing what was fixed, e.g. "Fixed sign in DTFT formula; corrected Parseval's theorem statement">|||<the full corrected note — only the erroneous lines changed, everything else identical>

RULES:
  • Do NOT rewrite correct content. Only fix genuine errors.
  • Do NOT add, remove, or reorder sections.
  • Do NOT change headings, bullet points, or callout blocks unless they contain an error.
  • When uncertain, leave as-is and output PASS.
"""


def parse_self_review_response(text: str) -> tuple[str, bool, str]:
    """
    Parse the NOTE_SELF_REVIEW_PROMPT output.
    Returns (verified_note, was_corrected, correction_summary).
    """
    def _strip_leaked_preface(s: str) -> str:
      # Defensive cleanup: some models prepend a natural-language PASS preface
      # before the unchanged note. This must never reach student notes.
      cleaned = re.sub(
        r'^\s*The notes are factually accurate,? and no corrections are needed\.?\s*'
        r'(?:Here is (?:the )?content unchanged:?\s*)?(?:\n\s*---\s*\n?)?',
        '',
        s,
        flags=re.IGNORECASE,
      )
      return cleaned.lstrip()

    text = text.strip()
    parts = text.split("|||", 1)
    if len(parts) < 2:
        # Malformed — return original text as-is
      return _strip_leaked_preface(text), False, ""
    header = parts[0].strip()
    note   = _strip_leaked_preface(parts[1].strip())
    if not note:
        return text, False, ""
    if header.upper().startswith("PASS"):
        return note, False, ""
    if header.upper().startswith("CORRECTED"):
        summary = header[len("CORRECTED"):].lstrip(": ").strip()
        return note, True, summary
    # Unknown prefix — treat as pass
    return note, False, ""
