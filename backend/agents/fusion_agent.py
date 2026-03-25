"""
agents/fusion_agent.py  — Semantic Kernel 1.x compatible
Knowledge Fusion Engine: generates notes from stored slide + textbook chunks.

v3 Changes vs v2
────────────────
• Takes pre-retrieved relevant chunks (not raw full-text) — GPT sees the
  most pertinent content, not a truncated dump of everything.
• Slide chunks and textbook chunks are formatted separately so GPT knows
  exactly which material came from the professor vs the book.
• Slide-first + textbook-enrichment-only rules preserved and strengthened.
"""

from semantic_kernel import Kernel
from semantic_kernel.functions import KernelArguments
from semantic_kernel.prompt_template import PromptTemplateConfig, InputVariable
from semantic_kernel.connectors.ai.open_ai import AzureChatPromptExecutionSettings


FUSION_PROMPT = r"""\
You are AuraGraph, an expert academic study coach for university and engineering students in India.
Produce the BEST study notes a student could read the night before an exam.
Write DENSE, TIGHT notes — every sentence must carry information. No filler. No repetition.

You have been given pre-selected content from two sources:

SLIDES / PROFESSOR NOTES  (primary — drives ALL section headings):
{{$slide_content}}

TEXTBOOK EXCERPTS  (enrichment only — deepens slide content, never adds new sections):
{{$textbook_content}}

TARGET PROFICIENCY: {{$proficiency}}

════════════════════════════════════════════════════════════════
SLIDE-FIRST ARCHITECTURE  ← most important rule
════════════════════════════════════════════════════════════════
• The SLIDES are the ONLY source of `##` section headings.
• Create one `##` heading per slide concept (merge consecutive slides on the
  same concept into one `##` section).
• NEVER create a `##` section for a topic that appears only in the textbook
  but NOT in the slides.
• NEVER skip any slide's content — every formula and definition must appear.

════════════════════════════════════════════════════════════════
TEXTBOOK ENRICHMENT RULE  ← second most important rule
════════════════════════════════════════════════════════════════
• For each slide section, you MAY pull at most 2-3 sentences from the textbook
  that directly deepen that specific slide's content.
• Add textbook enrichment INLINE inside the slide section — never as a
  separate section at the end.
• If no textbook content is clearly relevant to a slide section, skip it.
• DO NOT copy entire textbook paragraphs — extract only what adds value.

════════════════════════════════════════════════════════════════
PROFICIENCY GUIDE
════════════════════════════════════════════════════════════════

FOUNDATIONS — Teach from scratch. For EACH `##` section:
  1. One plain-English sentence: "Simply put, X is …"
  2. One `>` blockquote analogy.
  3. Key formula(s) in display LaTeX + **Where:** table (one line per symbol).
  4. Process as numbered list (max 5 steps) if applicable.
  5. `> 📝 **Exam Tip:** …`

PRACTITIONER — Consolidate. For EACH `##` section:
  1. One concise definition or formal statement.
  2. One intuition sentence linking formula to physical meaning.
  3. Display LaTeX for every key formula; define non-obvious symbols inline.
  4. Key conditions / edge cases as bullet list.
  5. `> 📝 **Exam Tip:** …`

EXPERT — Depth only. For EACH `##` section:
  1. Formal definition with all conditions.
  2. Full derivation (show algebra). Terse — no commentary between steps.
  3. Validity / convergence conditions.
  4. Edge cases and theorem variants as bullets.
  5. One comparison with a related concept.
  6. `> 📝 **Exam Tip:** …`

════════════════════════════════════════════════════════════════
STRICT QUALITY RULES
════════════════════════════════════════════════════════════════
STRUCTURE:
1. Markdown only. `##` for topics, `###` for genuine sub-divisions only.
2. Every `##` section ends with `> 📝 **Exam Tip:** …`
3. No preamble. Start directly with the first `##` heading.
4. No conclusion paragraphs. No `---` horizontal rules.

SECTION HEADINGS — MUST BE DESCRIPTIVE:
• NEVER use bare labels like "Theorem 2", "Corollary 3", "Lemma 1", "Remark 4",
  "Definition 5", "Example 6", or "Slide 7" as `##` headings.
• ALWAYS name the section after what it actually teaches, e.g.:
  - ❌ ## Theorem 2     ✅ ## Measurability of Composite Functions
  - ❌ ## Corollary 3  ✅ ## Continuous Functions are Measurable
  - ❌ ## Remark 4     ✅ ## Equivalence of Sigma-Algebra Generators
• If the slide only gives a bare label, infer a meaningful name from the content.

MATHEMATICS — FORMULA PRESERVATION:
5. ALL math in LaTeX — never write "integral", "sigma", "omega" as words.
6. Inline math: `$expression$`
7. Display math on its own line:
   $$
   \int_{-\infty}^{\infty} f(t)\, e^{-j\omega t}\, dt
   $$
8. NEVER use `\[`, `\]`, `\(`, `\)`. ONLY `$` and `$$`.
9. NEVER wrap math in backtick code fences.
10. Copy formulas EXACTLY as they appear in the source — do NOT simplify,
    rearrange, or "clean up" notation. If the slide writes $P(A|B)$, output
    $P(A|B)$, not $P(B|A)$ or a rearranged form. Preserve the EXACT symbols,
    subscripts, superscripts, and operator order from the source material.
11. If a formula appears in display math in the source, keep it as display math.
    If it is inline, keep it inline. Do not change the display mode.

CONCISENESS:
12. No prose restating what a formula already says.
13. No "In this section we will…" openers.
14. No acknowledgement phrases. No placeholders.
15. IGNORE slide metadata: author name, date, institution, slide numbers.
"""


# DOUBT_ANSWER_PROMPT now delegates to the verification pipeline.
# Import the prompt string from verifier_agent so there is a single source of truth.
from agents.verifier_agent import DOUBT_ANSWER_PROMPT                          # noqa: E402
from agents.verifier_agent import NOTE_SELF_REVIEW_PROMPT                       # noqa: E402


MUTATION_PROMPT = r"""\
You are AuraGraph's Note Mutation Engine.
A student is confused about something. You must ENHANCE the note page to resolve the doubt.

════════════════════════════════
CURRENT NOTE PAGE (exactly what the student is reading):
{{$note_page}}

════════════════════════════════
STUDENT'S DOUBT:
{{$doubt}}

════════════════════════════════
SOURCE MATERIAL — SLIDES (what the professor taught about this topic):
{{$slide_context}}

════════════════════════════════
SOURCE MATERIAL — TEXTBOOK (deeper reference for this topic):
{{$textbook_context}}

════════════════════════════════
TASK:
1. Diagnose the student's conceptual gap in ONE sentence.
2. Produce the ENHANCED NOTE PAGE following these ABSOLUTE RULES:

   ╔══════════════════════════════════════════════════════════════╗
   ║  ADDITIVE-ONLY MUTATION — ZERO DELETIONS ALLOWED            ║
   ║                                                              ║
   ║  • Every sentence, formula, definition, example, exam tip,   ║
   ║    and heading from the CURRENT NOTE PAGE MUST appear in     ║
   ║    your output VERBATIM. Do NOT rephrase, summarize, or      ║
   ║    omit ANY existing content.                                 ║
   ║  • You may ONLY ADD new content — never remove or replace.   ║
   ║  • Your output must be STRICTLY LONGER than the original.    ║
   ╚══════════════════════════════════════════════════════════════╝

   What to ADD (insert at the most relevant location in the existing text):
   - A 💡 intuition block explaining WHY it works, using the source material.
   - Additional formulas from source material that help resolve the doubt.
   - Deeper explanation of the confusing concept with a concrete example.
   - `> 📝 **Exam Tip:**` if the doubt reveals a common misconception.

   Formatting rules:
   - Preserve the `##` heading and all `###` sub-headings exactly.
   - Use display LaTeX for all math (`$$\n...\n$$`). NEVER use `\[` or `\(`.
   - The output MUST be longer than the input. If it is not, you have failed.

3. Output EXACTLY THREE sections separated by `|||`:

<Enhanced note page with ALL original content preserved + new additions>
|||
<One sentence: the diagnosed conceptual gap>
|||
<Direct answer to the student's doubt — 3–6 sentences explaining the concept clearly, as if tutoring the student one-on-one. Use plain language and include key formulas where helpful.>

Do NOT write labels like "Rewritten:", "Gap:", or "Answer:". Just three sections split by |||.
"""


class FusionAgent:
    def __init__(self, kernel: Kernel):
        self._kernel = kernel

        def _make_fn(name: str, prompt: str, vars: list[str], max_tokens: int = 16000):
            config = PromptTemplateConfig(
                template=prompt,
                template_format="semantic-kernel",
                input_variables=[
                    InputVariable(name=v, description=v) for v in vars
                ],
                execution_settings={
                    "gpt4o": AzureChatPromptExecutionSettings(max_tokens=max_tokens)
                },
            )
            return kernel.add_function(
                function_name=name,
                plugin_name="FusionAgent",
                prompt_template_config=config,
            )

        self._fuse_fn   = _make_fn("fuse",   FUSION_PROMPT,            ["slide_content", "textbook_content", "proficiency"])
        self._doubt_fn  = _make_fn("doubt",  DOUBT_ANSWER_PROMPT,      ["doubt", "note_page", "slide_context", "textbook_context", "student_context"])
        self._mutate_fn = _make_fn("mutate", MUTATION_PROMPT,           ["note_page", "doubt", "slide_context", "textbook_context"])
        # review gets a higher token cap — multi-page notes can easily exceed 8k tokens
        self._review_fn = _make_fn("review", NOTE_SELF_REVIEW_PROMPT,   ["note", "slide_context", "textbook_context"], max_tokens=16000)

    async def fuse(
        self,
        slide_content: str,
        textbook_content: str,
        proficiency: str = "Practitioner",
    ) -> str:
        result = await self._kernel.invoke(self._fuse_fn, KernelArguments(
            slide_content=slide_content,
            textbook_content=textbook_content,
            proficiency=proficiency,
        ))
        return str(result).strip()

    async def answer_doubt(
        self,
        doubt: str,
        slide_context: str,
        textbook_context: str,
        note_page: str,
        student_context: str = "",
    ) -> str:
        result = await self._kernel.invoke(self._doubt_fn, KernelArguments(
            doubt=doubt,
            slide_context=slide_context,
            textbook_context=textbook_context,
            note_page=note_page,
            student_context=student_context,
        ))
        return str(result).strip()

    @staticmethod
    def _parse_mutate_response(text: str) -> tuple[str, str, str]:
        """
        FIX L3: Single canonical parser for the ||| separator output.
        Returns (rewritten_note, concept_gap, answer_to_doubt).
        Used by both FusionAgent.mutate (Azure SK path) and the direct
        Groq path in main.py — no duplicate parsing logic anywhere.
        """
        parts = [p.strip() for p in text.split("|||")]
        if len(parts) >= 3:
            rewrite, gap, answer = parts[0], parts[1], " ".join(parts[2:]).strip()
            if rewrite and gap:
                return rewrite, gap, answer
        if len(parts) == 2:
            rewrite, gap = parts[0], parts[1]
            if rewrite and gap:
                return rewrite, gap, ""
        # Fallback: last short paragraph = gap sentence
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(paragraphs) >= 2:
            last = paragraphs[-1]
            if len(last) < 250 and not last.startswith(("#", "$", "|")):
                return "\n\n".join(paragraphs[:-1]).strip(), last, ""
        return text, "Student required additional clarification.", ""

    async def self_review(
        self,
        note: str,
        slide_context: str,
        textbook_context: str,
    ) -> str:
        """Run post-generation accuracy check. Returns raw LLM text for parse_self_review_response."""
        result = await self._kernel.invoke(self._review_fn, KernelArguments(
            note=note,
            slide_context=slide_context,
            textbook_context=textbook_context,
        ))
        return str(result).strip()

    async def mutate(
        self,
        note_page: str,
        doubt: str,
        slide_context: str,
        textbook_context: str,
    ) -> tuple[str, str, str]:
        result = await self._kernel.invoke(self._mutate_fn, KernelArguments(
            note_page=note_page,
            doubt=doubt,
            slide_context=slide_context,
            textbook_context=textbook_context,
        ))
        return self._parse_mutate_response(str(result).strip())
