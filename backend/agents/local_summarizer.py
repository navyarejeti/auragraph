"""agents/local_summarizer.py  — AuraGraph offline fallback  v2.0
Section builders and public API. Helpers live in local_summarizer_utils.py.
"""
import re
from typing import Optional

from agents.local_summarizer_utils import (
    _clean_pdf_text, _parse_slide_sections, _detect_heading_sections,
    _find_best_textbook_paragraph, _extract_enrichment, _extract_math_and_prose,
    _split_sentences, _score_and_pick, _get_analogy, _formula_hint, _exam_tip,
    _math_block, _raw_to_latex, _is_math_line,
)

__all__ = ["generate_local_note", "_PROF", "_is_math_line"]


# ─── Section builders ─────────────────────────────────────────────────────────
def _build_beginner_section(
    heading: str, body: str, enrichment: str,
    sentences: list[str], math_lines: list[str],
) -> Optional[str]:
    if not sentences and not math_lines:
        return None

    enrich_sentences = _split_sentences(enrichment) if enrichment else []
    all_sentences = sentences + [s for s in enrich_sentences if s not in sentences]

    defn_s    = [s for s in all_sentences if re.search(r'\b(is|are|defined|means|represents|refers to|known as|called|describes)\b', s, re.I)]
    why_s     = [s for s in all_sentences if re.search(r'\b(used|useful|important|application|allows|enables|helps|purpose|essential|fundamental)\b', s, re.I)]
    how_s     = [s for s in all_sentences if re.search(r'\b(given by|calculated|computed|found by|steps|process|method|procedure|approach|first|then|finally)\b', s, re.I)]
    example_s = [s for s in all_sentences if re.search(r'\b(example|instance|consider|suppose|imagine|such as|for example|e\.g|think of)\b', s, re.I)]
    reason_s  = [s for s in all_sentences if re.search(r'\b(because|therefore|since|hence|thus|which means|this means|this is why|reason)\b', s, re.I)]

    parts = []

    what_pool = defn_s[:4] if defn_s else all_sentences[:3]
    parts.append("### 📖 What Is It?\n\n" + "\n\n".join(what_pool[:4]))

    why_pool = list(dict.fromkeys(why_s + reason_s))
    if why_pool:
        parts.append("### 🎯 Why Does It Matter?\n\n" + "\n\n".join(why_pool[:3]))

    shown    = set(what_pool[:4] + why_pool[:3])
    how_pool = how_s if how_s else [s for s in all_sentences if s not in shown]
    if how_pool:
        parts.append("### ⚙️ How Does It Work?\n\n" + "\n\n".join(how_pool[:4]))

    if example_s:
        parts.append("### 💎 Worked Example\n\n" + "\n\n".join(example_s[:2]))

    analogy = _get_analogy(heading, body)
    if analogy:
        parts.append(f"> {analogy}")

    all_shown = set(what_pool[:4] + why_pool[:3] + how_pool[:4] + example_s[:2])
    leftover  = [s for s in all_sentences if s not in all_shown]
    if leftover:
        parts.append("### 📌 Also Important\n\n" + "\n\n".join(leftover[:3]))

    if math_lines:
        formula_parts = ["> 💡 **Formulas** (shown for reference — focus on the idea first!)\n"]
        for ml in math_lines[:4]:
            formula_parts.append(_math_block(ml))
            hint = _formula_hint(_raw_to_latex(ml))
            if hint:
                formula_parts.append(f"*{hint}*")
        parts.append("\n\n".join(formula_parts))

    if not parts:
        return None

    tip = _exam_tip(heading, body)
    return f"## {heading}\n\n" + "\n\n".join(parts) + f"\n\n> 📝 **Exam Tip:** {tip}"


def _build_intermediate_section(
    heading: str, body: str, enrichment: str,
    top_prose: list[str], math_lines: list[str],
) -> Optional[str]:
    if not top_prose and not math_lines:
        return None

    enrich_sentences = _split_sentences(enrichment)[:2] if enrichment else []
    parts = []

    defn = [s for s in top_prose if re.search(
        r'\b(is|are|defined as|defined by|means|represents|refers to|describes|known as|called)\b', s, re.I)]
    if defn:
        parts.append("### 📖 Definition\n\n" + " ".join(defn[:2]))

    how = [s for s in top_prose if s not in defn and re.search(
        r'\b(given by|calculated|computes|maps|transforms|yields|produces|allows|enables|because|therefore|hence|since|which means)\b', s, re.I)]
    if not how:
        how = [s for s in top_prose if s not in defn]
    combined_how = list(dict.fromkeys(how[:3] + enrich_sentences))
    if combined_how:
        parts.append("### 💡 Intuition\n\n" + "\n\n".join(combined_how[:4]))

    analogy = _get_analogy(heading, body)
    if analogy:
        parts.append(f"> {analogy}")

    cond = [s for s in top_prose if s not in defn and s not in how and re.search(
        r'\b(condition|constraint|requirement|valid|converge|exist|property|must|only if|if and only|assume)\b', s, re.I)]
    if cond:
        bullets = "\n".join(f"- {s}" for s in cond[:4])
        parts.append(f"### 📋 Key Conditions\n\n{bullets}")

    if math_lines:
        formula_parts = ["### 🔢 Formulas\n"]
        for ml in math_lines[:5]:
            formula_parts.append(_math_block(ml))
        parts.append("\n\n".join(formula_parts))

    if not parts:
        return None

    tip = _exam_tip(heading, body)
    return f"## {heading}\n\n" + "\n\n".join(parts) + f"\n\n> 📝 **Exam Tip:** {tip}"


def _build_advanced_section(
    heading: str, body: str, enrichment: str,
    top_prose: list[str], math_lines: list[str],
) -> Optional[str]:
    if not top_prose and not math_lines:
        return None

    enrich_sentences = _split_sentences(enrichment)[:2] if enrichment else []
    parts = []

    defn = [s for s in top_prose if re.search(
        r'\b(is defined|defined as|formally|let|suppose|assume|denote|given|theorem|states that)\b', s, re.I)]
    rest = [s for s in top_prose if s not in defn]
    all_prose = list(dict.fromkeys(rest + enrich_sentences))

    if defn:
        parts.append("### Formal Definition\n\n" + " ".join(defn[:3]))
    if all_prose:
        paras = []
        for i in range(0, len(all_prose), 3):
            paras.append(" ".join(all_prose[i:i+3]))
        parts.append("\n\n".join(paras))

    if math_lines:
        formula_block = [_math_block(ml) for ml in math_lines[:8]]
        parts.append("\n\n".join(formula_block))

    cond = [s for s in top_prose if re.search(
        r'\b(condition|constraint|converge|exist|valid|boundary|special case|edge case|degenerate|when|if and only)\b', s, re.I)]
    if cond:
        bullets = "\n".join(f"- {s}" for s in cond[:6])
        parts.append(f"### Conditions & Edge Cases\n\n{bullets}")

    if not parts:
        return None

    tip = _exam_tip(heading, body)
    return f"## {heading}\n\n" + "\n\n".join(parts) + f"\n\n> 📝 **Exam Tip:** {tip}"


# ─── Main section dispatcher ──────────────────────────────────────────────────
def _build_section(
    heading: str, body: str, enrichment: str,
    prose_k: int, proficiency: str,
) -> Optional[str]:
    math_lines, prose_lines = _extract_math_and_prose(body)
    sentences = _split_sentences(" ".join(prose_lines))

    if not sentences and not math_lines:
        return None

    if proficiency == "Foundations":
        return _build_beginner_section(heading, body, enrichment, sentences, math_lines)
    else:
        top_prose = _score_and_pick(sentences, prose_k) if len(sentences) > prose_k else sentences
        if proficiency == "Practitioner":
            return _build_intermediate_section(heading, body, enrichment, top_prose, math_lines)
        else:
            return _build_advanced_section(heading, body, enrichment, top_prose, math_lines)


# ─── Proficiency config ───────────────────────────────────────────────────────
_PROF = {
    "Foundations": {
        "prose_k": 99,
        "label":   "Full conceptual depth — every idea explained from scratch with analogies",
    },
    "Practitioner": {
        "prose_k": 8,
        "label":   "Balanced depth — key formulas with intuition and application",
    },
    "Expert": {
        "prose_k": 6,
        "label":   "Full rigour — formal definitions, derivations, edge cases",
    },
}


# ─── Public API ───────────────────────────────────────────────────────────────
def generate_local_note(slides_text: str, textbook_text: str, proficiency: str) -> str:
    """
    Generate structured Markdown study notes from extracted PDF/PPTX text.

    v2 Architecture:
      1. Parse slides into sections — SLIDES DRIVE the note structure.
      2. Split textbook into paragraphs.
      3. For each slide section, find the single most relevant textbook
         paragraph (keyword overlap). Extract 2-3 enrichment sentences.
      4. Build the section note: slide content + minimal enrichment.
      5. Deduplicate headings.
    """
    cfg     = _PROF.get(proficiency, _PROF["Practitioner"])
    prose_k = cfg["prose_k"]

    slides_text   = _clean_pdf_text(slides_text)
    textbook_text = _clean_pdf_text(textbook_text)

    # 1. Parse slide sections
    slide_sections = _parse_slide_sections(slides_text) if slides_text.strip() else []

    # 2. If no slides, use textbook as primary source (no enrichment)
    if not slide_sections and textbook_text.strip():
        slide_sections = _detect_heading_sections(textbook_text)
        textbook_text  = ""

    if not slide_sections:
        return (
            "## ⚠️ Could Not Extract Notes\n\n"
            "No readable text was found in your PDFs. "
            "Make sure they are text-based (not scanned images).\n\n"
            "If they are scanned, use a tool like Adobe Acrobat to run OCR first."
        )

    # 3. Split textbook into paragraphs for enrichment matching
    textbook_paragraphs: list[str] = []
    if textbook_text.strip():
        textbook_paragraphs = [
            p.strip()
            for p in re.split(r'\n{2,}', textbook_text)
            if len(p.strip()) > 60   # was 120 — too aggressive, dropped short but relevant paragraphs
        ]

    # 4. Build sections
    sections: list[str] = []
    seen_keys: set[str] = set()

    for heading, body in slide_sections:
        key = re.sub(r'\s+', ' ', heading.lower().strip())
        if key in seen_keys:
            continue
        seen_keys.add(key)

        enrichment = ""
        if textbook_paragraphs:
            best_para = _find_best_textbook_paragraph(heading, body, textbook_paragraphs)
            if best_para:
                enrichment = _extract_enrichment(
                    best_para,
                    max_sentences=3 if proficiency == "Foundations" else 2
                )

        sec = _build_section(heading, body, enrichment, prose_k, proficiency)
        if sec:
            sections.append(sec)

    if not sections:
        return (
            "## ⚠️ Could Not Extract Notes\n\n"
            "No readable text was found in your PDFs. "
            "Make sure they are text-based (not scanned images)."
        )

    # 5. Compose final output
    level_banner = {
        "Foundations":  "🔰 **Foundations mode** — Every concept taught from scratch. Read each section fully before looking at formulas.",
        "Practitioner": "⚡ **Practitioner mode** — Key definitions, formulas, and worked intuition.",
        "Expert":       "🎯 **Expert mode** — Full rigour: derivations, edge cases, formal notation.",
    }.get(proficiency, "")

    header = (
        f"# AuraGraph Study Notes\n\n"
        f"**Study Mode: {proficiency}** — {cfg['label']}\n\n"
        f"> {level_banner}\n"
    )
    return header + "\n\n---\n\n" + "\n\n---\n\n".join(sections)
