"""schemas.py — all Pydantic request/response models for AuraGraph."""
from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field, model_validator


class AuthRequest(BaseModel):
    """Login / register request.

    Accepts either `email` or `username`; `identifier` is computed automatically.
    Uses a `model_validator` instead of `@property` so Pydantic v2 sees it properly.
    """
    email:    Optional[str] = None
    username: Optional[str] = None
    name:     Optional[str] = None
    password: str = Field(..., min_length=8, max_length=128)

    # Computed — not sent by the client; populated by the validator below.
    identifier: str = Field(default="", init=False)

    @model_validator(mode="after")
    def _resolve_identifier(self) -> "AuthRequest":
        self.identifier = (self.email or self.username or "").strip()
        return self


class FusionResponse(BaseModel):
    fused_note:      str
    source:          str = "azure"
    fallback_reason: Optional[str] = None
    chunks_stored:   Optional[dict] = None


class DoubtRequest(BaseModel):
    notebook_id: str
    doubt:       str = Field(..., min_length=1, max_length=2000)
    page_idx:    int = 0


class DoubtResponse(BaseModel):
    answer:              str
    source:              str = "azure"
    verification_status: str = "correct"
    correction:          str = ""
    footnote:            str = ""


class MutationRequest(BaseModel):
    notebook_id:        str
    doubt:              str = Field(..., min_length=1, max_length=2000)
    page_idx:           int = 0
    original_paragraph: Optional[str] = Field(default=None, max_length=8000)


class MutationResponse(BaseModel):
    mutated_paragraph: str
    concept_gap:       str
    answer:            str = ""
    page_idx:          int
    source:            str = "azure"
    can_mutate:        bool = True


class RegenerateSectionRequest(BaseModel):
    notebook_id:   str
    page_idx:      int
    proficiency:   str = "Practitioner"
    custom_prompt: Optional[str] = Field(default=None, max_length=500)


class RegenerateSectionResponse(BaseModel):
    new_section: str
    page_idx:    int
    source:      str


class ExaminerRequest(BaseModel):
    concept_name:       str
    notebook_id:        Optional[str] = None
    custom_instruction: Optional[str] = None


class ExaminerResponse(BaseModel):
    practice_questions: str


class ConceptPracticeRequest(BaseModel):
    concept_name:       str
    level:              str = "partial"
    notebook_id:        Optional[str] = None
    custom_instruction: Optional[str] = None


class ConceptPracticeResponse(BaseModel):
    questions: list


class SniperExamRequest(BaseModel):
    notebook_id: Optional[str] = None
    weak_concepts: Optional[list[str]] = None


class SniperExamResponse(BaseModel):
    questions:       list
    concepts_tested: list


class GeneralExamRequest(BaseModel):
    notebook_id: Optional[str] = None
    all_concepts: Optional[list[str]] = None


class GeneralExamResponse(BaseModel):
    questions:       list
    concepts_tested: list


class NodeUpdateRequest(BaseModel):
    concept_name: str
    status:       str


class ConceptExtractRequest(BaseModel):
    note:        str
    notebook_id: Optional[str] = None


class NotebookCreateRequest(BaseModel):
    name:   str = Field(..., min_length=1, max_length=120)
    course: str = Field(default="", max_length=120)


class NotebookUpdateRequest(BaseModel):
    note:        str
    proficiency: Optional[str] = None


class FusionRequest(BaseModel):
    slide_summary:      str
    textbook_paragraph: str
    proficiency:        str = "Practitioner"
    notebook_id:        Optional[str] = None
