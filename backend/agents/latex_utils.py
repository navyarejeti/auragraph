r"""
agents/latex_utils.py
Utility: normalize all LaTeX delimiter variants to $ / $$ (rehype-katex friendly).

Any AI-generated text may use \[ \] or \( \) — this converter normalises them
so that remark-math + rehype-katex renders them correctly.

remark-math rules:
  • Inline math  : $expression$   (no spaces between $ and content)
  • Display math : paragraph containing ONLY $$\n…\n$$ with a blank line before
    the opening $$ and a blank line after the closing $$.

v2 fixes vs v1:
  • Step 3 (inline $$…$$) now guards against converting mid-sentence math
    that is already correctly formatted — it only converts when the $$ pair
    is NOT already on its own line.
  • Step 5 collapses to 2 blank lines (not 3), matching Markdown convention.
  • Added Step 6: strip stray zero-width / non-breaking spaces that break KaTeX.
"""

import re


def fix_latex_delimiters(text: str) -> str:
    """
    Normalise all LaTeX delimiter variants to $ / $$ for rehype-katex.

    Steps applied in order
    ──────────────────────
    1. \\( … \\)  (inline)  →  $…$
    2. \\[ … \\]  (display) →  block $$…$$
    3. Inline $$content$$ (genuinely on the same text line, no newlines) → block
       BUT only when the $$ pair is embedded inside other text (not already a
       standalone $$ line). This avoids double-converting properly-formatted blocks.
    4. Ensure every standalone $$ delimiter line has a blank line before it
       (opener) and a blank line after it (closer).
    5. Collapse 3+ consecutive blank lines → 2 (standard Markdown).
    6. Strip zero-width spaces and non-breaking spaces that confuse KaTeX.
    """

    # ── 0. Strip code fences (```markdown … ```) ──────────────────────────
    # LLMs often wrap their response in ```markdown or ```md or ``` fences.
    # ReactMarkdown treats fenced content as a code block, breaking rendering.
    text = re.sub(
        r'^\s*```+\s*(?:markdown|md|latex|text)?\s*\n',
        '',
        text,
        flags=re.MULTILINE,
    )
    # Remove trailing ``` fences (standalone on a line)
    text = re.sub(r'\n\s*```+\s*$', '', text)
    # Also strip if the entire text is wrapped in a single fence pair
    stripped = text.strip()
    if stripped.startswith('```') and stripped.endswith('```'):
        # Remove opening fence line and closing fence
        first_nl = stripped.find('\n')
        if first_nl != -1:
            text = stripped[first_nl + 1:]
            if text.rstrip().endswith('```'):
                text = text.rstrip()[:-3].rstrip()

    # ── 1. \\(…\\) → $…$ ────────────────────────────────────────────────────
    text = re.sub(
        r'\\\\\(\s*(.*?)\s*\\\\\)',
        lambda m: '$' + m.group(1).strip() + '$',
        text,
        flags=re.DOTALL,
    )
    # Also handle single-backslash variants (from some LLM outputs)
    text = re.sub(
        r'\\\(\s*(.*?)\s*\\\)',
        lambda m: '$' + m.group(1).strip() + '$',
        text,
        flags=re.DOTALL,
    )

    # ── 2. \\[…\\] → block $$…$$ ─────────────────────────────────────────────
    text = re.sub(
        r'\\\\\[\s*(.*?)\s*\\\\\]',
        lambda m: '\n\n$$\n' + m.group(1).strip() + '\n$$\n\n',
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'\\\[\s*(.*?)\s*\\\]',
        lambda m: '\n\n$$\n' + m.group(1).strip() + '\n$$\n\n',
        text,
        flags=re.DOTALL,
    )

    # ── 3. Inline $$content$$ → block ─────────────────────────────────────────
    # Only convert when the $$ pair appears mid-line (surrounded by other text
    # OR at start/end of a line that has other content).
    # Do NOT convert if the line is already a standalone $$ delimiter.
    #
    # Pattern: $$<content>$$ where content has no newlines.
    # Guard: line must not be ONLY "$$" (that's already a delimiter).
    def _inline_dd_to_block(m: re.Match) -> str:
        content = m.group(1).strip()
        # If the content itself contains $$ it was likely already a block — skip
        if '$$' in content:
            return m.group(0)
        return '\n\n$$\n' + content + '\n$$\n\n'

    text = re.sub(
        r'(?<!\n)\$\$([^$\n]{1,300}?)\$\$(?!\$)',
        _inline_dd_to_block,
        text,
    )

    # ── 4. Ensure blank lines around standalone $$ delimiter lines ─────────────
    lines = text.split('\n')
    out: list[str] = []
    in_display = False

    for i, line in enumerate(lines):
        if line.strip() == '$$':
            if not in_display:
                # Opening $$: needs blank line before it
                if out and out[-1].strip():
                    out.append('')
                out.append(line)
                in_display = True
            else:
                # Closing $$
                out.append(line)
                in_display = False
                # Needs blank line after it if next line has content
                if i + 1 < len(lines) and lines[i + 1].strip():
                    out.append('')
        else:
            out.append(line)

    # ── 5. Collapse excessive blank lines → max 2 ────────────────────────────
    text = '\n'.join(out)
    text = re.sub(r'\n{3,}', '\n\n', text)

    # ── 6. Strip zero-width / non-breaking spaces ─────────────────────────────
    text = text.replace('\u200b', '').replace('\u00a0', ' ').replace('\ufeff', '')

    return text.strip()
