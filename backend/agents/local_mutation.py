"""
Local (offline) Mutation — AuraGraph fallback
Rewrites a paragraph when Azure OpenAI is unavailable.

Strategy:
  1. Parse what the student is confused about from their doubt
  2. Add an explicit note addressing the doubt directly to the paragraph
  3. Highlight the key concept and add a plain-language clarification block
  4. Return a structured mutation result
"""
import re
import json


# ── Concept-gap heuristics ────────────────────────────────────────────────────
_CONFUSION_KEYWORDS = {
    "why": "The student is unclear about the reasoning or motivation behind this concept.",
    "what": "The student needs a clearer definition of the concept.",
    "how": "The student needs a step-by-step explanation of the mechanism.",
    "don't understand": "There is a fundamental conceptual gap requiring a re-explanation.",
    "didnt get": "The explanation needs to be rephrased with a concrete example.",
    "still don": "The previous explanation lacked sufficient depth or an intuitive analogy.",
    "confused": "The explanation lacks sufficient clarity or an intuitive analogy.",
    "difference": "The student cannot distinguish between two related concepts.",
    "relation": "The student needs an explicit comparison showing how the two concepts connect.",
    "when": "The student is uncertain about the conditions for applying this concept.",
    "prove": "The student requires a derivation or proof of the stated result.",
    "example": "An illustrative worked example would resolve the confusion.",
    "intuitively": "The student needs an intuitive (non-mathematical) explanation.",
    "intuition": "The student needs an intuitive (non-mathematical) explanation.",
}


def _diagnose_gap(doubt: str) -> str:
    doubt_lower = doubt.lower()
    # Check topic-specific concepts first (before generic question words)
    topic_keywords = {
        "convolution": "The student needs an intuitive explanation of what convolution computes.",
        "fourier": "The student needs to understand frequency decomposition conceptually.",
        "laplace": "The student needs to understand why/how Laplace generalises Fourier.",
        "z-transform": "The student needs to understand the discrete-time analogue of Laplace.",
        "binomial": "The student cannot distinguish between Binomial's parameters and meaning.",
        "bernoulli": "The student needs a clearer definition of a Bernoulli trial.",
        "poisson": "The student doesn't know when to apply Poisson vs Binomial.",
        "variance": "The student confuses variance with standard deviation or mean.",
        "eigenvalue": "The student needs a geometric intuition for eigenvalues.",
        "matrix": "The student needs to understand the matrix operation conceptually.",
        "integral": "The student needs a geometric interpretation of integration.",
        "derivative": "The student needs the instantaneous-rate-of-change intuition.",
    }
    for keyword, diagnosis in topic_keywords.items():
        if keyword in doubt_lower:
            return diagnosis
    # Fall back to generic question words
    for keyword, diagnosis in _CONFUSION_KEYWORDS.items():
        if keyword in doubt_lower:
            return diagnosis
    return "The student requires additional context and an intuitive explanation of this concept."



# ── Simple paragraph rewriter ─────────────────────────────────────────────────
def _build_analogy_hint(doubt: str) -> str:
    """Return a short analogy/clarification sentence based on the doubt."""
    dl = doubt.lower()

    # ── Probability & Statistics ──────────────────────────────────────────────
    if "bernoulli" in dl and ("binomial" in dl or "relation" in dl):
        return ("Binomial is just n independent Bernoulli trials counted together: "
                "if each coin flip is Bernoulli(p), then counting how many Heads in n flips is Binomial(n,p). "
                "Bernoulli = one trial; Binomial = n trials.")
    if "bernoulli" in dl:
        return ("A Bernoulli trial is the simplest random experiment: only two outcomes — "
                "success (probability p) or failure (probability 1−p). "
                "Think of a single biased coin flip.")
    if "binomial" in dl:
        return ("Binomial(n,p) counts the number of successes in n independent Bernoulli trials. "
                "P(X=k) = C(n,k)·pᵏ·(1−p)ⁿ⁻ᵏ — choose k positions for successes, "
                "multiply the probability of each arrangement.")
    if "negative binomial" in dl:
        return ("Negative Binomial asks: how many trials until the r-th success? "
                "Unlike Binomial (fixed n, random successes), here successes are fixed and trials are random.")
    if "geometric" in dl and "distribution" in dl:
        return ("Geometric distribution models the number of trials until the first success. "
                "It has the memoryless property: past failures don't affect future probability.")
    if "poisson" in dl:
        return ("Poisson(λ) models rare events in a fixed interval — e.g. calls per hour. "
                "It is the limit of Binomial(n,p) as n→∞, p→0, np=λ.")
    if "pmf" in dl or "probability mass" in dl:
        return ("A PMF lists the exact probability for each discrete value X can take. "
                "All PMF values are ≥0 and must sum to 1.")
    if "pdf" in dl or "probability density" in dl:
        return ("A PDF gives probability density — you need to integrate over a range to get a probability. "
                "P(a≤X≤b) = ∫ f(x) dx from a to b.")
    if "cdf" in dl or "cumulative" in dl:
        return ("CDF F(x) = P(X ≤ x). It is non-decreasing from 0 to 1. "
                "For discrete distributions, it's a staircase; for continuous, a smooth S-curve.")
    if "expectation" in dl or "expected value" in dl or "mean" in dl:
        return ("Expected value is the probability-weighted average outcome. "
                "Think of it as the long-run average if you repeated the experiment infinitely many times.")
    if "variance" in dl or "standard deviation" in dl:
        return ("Variance measures how spread out values are around the mean. "
                "Var(X) = E[X²] − (E[X])². A small variance means outcomes cluster tightly around the mean.")
    if "mgf" in dl or "moment generating" in dl:
        return ("The MGF M(t) = E[eᵗˣ] encodes all moments of X. "
                "The k-th moment = M⁽ᵏ⁾(0). MGFs also uniquely identify distributions and are useful for sums of independent RVs.")
    if "memoryless" in dl:
        return ("Memoryless means P(X>m+n | X>n) = P(X>m): knowing you've waited n steps gives no information "
                "about remaining wait time. Only Geometric (discrete) and Exponential (continuous) have this property.")
    if "independent" in dl and ("random" in dl or "variable" in dl or "trial" in dl):
        return ("Independence means knowing the outcome of one variable gives no information about the other. "
                "For events: P(A∩B) = P(A)·P(B). For RVs: the joint PMF/PDF factors as a product.")
    if "relation" in dl or "difference" in dl or "distinguish" in dl:
        return ("When comparing two distributions, focus on: (1) what is random (successes vs trials), "
                "(2) parameter meaning, and (3) when each one is the right model to pick.")

    # ── Signals & Systems ─────────────────────────────────────────────────────
    if "convolution" in dl or "conv" in dl:
        return ("Think of it as sliding a 'weighing window' across a signal: "
                "at each position you compute a weighted sum of overlapping values.")
    if "fourier" in dl or "frequency" in dl or "spectrum" in dl:
        return ("The Fourier Transform decomposes a signal into its constituent frequencies, "
                "much like a musical chord being split into individual notes.")
    if "laplace" in dl:
        return ("The Laplace Transform generalises the Fourier Transform by adding a "
                "decay factor, allowing analysis of signals that do not naturally converge.")
    if "z-transform" in dl or "z transform" in dl:
        return ("The Z-Transform is the discrete-time counterpart of the Laplace Transform — "
                "replacing continuous exponentials with powers of a complex variable z.")

    # ── Calculus ─────────────────────────────────────────────────────────────
    if "differential" in dl or "derivative" in dl:
        return ("Think of a derivative as measuring the instantaneous slope — "
                "how quickly the quantity is changing at a single point.")
    if "integral" in dl or "integration" in dl:
        return ("Integration accumulates the area under a curve, "
                "aggregating infinitely many infinitely thin slices into a total sum.")

    # ── Linear Algebra ────────────────────────────────────────────────────────
    if "matrix" in dl or "eigen" in dl:
        return ("An eigenvector is a special direction that a transformation only stretches "
                "or shrinks, never rotates — its scaling factor is the eigenvalue.")

    # Generic fallback — use the doubt's key noun for a targeted hint
    key_nouns = [w for w in dl.split() if len(w) > 4 and w.isalpha()]
    noun_hint = f" Focus specifically on what '{key_nouns[0]}' means in this context." if key_nouns else ""
    return ("To build intuition: try to identify a real-world analogy "
            f"or work through the smallest possible concrete example first.{noun_hint}")


def _extract_heading(body: str) -> tuple[str, str]:
    """Return (heading_line, rest_of_body) splitting off the first ## heading if present."""
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("## ") or line.startswith("# "):
            heading = line
            rest = "\n".join(lines[i + 1:]).strip()
            return heading, rest
    return "", body


def local_mutate(original_paragraph: str, student_doubt: str) -> tuple[str, str]:
    """
    Returns (mutated_paragraph, concept_gap_diagnosis).
    Works entirely offline without any API calls.
    Produces a genuine rewrite: preserves the original heading, inserts an intuition
    block up-front, then restates the original content below.
    """
    concept_gap = _diagnose_gap(student_doubt)
    analogy = _build_analogy_hint(student_doubt)

    body = original_paragraph.strip()
    heading, rest = _extract_heading(body)

    # Build intuition/clarification block
    insight_block = (
        f"> 💡 **Intuition (re: \"_{student_doubt.strip()}_\"):** "
        f"{analogy} "
        f"_{concept_gap}_"
    )

    # Reconstruct: heading → insight block → original body
    if heading:
        mutated = f"{heading}\n\n{insight_block}\n\n{rest}"
    else:
        mutated = f"{insight_block}\n\n{rest}"

    return mutated, concept_gap
