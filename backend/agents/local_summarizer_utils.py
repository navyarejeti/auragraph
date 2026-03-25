r"""
agents/local_summarizer_utils.py — Private helpers for the AuraGraph offline note generator.
Extracted from local_summarizer.py to keep the main module under ~300 lines.
"""

import re
from collections import Counter
from typing import Optional


# ─── Stop words ───────────────────────────────────────────────────────────────
_STOP = set(
    "a an the is are was were be been being have has had do does did will would "
    "shall should may might must can could to of in on at for by with from as it "
    "its this that these those and or but not so if then than when where which who "
    "what how all any each every no more most other some such into out up down over "
    "under also just only very well about after before during between through while "
    "we they he she you i".split()
)


# ─── Math symbol → LaTeX conversion table ─────────────────────────────────────
_MATH_SUBS = [
    (r'\b2pi\b',                  r'2\\pi'),
    (r'\bj2pi\b',                 r'j2\\pi'),
    (r'\bpi\s*/\s*2\b',           r'\\pi/2'),
    (r'\bC\((\w+),\s*(\w+)\)',    r'\\binom{\1}{\2}'),
    (r'\bGamma\b',    r'\\Gamma'),
    (r'\bgamma\b',    r'\\gamma'),
    (r'\bDelta\b',    r'\\Delta'),
    (r'\bdelta\b',    r'\\delta'),
    (r'\bTheta\b',    r'\\Theta'),
    (r'\btheta\b',    r'\\theta'),
    (r'\bLambda\b',   r'\\Lambda'),
    (r'\blambda\b',   r'\\lambda'),
    (r'\bSigma\b',    r'\\Sigma'),
    (r'\bsigma\b',    r'\\sigma'),
    (r'\bOmega\b',    r'\\Omega'),
    (r'\bomega\b',    r'\\omega'),
    (r'\bAlpha\b',    r'\\Alpha'),
    (r'\balpha\b',    r'\\alpha'),
    (r'\bBeta\b',     r'\\Beta'),
    (r'\bbeta\b',     r'\\beta'),
    (r'\bepsilon\b',  r'\\epsilon'),
    (r'\bvarepsilon\b', r'\\varepsilon'),
    (r'\bzeta\b',     r'\\zeta'),
    (r'(?<![a-z])eta\b', r'\\eta'),
    (r'\bmu\b',       r'\\mu'),
    (r'\bnu\b',       r'\\nu'),
    (r'\bxi\b',       r'\\xi'),
    (r'\bPi\b',       r'\\Pi'),
    (r'\bpi\b',       r'\\pi'),
    (r'\brho\b',      r'\\rho'),
    (r'\btau\b',      r'\\tau'),
    (r'\bPhi\b',      r'\\Phi'),
    (r'\bphi\b',      r'\\phi'),
    (r'\bPsi\b',      r'\\Psi'),
    (r'\bpsi\b',      r'\\psi'),
    (r'\bnabla\b',    r'\\nabla'),
    (r'\bchi\b',      r'\\chi'),
    (r'\bkappa\b',    r'\\kappa'),
    (r'\binfty\b',       r'\\infty'),
    (r'\binfinity\b',    r'\\infty'),
    (r'\bforall\b',      r'\\forall'),
    (r'\bexists\b',      r'\\exists'),
    (r'\bintegral(?=\b|_|\^|\{|\s)', r'\\int'),
    (r'\bpartial\b',     r'\\partial'),
    (r'\bgrad\b',        r'\\nabla'),
    (r'\bsqrt(?=[\s_^\{(])', r'\\sqrt'),
    (r'\bsum(?=\b|_|\^|\{)',    r'\\sum'),
    (r'\bprod(?=\b|_|\^|\{)',   r'\\prod'),
    (r'\blim(?=\b|_|\^|\{)',    r'\\lim'),
    (r'\bmax(?=\b|_|\^|\{)',    r'\\max'),
    (r'\bmin(?=\b|_|\^|\{)',    r'\\min'),
    (r'\bsup(?=\b|_|\^|\{)',    r'\\sup'),
    (r'\binf(?=\b|_|\^|\{)',    r'\\inf'),
    (r'\bsinh(?=\b|_|\^|\{)',   r'\\sinh'),
    (r'\bcosh(?=\b|_|\^|\{)',   r'\\cosh'),
    (r'\btanh(?=\b|_|\^|\{)',   r'\\tanh'),
    (r'\bsin(?=\b|_|\^|\{)',    r'\\sin'),
    (r'\bcos(?=\b|_|\^|\{)',    r'\\cos'),
    (r'\btan(?=\b|_|\^|\{)',    r'\\tan'),
    (r'\bcot(?=\b|_|\^|\{)',    r'\\cot'),
    (r'\bsec(?=\b|_|\^|\{)',    r'\\sec'),
    (r'\bcsc(?=\b|_|\^|\{)',    r'\\csc'),
    (r'\blog(?=\b|_|\^|\{)',    r'\\log'),
    (r'\bln(?=\b|_|\^|\{)',     r'\\ln'),
    (r'\bexp(?=\b|_|\^|\{)',    r'\\exp'),
    (r'\bdet(?=\b|_|\^|\{)',    r'\\det'),
    (r'\btr\b',                 r'\\text{tr}'),
    (r'<->',  r'\\leftrightarrow'),
    (r'<=>',  r'\\Leftrightarrow'),
    (r'->',   r'\\rightarrow'),
    (r'=>',   r'\\Rightarrow'),
    (r'<-',   r'\\leftarrow'),
    (r'!=',           r'\\neq'),
    (r'>=',           r'\\geq'),
    (r'<=',           r'\\leq'),
    (r'\bapprox\b',   r'\\approx'),
    (r'\bpm\b',       r'\\pm'),
    (r'\btimes\b',    r'\\times'),
    (r'\bcdot\b',     r'\\cdot'),
]


def _raw_to_latex(raw: str) -> str:
    r"""Convert a raw PDF formula string to proper LaTeX (single-pass, no double-backslash)."""
    s = raw.strip()
    if '\\' in s:
        return s
    combined_pattern = '|'.join(f'(?P<g{i}>{pat})' for i, (pat, _) in enumerate(_MATH_SUBS))
    repls = [r for _, r in _MATH_SUBS]

    def _replace(m: re.Match) -> str:
        for i, repl in enumerate(repls):
            gname = f'g{i}'
            if m.group(gname) is not None:
                return repl
        return m.group(0)

    return re.sub(combined_pattern, _replace, s)


# ─── Math line detection (two-pass) ───────────────────────────────────────────
_STRUCTURAL_MATH_RE = re.compile(
    r'\\[a-zA-Z]+'
    r'|\$[^$]|\$\$'
    r'|[A-Za-z]\s*\^\s*[\d{(]'
    r'|[A-Za-z]\s*_\s*[\d{(a-z]'
    r'|\b\d+\s*[+\-*/]\s*\d+\b'
)

_PROSE_GUARD_RE = re.compile(
    r'\b(is|are|the|denotes|means|where|which|such|called|represent|equal|'
    r'defined|given|known|refers|describes|consider|let|suppose|note|show|'
    r'when|thus|hence|since|because|therefore|allows|using|used)\b',
    re.I
)

_GREEK_RE = re.compile(
    r'\b(alpha|beta|gamma|delta|epsilon|zeta|theta|lambda|mu|nu|xi|rho|sigma|tau|'
    r'phi|psi|omega|nabla|infty|infinity|integral|partial|chi|kappa)\b',
    re.I
)


def _is_math_line(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 300:
        return False
    if _STRUCTURAL_MATH_RE.search(s):
        if len(s.split()) > 12 and _PROSE_GUARD_RE.search(s):
            return False
        return True
    has_ops   = bool(re.search(r'[=+\-*/^<>]', s))
    has_greek = bool(_GREEK_RE.search(s))
    if has_greek and has_ops:
        if len(s.split()) <= 12 and not _PROSE_GUARD_RE.search(s):
            return True
    if re.search(r'[A-Za-z]\w*\s*\([^)]{0,20}\)\s*=', s):
        if not _PROSE_GUARD_RE.search(s):
            return True
    if len(s.split()) <= 5 and re.search(r'[=+\-*/^]', s) and not re.search(r'\b(is|are|the|a|an)\b', s, re.I):
        return True
    return False


# ─── Text cleaning ────────────────────────────────────────────────────────────
_CID_INLINE_RE = re.compile(r'\(cid:\d+\)')
_PAGE_MARK_RE  = re.compile(r'---\s*[Pp]age\s+\d+\s*---')


def _clean_pdf_text(text: str) -> str:
    _noise = re.compile(
        r"^\s*("
        r"(lecture|lec|slide|unit|module|chapter|topic|week|session)\s*[\d\.\:]+.*"
        r"|page\s+\d+"
        r"|\d+\s*/\s*\d+"
        r"|copyright|all rights reserved|university|institute|dept\."
        r"|www\.|http|\.com|\.edu|\.org"
        r")\s*$",
        re.IGNORECASE
    )
    text = _CID_INLINE_RE.sub('', text)
    text = _PAGE_MARK_RE.sub('', text)
    lines: list[str] = []
    prev_compact = ''
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            lines.append("")
            prev_compact = ''
            continue
        if len(stripped) <= 3:
            continue
        if _noise.match(stripped):
            continue
        compact = re.sub(r'\s+', '', stripped)
        if compact and compact == prev_compact:
            fixed_cur = re.sub(r'([a-z])([A-Z][a-z])', r'\1 \2', stripped)
            fixed_cur = re.sub(r'([.!?])([A-Z])', r'\1 \2', fixed_cur)
            if lines and lines[-1].strip():
                lines[-1] = fixed_cur
            continue
        prev_compact = compact if compact else prev_compact
        fixed = re.sub(r'([a-z])([A-Z][a-z])', r'\1 \2', stripped)
        fixed = re.sub(r'([.!?])([A-Z])', r'\1 \2', fixed)
        lines.append(fixed)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# ─── Slide-aware section parser ────────────────────────────────────────────────
def _parse_slide_sections(slides_text: str) -> list[tuple[str, str]]:
    """Parse slide text into (heading, body) pairs using slide markers."""
    slide_marker = re.compile(
        r'^---\s*Slide\s+\d+(?::\s*(.+?))?\s*---\s*$',
        re.MULTILINE
    )
    matches = list(slide_marker.finditer(slides_text))
    if matches:
        raw_sections = []
        for i, m in enumerate(matches):
            title = (m.group(1) or '').strip()
            start = m.end()
            end   = matches[i + 1].start() if i + 1 < len(matches) else len(slides_text)
            body  = slides_text[start:end].strip()
            raw_sections.append((title or f"Slide {i+1}", body))

        merged = []
        pending_bodies: list[str] = []
        for title, body in raw_sections:
            is_short = len(body) < 80 and (not title or title.startswith('Slide '))
            if is_short:
                if body:
                    pending_bodies.append(body)
            else:
                if pending_bodies:
                    combined = "\n\n".join(pending_bodies) + "\n\n" + body
                    body = combined.strip()
                    pending_bodies = []
                merged.append((title, body))
        if pending_bodies and merged:
            prev_t, prev_b = merged[-1]
            extra = "\n\n".join(pending_bodies)
            merged[-1] = (prev_t, (prev_b + "\n\n" + extra).strip())
        elif pending_bodies:
            merged.append(("Overview", "\n\n".join(pending_bodies)))
        if merged:
            return merged
    return _detect_heading_sections(slides_text)


def _detect_heading_sections(text: str) -> list[tuple[str, str]]:
    heading_pat = re.compile(
        r"^("
        r"[A-Z][A-Z0-9 ,\-:\'&\/]{2,50}"
        r"|[A-Z][a-zA-Z0-9\-]+(?:\s+[A-Z][a-zA-Z0-9\-]+){1,6}"
        r"|\d+[\.\d]*\s+[A-Z][A-Za-z0-9 ,\-:\'&\/]{3,50}"
        r")$",
        re.MULTILINE
    )
    noise_h = re.compile(r"(lecture|slide|page|copyright|university|institute)", re.I)
    matches = [m for m in heading_pat.finditer(text) if not noise_h.search(m.group(0))]
    if len(matches) >= 2:
        secs = []
        for i, m in enumerate(matches):
            heading = m.group(0).strip().title()
            start   = m.end()
            end     = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body    = text[start:end].strip()
            if len(body) > 40:
                secs.append((heading, body))
        if secs:
            return secs
    paras   = [p.strip() for p in re.split(r"\n{2,}", text) if len(p.strip()) > 60]
    merged, current = [], ""
    for para in paras:
        if current and len(current) + len(para) > 800:
            merged.append(current)
            current = para
        else:
            current = (current + "\n\n" + para).strip() if current else para
    if current:
        merged.append(current)
    return [(f"Section {i+1}", c) for i, c in enumerate(merged)]


# ─── TF-IDF keyword helpers ───────────────────────────────────────────────────
def _keywords(text: str) -> set[str]:
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    return {w for w in words if w not in _STOP}


def _keyword_overlap(a_kw: set[str], b_kw: set[str]) -> float:
    if not a_kw or not b_kw:
        return 0.0
    return len(a_kw & b_kw) / len(a_kw | b_kw)


def _find_best_textbook_paragraph(
    slide_heading: str,
    slide_body: str,
    textbook_paragraphs: list[str],
    min_overlap: float = 0.08,
) -> Optional[str]:
    slide_kw   = _keywords(slide_heading + " " + slide_body)
    best_score = min_overlap
    best_para  = None
    for para in textbook_paragraphs:
        if len(para) < 50:
            continue
        para_kw = _keywords(para)
        score   = _keyword_overlap(slide_kw, para_kw)
        if score > best_score:
            best_score = score
            best_para  = para
    return best_para


def _extract_enrichment(textbook_para: str, max_sentences: int = 3) -> str:
    sentences = _split_sentences(textbook_para)
    if not sentences:
        return ""
    scored = []
    for s in sentences:
        score = 0
        if re.search(r'\b(defined|definition|theorem|states|formula|given by|'
                     r'represents|equals|describes|can be written)\b', s, re.I):
            score += 3
        if re.search(r'\b(because|therefore|since|hence|thus|this means)\b', s, re.I):
            score += 2
        if re.search(r'\b(important|key|fundamental|note|recall)\b', s, re.I):
            score += 1
        scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return " ".join(s for _, s in scored[:max_sentences])


# ─── Sentence utilities ────────────────────────────────────────────────────────
def _split_sentences(text: str) -> list[str]:
    protected = re.sub(
        r'\b(Fig|Eq|No|Vol|Ch|Sec|Ref|est|approx|vs|etc|e\.g|i\.e|Dr|Prof|St|Mr|Mrs|Ms)\.',
        lambda m: m.group(0).replace('.', '\x00'),
        text
    )
    raw = re.split(r'(?<=[.!?])\s+(?=[A-Z])', protected)
    restored = [s.replace('\x00', '.').strip() for s in raw]
    return [s for s in restored if len(s.split()) >= 5 and not _is_math_line(s)]


def _score_and_pick(sentences: list[str], k: int) -> list[str]:
    all_words = [
        w.lower() for s in sentences
        for w in re.findall(r'\b[a-zA-Z]{3,}\b', s)
        if w.lower() not in _STOP
    ]
    freq = Counter(all_words)

    def score(s: str) -> float:
        words = [w.lower() for w in re.findall(r'\b[a-zA-Z]{3,}\b', s) if w.lower() not in _STOP]
        if not words:
            return 0.0
        base = sum(freq[w] for w in words) / len(words)
        if re.search(r'\b(defined|definition|means|states|theorem|law|principle|formula|'
                     r'algorithm|property|given by|represents|equals|describes)\b', s, re.I):
            base *= 2.0
        if re.search(r'\b(example|instance|consider|such as|for example|e\.g|imagine)\b', s, re.I):
            base *= 1.5
        if re.search(r'\b(because|therefore|since|hence|thus|which means|this means)\b', s, re.I):
            base *= 1.4
        if re.search(r'\b(important|note|recall|remember|key|fundamental|essential|crucial)\b', s, re.I):
            base *= 1.3
        return base

    scored   = sorted(enumerate(sentences), key=lambda x: -score(x[1]))
    top_idx  = {i for i, _ in scored[:k]}
    return [s for i, s in enumerate(sentences) if i in top_idx]


# ─── Math line extraction ──────────────────────────────────────────────────────
def _extract_math_and_prose(body: str) -> tuple[list[str], list[str]]:
    math_set   = []
    math_seen  = set()
    prose_lines = []
    for line in body.split("\n"):
        s = line.strip()
        if not s:
            continue
        if _is_math_line(s):
            key = re.sub(r'\s+', '', s.lower())
            if key not in math_seen:
                math_seen.add(key)
                math_set.append(s)
        else:
            prose_lines.append(s)
    return math_set, prose_lines


# ─── Analogy bank ─────────────────────────────────────────────────────────────
_ANALOGIES: dict[str, str] = {
    "fourier": (
        "🎵 **Think of it like this:** Imagine holding a cable connected to a speaker playing a chord. "
        "You hear *one* complex sound. The Fourier Transform is like a **musical equaliser** — it splits "
        "that complex sound into individual frequency ingredients. After the transform you can see exactly "
        "*how much* of each frequency is present."
    ),
    "convolution": (
        "🌊 **Think of it like this:** Imagine pouring water through a sponge. The sponge is the system's "
        "**impulse response** $h(t)$. The water is your **input signal** $x(t)$. Convolution calculates "
        "the smearing effect — at every moment it asks: 'How much past input is still ringing through the system?'"
    ),
    "laplace": (
        "🔧 **Think of it like this:** Fourier only works on stable signals. Laplace multiplies the signal "
        "by $e^{-\\sigma t}$ to tame it before transforming. Think of Laplace as "
        "**Fourier with a safety harness** for unstable or transient signals."
    ),
    "z-transform": (
        "🎮 **Think of it like this:** All digital audio is processed as discrete number sequences. "
        "The Z-Transform analyses these **digital sequences** the same way Laplace analyses continuous signals. "
        "Laplace = analog world; Z-Transform = **digital world**."
    ),
    "sampling": (
        "📱 **Think of it like this:** Recording audio at 44,100 Hz means 44,100 measurements per second. "
        "Nyquist says you must sample at **at least twice** the highest frequency you want to capture. "
        "Sample too slowly and you get **aliasing** — distorted high frequencies."
    ),
    "lti": (
        "🏭 **Think of it like this:** An LTI system is like a reliable factory machine. **Linear**: "
        "double the input → double the output. **Time-invariant**: the machine behaves identically "
        "whether you feed it input now or an hour later."
    ),
    "probability": (
        "🎲 **Think of it like this:** If a bag has 3 red and 7 blue balls, the probability of picking "
        "red is 3/10 = 0.3. Everything in probability builds on: "
        "$P(\\text{event}) = \\frac{\\text{favourable}}{\\text{total outcomes}}$."
    ),
    "binomial": (
        "🪙 **Think of it like this:** Flip a biased coin $n$ times. The Binomial distribution answers "
        "'What's the chance of exactly $k$ heads?' The formula $\\binom{n}{k} p^k (1-p)^{n-k}$ counts "
        "all ways to arrange $k$ successes in $n$ tries."
    ),
    "normal": (
        "📈 **Think of it like this:** Measure 10,000 people's heights — most cluster near the average "
        "with fewer at extremes. That bell curve is the Normal distribution, appearing everywhere due to "
        "the **Central Limit Theorem**."
    ),
    "derivative": (
        "🚗 **Think of it like this:** A car's **speedometer** shows velocity — that's a derivative. "
        "It tells you how fast your *position* is changing at this exact instant. "
        "Geometrically, it's the **slope of the tangent line** at a point."
    ),
    "integral": (
        "📦 **Think of it like this:** Imagine filling a pool by tracking flow rate each second. "
        "The integral adds all those tiny amounts to give the **total water collected**. "
        "$\\int_a^b f(x)\\,dx$ = area under the curve from $a$ to $b$."
    ),
    "eigenvalue": (
        "🔍 **Think of it like this:** Apply a transformation to every vector. Most change direction. "
        "But special **eigenvectors** only get stretched/shrunk, keeping the same direction. "
        "The stretch factor is the **eigenvalue** $\\lambda$."
    ),
    "matrix": (
        "📊 **Think of it like this:** A matrix encodes a **transformation** — rotating, scaling, "
        "reflecting a space. Multiplying a vector by a matrix applies that transformation to it."
    ),
}


def _get_analogy(heading: str, body: str) -> str:
    text = (heading + " " + body).lower()
    for kw, analogy in _ANALOGIES.items():
        if kw in text:
            return analogy
    return ""


# ─── Formula hints ────────────────────────────────────────────────────────────
_FORMULA_HINTS: list[tuple[str, str]] = [
    (r'\\int',       "↑ This integral sums up tiny contributions over a range — the continuous version of adding things up."),
    (r'\\sum',       "↑ Σ means: add up the expression for every value from the bottom index to the top."),
    (r'e\^',         "↑ $e^x$ is the exponential function ($e \\approx 2.718$). It grows or decays very fast."),
    (r'\\frac',      "↑ This fraction: divide the top (numerator) by the bottom (denominator)."),
    (r'\\binom',     "↑ $\\binom{n}{k}$ = 'n choose k' — ways to pick $k$ items from $n$."),
    (r'\\partial',   "↑ ∂ is a partial derivative — how the function changes when only ONE variable changes."),
    (r'j.*\\omega|\\omega.*j', "↑ $j = \\sqrt{-1}$. $j\\omega$ represents a pure oscillation at frequency $\\omega$."),
    (r'\\nabla',     "↑ ∇ (nabla/gradient) points in the direction of steepest increase."),
    (r'\\sqrt',      "↑ $\\sqrt{x}$ is the square root — the value that, squared, gives $x$."),
]


def _formula_hint(latex_line: str) -> str:
    for pattern, hint in _FORMULA_HINTS:
        if re.search(pattern, latex_line):
            return hint
    return ""


# ─── Exam tips ────────────────────────────────────────────────────────────────
def _exam_tip(heading: str, body: str) -> str:
    h, b = heading.lower(), body.lower()
    if re.search(r"theorem|transform|law|series|property", h + " " + b):
        return "State the theorem/definition precisely — examiners award marks for exact wording."
    if re.search(r"deriv|proof|show that|prove", b):
        return "Reproduce the derivation step-by-step — partial credit for each correct intermediate step."
    if re.search(r"formula|equation|expression|given by", b):
        return "Memorise the formula with all variable definitions — numerical application problems are very common."
    if re.search(r"condition|constraint|valid|converge|region|require", b):
        return "Know and state ALL conditions/constraints — often worth 1–2 dedicated marks."
    if re.search(r"application|used in|practical|real.world", b):
        return "Know at least 2–3 real-world applications — a common short-answer question."
    return "Write the formal definition first, then explain it in your own words, then give a worked example."


# ─── Math block formatter ─────────────────────────────────────────────────────
def _math_block(raw_line: str) -> str:
    """Emit a display math block with proper blank-line padding for remark-math."""
    latex = _raw_to_latex(raw_line)
    return f"\n$$\n{latex}\n$$\n"
