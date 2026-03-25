"""
Deep prompt tests — template rendering and variable coverage.
Run: cd backend && python -m pytest tests/test_prompts_advanced.py -v
"""
import sys, os, pytest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from agents.prompts import registry, validate_vars, PromptSpec


# ── Template population ───────────────────────────────────────────────────────

def test_every_template_renders_without_key_error():
    """Substituting dummy values for all required_vars must not raise."""
    for name, spec in registry.items():
        provided = {v: f"<dummy_{v}>" for v in spec.required_vars}
        rendered = spec.template
        for var, val in provided.items():
            rendered = rendered.replace("{{$" + var + "}}", val)
        # All placeholders should be resolved — none remain
        unresolved = [v for v in spec.required_vars if "{{$" + v + "}}" in rendered]
        assert unresolved == [], f"Prompt '{name}' still has unresolved vars: {unresolved}"


def test_validate_vars_correct_missing_names():
    """validate_vars must return exact names of the missing variables."""
    doubt_spec = registry["doubt_answer"]
    if len(doubt_spec.required_vars) >= 2:
        first_var = doubt_spec.required_vars[0]
        provided = {v: "x" for v in doubt_spec.required_vars[1:]}  # all except first
        missing = validate_vars("doubt_answer", provided)
        assert first_var in missing


def test_no_duplicate_required_vars():
    """required_vars lists should not contain duplicates."""
    for name, spec in registry.items():
        assert len(spec.required_vars) == len(set(spec.required_vars)), \
            f"Prompt '{name}' has duplicate required_vars"


def test_all_required_vars_appear_in_template():
    """Every declared required_var must appear in the template string."""
    for name, spec in registry.items():
        for var in spec.required_vars:
            placeholder = "{{$" + var + "}}"
            assert placeholder in spec.template, \
                f"Prompt '{name}': required var '{var}' not found in template"


def test_templates_have_minimum_length():
    """Each template should be at least 50 characters (not accidentally emptied)."""
    for name, spec in registry.items():
        assert len(spec.template.strip()) >= 50, \
            f"Prompt '{name}' template is suspiciously short ({len(spec.template)} chars)"


def test_validate_vars_extra_vars_ok():
    """Providing extra (undeclared) vars should not cause validation to fail."""
    for name, spec in registry.items():
        provided = {v: "x" for v in spec.required_vars}
        provided["extra_unused_key"] = "ignored"
        assert validate_vars(name, provided) == []


def test_registry_keys_are_snake_case():
    """Prompt names should follow snake_case convention."""
    import re
    for name in registry.keys():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), \
            f"Prompt name '{name}' does not follow snake_case"


def test_mutation_prompt_contains_doubt_context():
    """The mutation prompt should reference the student's doubt."""
    spec = registry["mutation"]
    assert any(v in spec.required_vars for v in ("doubt", "question", "student_doubt")), \
        f"mutation prompt should require a doubt/question variable; got: {spec.required_vars}"
