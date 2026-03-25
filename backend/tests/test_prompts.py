"""Tests for agents/prompts.py — run: cd backend && python -m pytest tests/test_prompts.py -v"""
import sys, os, pytest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from agents.prompts import registry, validate_vars, PromptSpec

EXPECTED_PROMPTS = {"doubt_answer", "mutation", "note_self_review", "verification", "examiner"}

def test_registry_has_all_prompts():
    assert EXPECTED_PROMPTS.issubset(set(registry.keys()))

def test_each_prompt_is_promptspec():
    for name, spec in registry.items():
        assert isinstance(spec, PromptSpec), f"{name} is not a PromptSpec"

def test_each_prompt_has_template():
    for name, spec in registry.items():
        assert spec.template.strip(), f"{name}.template is empty"

def test_each_prompt_has_required_vars():
    for name, spec in registry.items():
        assert isinstance(spec.required_vars, list), f"{name}.required_vars is not a list"

def test_validate_vars_no_missing():
    doubt_spec = registry["doubt_answer"]
    provided = {v: "dummy" for v in doubt_spec.required_vars}
    missing = validate_vars("doubt_answer", provided)
    assert missing == []

def test_validate_vars_detects_missing():
    doubt_spec = registry["doubt_answer"]
    if doubt_spec.required_vars:
        missing = validate_vars("doubt_answer", {})
        assert len(missing) == len(doubt_spec.required_vars)

def test_validate_vars_unknown_prompt():
    with pytest.raises((KeyError, ValueError)):
        validate_vars("nonexistent_prompt_xyz", {})

def test_mutation_template_contains_rewrite():
    spec = registry["mutation"]
    assert "rewrite" in spec.template.lower() or "REWRITE" in spec.template

def test_doubt_answer_template_vars():
    spec = registry["doubt_answer"]
    for var in spec.required_vars:
        placeholder = "{{$" + var + "}}"
        assert placeholder in spec.template, (
            f"Required var {var!r} not found as '{placeholder}' in template. "
            f"Template snippet: {spec.template[:200]!r}"
        )
