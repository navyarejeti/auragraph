"""
Local (offline) Examiner — AuraGraph fallback
Generates practice MCQs for a concept when Azure OpenAI is unavailable.

Maintains a question bank keyed by concept keywords.
Falls back to generic comprehension questions when no keyword matches.
"""
import re
from typing import List, Tuple


# ── Question bank ─────────────────────────────────────────────────────────────
# Format: { keyword: [(question, [A,B,C,D], correct_letter, explanation), ...] }
_QUESTION_BANK: dict[str, list[tuple]] = {
    "fourier": [
        (
            "What does the Fourier Transform convert a signal from?",
            ["A) Frequency domain to spatial domain",
             "B) Time domain to frequency domain",
             "C) Spatial domain to time domain",
             "D) Amplitude domain to phase domain"],
            "B",
            "The Fourier Transform maps a time-domain signal to its frequency-domain representation.",
        ),
        (
            "Which property of the Fourier Transform states that time-domain convolution equals frequency-domain multiplication?",
            ["A) Linearity property",
             "B) Duality property",
             "C) Convolution theorem",
             "D) Parseval's theorem"],
            "C",
            "The Convolution Theorem is the key property linking convolution in time and multiplication in frequency.",
        ),
        (
            "What is the Fourier Transform of a Dirac delta function δ(t)?",
            ["A) Zero for all frequencies",
             "B) A constant (1) for all frequencies",
             "C) A sinusoidal function",
             "D) An impulse at ω = 0"],
            "B",
            "The Dirac delta is 1 everywhere in the frequency domain because it contains all frequencies equally.",
        ),
    ],
    "convolution": [
        (
            "What operation does convolution perform on two signals?",
            ["A) Pointwise multiplication",
             "B) Integration of the product of one signal with the time-reversed and shifted version of another",
             "C) Addition of two signals",
             "D) Differentiation of the product of two signals"],
            "B",
            "Convolution integrates the overlap between one signal and the flipped, shifted version of the second.",
        ),
        (
            "Why is h(t-τ) in the convolution integral flipped and shifted?",
            ["A) To make the integral converge faster",
             "B) To compute the weighted overlap as the 'window' slides across the input",
             "C) Because the Laplace Transform requires it",
             "D) To ensure causality"],
            "B",
            "Flipping h and shifting it creates a sliding window that computes the weighted overlap at each time instant.",
        ),
        (
            "Which system property is most directly characterised by convolution?",
            ["A) Non-linear systems",
             "B) Time-varying systems",
             "C) Linear Time-Invariant (LTI) systems",
             "D) Causal non-LTI systems"],
            "C",
            "Convolution is the fundamental tool for analysing LTI systems via their impulse response.",
        ),
    ],
    "laplace": [
        (
            "What is the main advantage of the Laplace Transform over the Fourier Transform?",
            ["A) It can only analyse stable systems",
             "B) It handles signals that grow exponentially and analyses transient responses",
             "C) It is faster to compute numerically",
             "D) It works only in discrete time"],
            "B",
            "The Laplace Transform introduces the complex variable s = σ + jω, allowing analysis of growing/decaying signals.",
        ),
        (
            "What is the region of convergence (ROC) in the Laplace Transform?",
            ["A) The set of frequencies where the signal is periodic",
             "B) The set of complex s values for which the Laplace integral converges",
             "C) The time interval over which the signal exists",
             "D) The amplitude range of the signal"],
            "B",
            "The ROC defines the valid domain of s for which the integral ∫x(t)e^{-st}dt is finite.",
        ),
        (
            "What does a pole in the s-domain indicate about a system?",
            ["A) A frequency where the output is always zero",
             "B) A value of s that makes the transfer function infinite — related to system modes",
             "C) The bandwidth of the system",
             "D) A point where the signal is maximum"],
            "B",
            "Poles determine the natural modes of a system; their location in the left/right half-plane indicates stability.",
        ),
    ],
    "z-transform": [
        (
            "The Z-Transform is the discrete-time equivalent of which transform?",
            ["A) Fourier Transform",
             "B) Wavelet Transform",
             "C) Laplace Transform",
             "D) Hilbert Transform"],
            "C",
            "The Z-Transform generalises the Discrete-Time Fourier Transform, analogous to how Laplace generalises the continuous FT.",
        ),
        (
            "If a system's poles all lie strictly inside the unit circle in the z-plane, it is:",
            ["A) Unstable",
             "B) Marginally stable",
             "C) BIBO stable",
             "D) Non-causal"],
            "C",
            "The BIBO stability criterion for discrete systems requires all poles to be strictly inside the unit circle (|z| < 1).",
        ),
        (
            "What property links time-domain convolution to the Z-domain?",
            ["A) Time-shifting property",
             "B) Convolution theorem — convolution in z-domain becomes multiplication",
             "C) Initial value theorem",
             "D) Parseval's theorem"],
            "B",
            "Just as with the Laplace Transform, time-domain convolution corresponds to multiplication of Z-transforms.",
        ),
    ],
    "lti": [
        (
            "What are the two defining properties of an LTI system?",
            ["A) Causality and stability",
             "B) Linearity (superposition) and time-invariance",
             "C) Memory and invertibility",
             "D) Continuity and differentiability"],
            "B",
            "LTI systems obey superposition (linear) and their behaviour does not change with time (time-invariant).",
        ),
        (
            "The output of an LTI system to any input x(t) can be expressed as:",
            ["A) The Fourier Transform of x(t)",
             "B) The convolution of x(t) with the system's impulse response h(t)",
             "C) The derivative of x(t)",
             "D) The integral of x(t) alone"],
            "B",
            "Convolution y(t) = x(t) * h(t) completely characterises an LTI system via its impulse response h(t).",
        ),
    ],
}

# Generic fallback questions
_GENERIC_QUESTIONS = [
    (
        "Which of the following best describes the purpose of a mathematical transform in signal processing?",
        ["A) To amplify signals",
             "B) To convert a signal into another domain where analysis is simpler",
             "C) To encrypt data",
             "D) To generate new signals from noise"],
        "B",
        "Transforms change the representation of a signal to a domain (e.g., frequency) that reveals useful properties.",
    ),
    (
        "What is a key benefit of frequency-domain analysis of signals?",
        ["A) It eliminates noise automatically",
             "B) It reveals the spectral composition and allows simpler filtering operations",
             "C) It reduces computational complexity in all cases",
             "D) It makes signals time-invariant"],
        "B",
        "In the frequency domain, filtering becomes multiplication rather than convolution, greatly simplifying analysis.",
    ),
    (
        "Which property allows the output of a linear system to be decomposed using superposition?",
        ["A) Time-invariance",
             "B) Causality",
             "C) Linearity",
             "D) Stability"],
        "C",
        "Linearity (superposition) means the response to a sum of inputs equals the sum of individual responses.",
    ),
]


def _match_concept(concept_name: str) -> list[tuple]:
    cl = concept_name.lower()
    for key, questions in _QUESTION_BANK.items():
        if key in cl:
            return questions
    return _GENERIC_QUESTIONS


def _format_questions(questions: list[tuple], concept_name: str) -> str:
    lines = [f"**Practice Questions: {concept_name}**\n"]
    for i, (q_text, options, correct, explanation) in enumerate(questions[:5], 1):
        lines.append(f"**Q{i}.** {q_text}")
        for opt in options:
            letter = opt[0]  # 'A', 'B', 'C', 'D'
            marker = " ✅" if letter == correct else ""
            lines.append(f"{opt}{marker}")
        lines.append(f"> 💡 **Explanation:** {explanation}")
        lines.append("")
    return "\n".join(lines).strip()


def local_examine(concept_name: str) -> str:
    """
    Returns a formatted string of 3 MCQs for the given concept.
    Works entirely offline without any API calls.
    """
    questions = _match_concept(concept_name)
    return _format_questions(questions, concept_name)
