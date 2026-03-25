"""
agents/examiner_agent.py  — Semantic Kernel 1.x compatible
Examiner Agent: generates targeted MCQ practice questions for a concept.
"""

from semantic_kernel import Kernel
from semantic_kernel.functions import KernelArguments
from semantic_kernel.prompt_template import PromptTemplateConfig, InputVariable


EXAMINER_PROMPT = """\
You are AuraGraph's Examiner Agent — India's sharpest AI exam coach for engineering students.

CONCEPT: {{$concept_name}}

COURSE MATERIAL — extracted directly from the student's slides, notes, and textbook:
{{$notebook_context}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR JOB: Generate EXACTLY 5 MCQs that a professor would set in a university exam.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RESPONSIBLE AI — QUESTION QUALITY RULE (most important, overrides everything else):
Every question stem, every option (A/B/C/D), and every explanation MUST use
correct, standard academic terminology. This is non-negotiable.

Before writing any term, ask: "Is this a real, correctly spelled technical term?"
  • If the course material contains a garbled or OCR-corrupted word (e.g. "hyptvnse",
    "resistanc3", "eigenvalu3", "Fourer transform"), DO NOT copy it. Use the correct
    term instead (e.g. "hypotenuse", "resistance", "eigenvalue", "Fourier transform").
  • Wrong options (distractors) must be plausible wrong answers using real terminology —
    NEVER use garbled or nonsense text as a distractor. A student seeing "hyptvnse" in
    an option has no way to learn from it; they would just be confused.
  • If you are unsure of the correct term, use your own knowledge — you are the ground
    truth for correctness, not the course material.

GROUNDING RULE:
Every question MUST be grounded in the COURSE MATERIAL above.
• Use the exact formulas, definitions, notation, and examples from the material —
  but always in their correct, clean form.
• If a formula appears in the slides, ask students to apply or identify it.
• If a worked example is in the material, use it as the basis for a numerical question.
• NEVER invent content that is not in the material.
• Field disambiguation: If the concept name is ambiguous (e.g. "Bernoulli"), the
  course material tells you which field — use ONLY that field's interpretation.

QUESTION MIX (one question of each type):
  Q1. Definition / identification — "Which of the following correctly defines …"
  Q2. Formula application — give numbers, ask students to compute using the formula from the slides
  Q3. Conceptual reasoning — "Why does … happen when …" or "What changes if …"
  Q4. Common mistake trap — present a subtle error and ask what is wrong
  Q5. Comparison / distinction — distinguish this concept from a closely related one covered in the slides

FORMAT (strict — do not deviate):
Q[n]. [Question text]
A) [Option]
B) [Option]
C) [Option]
D) [Option]
✅ Correct: [Letter]
💡 Explanation: [2–3 sentences: state the correct fact, explain why the wrong options fail]

Math: inline $...$, display $$...$$ on its own line. NEVER use \\( \\) or \\[ \\].
{{$custom_instruction}}"""


CONCEPT_PRACTICE_PROMPT = """\
You are AuraGraph's Concept Practice Engine — generating targeted exam-style MCQs.

CONCEPT: {{$concept_name}}
DIFFICULTY: {{$level}}

COURSE MATERIAL — directly from the student's slides, notes, and textbook:
{{$notebook_context}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DIFFICULTY GUIDE:
  struggling  → Foundational: definition recall, identify the correct formula from the slides,
                single-step calculation using course notation.
  partial     → Standard exam: apply the formula from the material to a numerical problem,
                pick the correct condition/property, identify a common error.
  mastered    → Hard exam: derivation step, edge case, combine two concepts from the material,
                prove or disprove a statement using course theory.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RESPONSIBLE AI — QUESTION QUALITY RULE (highest priority):
Every question stem, every option (A/B/C/D), and every explanation MUST use
correct, standard academic terminology. Never copy garbled or OCR-corrupted text.
  • If course material contains a corrupted word (e.g. "hyptvnse", "eigenvalu3"),
    use the correct term ("hypotenuse", "eigenvalue") — you are the ground truth.
  • Wrong options (distractors) must be plausible real terms — never nonsense strings.
  • A student seeing garbled text in a quiz option cannot learn from it.

GROUNDING RULE: Every question MUST use the exact formulas, notation, and examples from
the COURSE MATERIAL above — but always in correct, clean form.
Use numbers directly from textbook examples if available.
Do NOT generate generic textbook questions — generate questions from THIS student's material.
Field disambiguation: if the concept name could belong to multiple fields, the course material
determines which field — generate questions for THAT field only.

Output ONLY a valid JSON array of exactly 3 objects. Raw JSON — no markdown, no backticks.
Each object MUST have EXACTLY these keys:
  "question"    : full question text (string)
  "options"     : object with keys A, B, C, D (all strings)
  "correct"     : correct option letter ("A", "B", "C", or "D")
  "explanation" : 2–3 sentences explaining the correct answer and why distractors are wrong

Math: inline $...$, display $$...$$ on its own line. NEVER use \\( \\) or \\[ \\].
{{$custom_instruction}}"""


SNIPER_EXAM_PROMPT = """\
You are AuraGraph's Sniper Examiner — generating a targeted 5-question exam.

STRUGGLING CONCEPTS (weight 70% → questions 1, 2, 3):
{{$struggling_concepts}}

REVIEW CONCEPTS (weight 30% → questions 4, 5):
{{$partial_concepts}}

COURSE MATERIAL — from the student's own slides, notes, and textbooks:
{{$notebook_context}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESPONSIBLE AI — QUESTION QUALITY RULE (highest priority):
Every question stem, every option (A/B/C/D), and every explanation MUST use
correct, standard academic terminology. You are the ground truth for correctness.
  • If the course material contains a garbled or OCR-corrupted word, use the correct
    term from your own knowledge — never copy nonsense strings into quiz options.
  • Plausible distractors must be real, recognisable wrong answers — never garbled text.

RULES:
• Questions 1–3 MUST test the struggling concepts — rotate evenly if multiple.
• Questions 4–5 MUST test the partial concepts — rotate evenly if multiple.
• Every question MUST be grounded in the COURSE MATERIAL — use the exact formulas,
  definitions, and examples from the student's own slides and textbook, in correct form.
• No outside-field content — field is determined by the course material, not concept name.
• Make every question exam-ready: specific, unambiguous, with 3 plausible distractors.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Output ONLY a valid JSON array of exactly 5 objects. Raw JSON — no markdown fences.
Each object MUST have EXACTLY these keys:
  "question"    : full question text (string)
  "options"     : object with keys A, B, C, D (all strings)
  "correct"     : the correct option letter ("A", "B", "C", or "D")
  "explanation" : 2–3 sentences explaining the answer and why wrong options fail
  "concept"     : the concept this question tests

Math: inline $...$, display $$...$$ on its own line. NEVER use \\( \\) or \\[ \\].
"""


GENERAL_EXAM_PROMPT = """\
You are AuraGraph's General Examiner — generating a comprehensive 10-question exam
covering ALL the student's concepts.

CONCEPTS TO TEST:
{{$all_concepts}}

COURSE MATERIAL — from the student's own slides, notes, and textbooks:
{{$notebook_context}}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESPONSIBLE AI — QUESTION QUALITY RULE (highest priority):
Every question stem, every option (A/B/C/D), and every explanation MUST use
correct, standard academic terminology. You are the ground truth for correctness.
  • If the course material contains a garbled or OCR-corrupted word, use the correct
    term from your own knowledge — never copy nonsense strings into quiz options.
  • Plausible distractors must be real, recognisable wrong answers — never garbled text.

RULES:
• Distribute the 10 questions evenly across ALL listed concepts.
  If there are fewer than 10 concepts, give more questions to harder topics.
• Every question MUST be grounded in the COURSE MATERIAL — use the exact formulas,
  definitions, and examples from the student's own slides and textbook, in correct form.
• No outside-field content — field is determined by the course material, not concept name.
• Mix question types: definition, formula application, conceptual reasoning, common mistakes.
• Make every question exam-ready: specific, unambiguous, with 3 plausible distractors.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Output ONLY a valid JSON array of exactly 10 objects. Raw JSON — no markdown fences.
Each object MUST have EXACTLY these keys:
  "question"    : full question text (string)
  "options"     : object with keys A, B, C, D (all strings)
  "correct"     : the correct option letter ("A", "B", "C", or "D")
  "explanation" : 2–3 sentences explaining the answer and why wrong options fail
  "concept"     : the concept this question tests

Math: inline $...$, display $$...$$ on its own line. NEVER use \\( \\) or \\[ \\].
"""


class ExaminerAgent:
    def __init__(self, kernel: Kernel):
        self._kernel = kernel
        config = PromptTemplateConfig(
            template=EXAMINER_PROMPT,
            template_format="semantic-kernel",
            input_variables=[
                InputVariable(name="concept_name", description="The concept to generate questions for"),
                InputVariable(name="notebook_context", description="Retrieved course material context", default_value="(no course context available)", is_required=False),
                InputVariable(name="custom_instruction", description="Optional extra instruction from the student", default_value="", is_required=False),
            ],
        )
        self._fn = kernel.add_function(
            function_name="examine",
            plugin_name="ExaminerAgent",
            prompt_template_config=config,
        )
        practice_config = PromptTemplateConfig(
            template=CONCEPT_PRACTICE_PROMPT,
            template_format="semantic-kernel",
            input_variables=[
                InputVariable(name="concept_name", description="Concept to generate questions for"),
                InputVariable(name="level", description="Difficulty level: struggling / partial / mastered"),
                InputVariable(name="notebook_context", description="Retrieved course material context", default_value="(no course context available)", is_required=False),
                InputVariable(name="custom_instruction", description="Optional extra instruction from the student", default_value="", is_required=False),
            ],
        )
        self._practice_fn = kernel.add_function(
            function_name="concept_practice",
            plugin_name="ExaminerAgent",
            prompt_template_config=practice_config,
        )

    async def examine(self, concept_name: str, notebook_context: str = "", custom_instruction: str = "") -> str:
        ci = f"\n\nCUSTOM FOCUS (follow exactly): {custom_instruction}" if custom_instruction.strip() else ""
        ctx = notebook_context or "(no course context available)"
        args = KernelArguments(concept_name=concept_name, notebook_context=ctx, custom_instruction=ci)
        result = await self._kernel.invoke(self._fn, args)
        return str(result).strip()

    async def concept_practice(self, concept_name: str, level: str, notebook_context: str = "", custom_instruction: str = "") -> str:
        ci = f"\n\nCUSTOM FOCUS (follow exactly): {custom_instruction}" if custom_instruction.strip() else ""
        ctx = notebook_context or "(no course context available)"
        args = KernelArguments(concept_name=concept_name, level=level, notebook_context=ctx, custom_instruction=ci)
        result = await self._kernel.invoke(self._practice_fn, args)
        return str(result).strip()
