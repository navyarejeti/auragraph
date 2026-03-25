"""routers/fuse.py — file upload, SSE streaming note generation, legacy /api/fuse."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Optional, List

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

import deps
from deps import (
    get_current_user, _require_notebook_owner,
    _is_azure_available, _is_groq_available,
    _check_llm_rate_limit, _record_llm_call,
    _verify_note, _inject_figures_into_sections, _match_image_to_topic,
    _note_to_pages, _format_chunks_for_prompt,
    MAX_TOTAL_UPLOAD_BYTES, PIPELINE_TIMEOUT_S,
    _PROMPT_SLIDES_BUDGET, _PROMPT_TEXTBOOK_BUDGET,
)
from schemas import FusionResponse, FusionRequest

logger = logging.getLogger("auragraph")
router = APIRouter(tags=["fuse"])
_IMAGE_DESC_TIMEOUT_S = 15.0

# ── File type validation ───────────────────────────────────────────────────────
_ALLOWED_EXTENSIONS = frozenset({
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tiff", ".bmp",
})

def _validate_upload(upload: UploadFile) -> None:
    """Reject any file whose extension is not in the allow-list."""
    fname = (upload.filename or "").lower()
    if not any(fname.endswith(ext) for ext in _ALLOWED_EXTENSIONS):
        raise HTTPException(
            415,
            f"Unsupported file type: '{upload.filename}'. "
            f"Allowed types: PDF and image files (PNG, JPG, WEBP, TIFF, BMP)."
        )


def _renumber_pages(text: str, offset: int) -> tuple[str, int]:
    """
    Renumber every '--- Page N ---' and '--- Slide N ---' marker in *text* so
    that page/slide numbers are globally unique across multiple uploaded files.

    Without this, every PDF resets to '--- Page 1 ---' and every PPTX resets
    to '--- Slide 1 ---'. The bipartite safety union in slide_analyzer.py then
    compares source pages {1,2,3,4} against LLM-covered pages {1,2,3,4} —
    collision hides the fact that 14 distinct pages exist across 4 files, and
    nothing is ever rescued.

    Returns (renumbered_text, number_of_pages_found_in_this_file).
    """
    max_local = 0

    def _replace(m: re.Match) -> str:
        nonlocal max_local
        prefix = m.group(1)   # "Page" or "Slide"
        n = int(m.group(2))
        if n > max_local:
            max_local = n
        return f"--- {prefix} {offset + n} ---"

    new_text = re.sub(r'---\s*(Page|Slide)\s+(\d+)\s*---', _replace, text)
    return new_text, max_local




@router.post("/api/upload-fuse-multi", response_model=FusionResponse)
async def upload_fuse_multi(
    slides_pdfs:   List[UploadFile] = File(...),
    textbook_pdfs: Optional[List[UploadFile]] = File(default=None),
    proficiency:   str = Form("Practitioner"),
    notebook_id:   str = Form(""),
    authorization: Optional[str] = Header(None),
):
    """Full 8-step semantic pipeline: extract → chunk → embed → analyse → retrieve → generate → verify → persist."""
    from agents.pdf_utils import extract_text_from_file, chunk_text
    from agents.knowledge_store import store_source_chunks, store_note_pages
    from agents.notebook_store import update_notebook_note
    from agents.local_summarizer import generate_local_note
    from agents.slide_images import extract_images_from_file, save_images
    from agents.image_ocr import describe_slide_image, is_image_file
    from agents.latex_utils import fix_latex_delimiters
    from pipeline.chunker import chunk_textbook
    from pipeline.embedder import Embedder
    from pipeline.vector_db import VectorDB
    from pipeline.slide_analyzer import analyse_slides
    from pipeline.topic_retriever import TopicRetriever
    from pipeline.note_generator import run_generation_pipeline, _fix_tables

    user = get_current_user(authorization)
    _check_llm_rate_limit(user["id"])
    if notebook_id:
        _require_notebook_owner(notebook_id, user)

    all_slides_text, all_textbook_text = "", ""
    all_slide_images, all_textbook_images, textbook_figures_items = [], [], []
    extraction_errors: list[str] = []
    _total_bytes = 0
    _global_page_offset = 0   # Global page counter across all uploaded slide files

    for upload in slides_pdfs:
        _validate_upload(upload)          # FIX: reject non-PDF/image uploads
        raw = await upload.read()
        fname = upload.filename or "slides.pdf"
        _total_bytes += len(raw)
        if _total_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(413, f"Total upload exceeds {MAX_TOTAL_UPLOAD_BYTES // 1024 // 1024} MB.")
        pages_in_file = 0  # will be set by _renumber_pages; init here so image block can safely reference it
        try:
            marker = f"\n\n{'='*60}\n=== FILE: {fname} ===\n{'='*60}\n\n"
            extracted = (await asyncio.to_thread(extract_text_from_file, raw, fname)
                         if is_image_file(fname)
                         else extract_text_from_file(raw, fname))
            # Renumber pages globally so each page has a unique number across all files.
            # Without this, every PDF resets to Page 1 and the bipartite safety union
            # is blind to inter-file coverage gaps.
            extracted, pages_in_file = _renumber_pages(extracted, _global_page_offset)
            _global_page_offset += pages_in_file
            all_slides_text += marker + extracted + "\n\n"
        except ValueError as e:
            extraction_errors.append(f"{fname}: {e}")
        try:
            if not is_image_file(fname):
                file_imgs = extract_images_from_file(raw, fname)
                # Apply the same page offset used by _renumber_pages so that
                # source_label (e.g. "Page 3") matches the renumbered marker
                # (e.g. "--- Page 7 ---") when multiple files are uploaded.
                offset_before = _global_page_offset - pages_in_file if pages_in_file else 0
                for img in file_imgs:
                    img.source_label = re.sub(
                        r'^(Page|Slide)\s+(\d+)$',
                        lambda m: f"{m.group(1)} {int(m.group(2)) + offset_before}",
                        img.source_label,
                    )
                all_slide_images.extend(file_imgs)
        except Exception as e:
            logger.warning("Image extraction failed %s: %s", fname, e)

    for upload in (textbook_pdfs or []):
        raw = await upload.read()
        fname = upload.filename or "textbook.pdf"
        _total_bytes += len(raw)
        if _total_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(413, f"Total upload exceeds {MAX_TOTAL_UPLOAD_BYTES // 1024 // 1024} MB.")
        try:
            extracted = (await asyncio.to_thread(extract_text_from_file, raw, fname)
                         if is_image_file(fname)
                         else extract_text_from_file(raw, fname))
            all_textbook_text += extracted + "\n\n"
        except ValueError as e:
            extraction_errors.append(f"{fname}: {e}")
        try:
            if not is_image_file(fname):
                tb_imgs = extract_images_from_file(raw, fname)
                for img in tb_imgs:
                    img.img_id       = f"tb_{img.img_id}"
                    img.source_label = f"Textbook — {img.source_label}"
                all_textbook_images.extend(tb_imgs)
        except Exception:
            pass

    if not all_slides_text.strip() and not all_textbook_text.strip():
        raise HTTPException(422, "Could not extract text from any uploaded files. " + "; ".join(extraction_errors))

    # Step 1b — describe + annotate images (must happen before chunking)
    # Description + text annotation always runs regardless of notebook_id.
    if all_slide_images:
        async def _desc(img):
            try:
                img.description = await asyncio.wait_for(
                    asyncio.to_thread(describe_slide_image, img.data, img.source_label),
                    timeout=_IMAGE_DESC_TIMEOUT_S,
                )
            except Exception:
                img.description = f"Figure from {img.source_label}"
        await asyncio.gather(*[_desc(img) for img in all_slide_images])
        if notebook_id:
            try:
                save_images(notebook_id, all_slide_images, clear_existing=True)
            except Exception as e:
                logger.warning("save_images failed for slide images: %s", e)
        for img in all_slide_images:
            pat = re.compile(r'(---\s*' + re.escape(img.source_label) + r'\b[^\n]*---)', re.IGNORECASE)
            all_slides_text = pat.sub(
                lambda m, ann=f"\n[Figure: {img.description}]": m.group(0) + ann,
                all_slides_text, count=1,
            )

    if all_textbook_images and notebook_id:
        async def _desc_tb(img):
            try:
                img.description = await asyncio.wait_for(
                    asyncio.to_thread(describe_slide_image, img.data, img.source_label),
                    timeout=_IMAGE_DESC_TIMEOUT_S,
                )
            except Exception:
                img.description = f"Figure from {img.source_label}"
        await asyncio.gather(*[_desc_tb(img) for img in all_textbook_images])
        try:
            save_images(notebook_id, all_textbook_images, clear_existing=False)
            for img in all_textbook_images:
                ext = img.mime.split("/")[-1].replace("jpeg", "jpg")
                textbook_figures_items.append((img, f"/api/images/{notebook_id}/{img.img_id}.{ext}"))
        except Exception:
            all_textbook_images = []

    # Step 2 — chunk + knowledge store
    slide_raw_chunks    = chunk_text(all_slides_text,   max_chars=4000)
    textbook_raw_chunks = chunk_text(all_textbook_text, max_chars=4000)
    textbook_hash       = hashlib.md5(all_textbook_text.encode()).hexdigest()[:16]
    chunks_stored       = None
    if notebook_id:
        try:
            chunks_stored = store_source_chunks(
                nb_id=notebook_id,
                slide_chunks=slide_raw_chunks,
                textbook_chunks=textbook_raw_chunks,
                textbook_hash=textbook_hash,
            )
        except Exception as e:
            logger.warning("Knowledge store write failed: %s", e)

    # Step 2b — semantic chunking
    textbook_semantic_chunks = []
    if all_textbook_text.strip():
        try:
            textbook_semantic_chunks = chunk_textbook(all_textbook_text)
        except Exception as e:
            logger.warning("Textbook semantic chunking failed: %s", e)

    # Step 3 — embed
    embedder, vector_db = Embedder(), VectorDB()
    if textbook_semantic_chunks:
        try:
            loaded = bool(notebook_id) and vector_db.load(notebook_id, expected_hash=textbook_hash)
            if loaded:
                embedder.rebuild_from_chunks(vector_db.chunks)
            else:
                embedder.embed_chunks(textbook_semantic_chunks)
                vector_db.add_chunks(textbook_semantic_chunks)
                if notebook_id: vector_db.add_to_azure(notebook_id, textbook_semantic_chunks)
                if notebook_id:
                    vector_db.save(notebook_id, textbook_hash=textbook_hash)
        except Exception as e:
            logger.warning("Embedding failed: %s", e)

    # Step 4 — slide analysis
    topics = []
    try:
        topics = await analyse_slides(all_slides_text)
    except Exception as e:
        logger.warning("Slide analysis failed: %s", e)

    # Step 5 — retrieval
    topic_contexts: dict[str, str] = {}
    if topics and vector_db.size > 0:
        try:
            retriever      = TopicRetriever(vector_db, embedder)
            topic_contexts = retriever.retrieve_all_topics(topics, nb_id=notebook_id or "")
        except Exception as e:
            logger.warning("Topic retrieval failed: %s", e)

    # Step 5b — match textbook figures to topics
    if textbook_figures_items and topics:
        for img, img_url in textbook_figures_items:
            best = _match_image_to_topic(img.description, topics)
            if best is not None:
                ref = f"\n\n[Textbook Figure: {img.description}]\n![{img.description}]({img_url})"
                topic_contexts[best] = topic_contexts.get(best, "") + ref

    # Step 5c — inline figure map (same logic as stream endpoint — see comments there)
    topic_figures: dict[str, list] = {}
    if topics:
        for img in all_slide_images:
            img_url = (
                f"/api/images/{notebook_id}/{img.img_id}."
                + img.mime.split("/")[-1].replace("jpeg", "jpg")
            ) if notebook_id else ""

            label_pat = re.compile(
                r'---\s*' + re.escape(img.source_label) + r'\b[^\n]*---',
                re.IGNORECASE,
            )
            primary_match = None
            primary_idx   = None
            for idx, t in enumerate(topics):
                if label_pat.search(t.slide_text):
                    primary_match = t.topic
                    primary_idx   = idx
                    break

            # --- Spatial + semantic override ---
            # source_label page match gives us the page, but a single page can
            # contain multiple topics (e.g. Page 1 has "Measurable Functions" and
            # "Function of a Random Variable", with the diagram under the second).
            #
            # PRIMARY FIX — spatial locality in slide text:
            # The [Figure: ...] annotation is injected right after its page marker.
            # The slide text for that page preserves all section headings in order.
            # The last heading that appears BEFORE the [Figure:] annotation is the
            # topic the image physically belongs to — this is exact, not heuristic.
            #
            # SECONDARY FIX — semantic fallback:
            # If spatial lookup finds no heading or no matching topic, fall back to
            # Jaccard scoring across all topics (margin > 0.08 to override).
            matched = primary_match
            if primary_match is not None and primary_idx is not None:

                # --- Try spatial: find last heading on this page in the FULL slide text ---
                # We search all_slides_text (not topic.slide_text) because the LLM
                # only puts its own topic's content in slide_text and may omit headings
                # from other topics that appear later on the same page.
                # all_slides_text always has the complete verbatim page content.
                spatial_match = None
                _label_in_full = re.compile(
                    r'---\s*' + re.escape(img.source_label) + r'\b[^\n]*---',
                    re.IGNORECASE,
                )
                pm = _label_in_full.search(all_slides_text)
                if pm:
                    page_body_start = pm.end()
                    next_pm = re.search(
                        r'\n---\s*(?:Page|Slide)\s+\d+',
                        all_slides_text[page_body_start:],
                    )
                    page_body_end = (
                        page_body_start + next_pm.start() if next_pm
                        else len(all_slides_text)
                    )
                    page_body = all_slides_text[page_body_start:page_body_end]

                    _HEADING_RE = re.compile(
                        r'^(?:\d+\.\d+(?:\.\d+)?\s+(.+)'
                        r'|#{1,3}\s+(.+)'
                        r'|(\d+\s+[A-Z][^\n]{2,60}))$',
                        re.MULTILINE,
                    )
                    _PLAIN_HEADING_RE = re.compile(
                        r'^(?!(?:Definition|Remark|Example|Proof|Theorem|Lemma'
                        r'|Corollary|Note|Exercise|Figure|Table|Since|Then|Thus'
                        r'|Hence|Also|Let|For|The|This|We|It|As|So|By)\b)'
                        r'([A-Za-z][^\n]{3,55})$',
                        re.MULTILINE,
                    )
                    _SENT_END = re.compile(r'[.!?,;:]$')
                    last_heading_text = None
                    for hm in _HEADING_RE.finditer(page_body):
                        g = next(
                            (x for x in (hm.group(1), hm.group(2), hm.group(3)) if x),
                            None,
                        )
                        if g:
                            last_heading_text = g.strip()
                    if last_heading_text is None:
                        for hm in _PLAIN_HEADING_RE.finditer(page_body):
                            line = hm.group(1).strip()
                            if _SENT_END.search(line): continue
                            if len(line.split()) < 2 or len(line) > 70: continue
                            last_heading_text = line

                    if last_heading_text:
                        _stop2 = {'a','an','the','is','are','of','in','on','at',
                                   'to','for','with','its','this','that','these',
                                   'those','it','as','by','be','was','were'}
                        def _hw(s):
                            s = s.replace('-', ' ').replace('_', ' ')
                            return set(re.sub(r'[^\w\s]', '', s.lower()).split()) - _stop2
                        hw = _hw(last_heading_text)
                        best_h, best_h_name = 0.0, None
                        for t in topics:
                            tw = _hw(t.topic)
                            if not hw or not tw:
                                continue
                            score = len(hw & tw) / len(hw | tw)
                            if score > best_h:
                                best_h, best_h_name = score, t.topic
                        if best_h_name and best_h > 0.0 and best_h_name != primary_match:
                            matched = best_h_name
                            spatial_match = matched
                            logger.info(
                                "image_placement: spatial override '%s' → '%s' "
                                "(last_heading=%r score=%.2f)",
                                primary_match, matched, last_heading_text, best_h,
                            )

                # --- Semantic fallback if spatial didn't find anything ---
                if spatial_match is None:
                    _stop3 = {'a','an','the','is','are','of','in','on','at','to',
                               'for','with','its','this','that','these','those','it',
                               'as','by','be','was','were','showing','shows','figure',
                               'diagram','image','graph','chart','plot','from','and',
                               'or','not','each','which','where'}
                    def _tok(s):
                        s = s.replace('-', ' ').replace('_', ' ')
                        return set(re.sub(r'[^\w\s]', '', s.lower()).split()) - _stop3
                    def _jscore(t_obj):
                        combined = t_obj.topic + ' ' + ' '.join(
                            getattr(t_obj, 'key_points', [])[:8])
                        d = _tok(img.description)
                        c = _tok(combined)
                        if not d or not c: return 0.0
                        return len(d & c) / len(d | c)
                    s_primary = _jscore(topics[primary_idx])
                    best_score, best_name = s_primary, primary_match
                    for t in topics:
                        s = _jscore(t)
                        if s > best_score:
                            best_score, best_name = s, t.topic
                    if best_name != primary_match and best_score > s_primary + 0.08:
                        matched = best_name
                        logger.info(
                            "image_placement: semantic override '%s' → '%s' "
                            "(scores %.2f → %.2f)",
                            primary_match, matched, s_primary, best_score,
                        )

            if matched is None:
                matched = _match_image_to_topic(img.description, topics)
            if matched and img_url:
                topic_figures.setdefault(matched, []).append((img.description, img_url))

        for img, img_url in textbook_figures_items:
            best = _match_image_to_topic(img.description, topics)
            if best and img_url:
                topic_figures.setdefault(best, []).append((img.description, img_url))

    logger.info(
        "image_pipeline: %d slide imgs, %d tb imgs -> %d topic_figures: %s",
        len(all_slide_images),
        len(all_textbook_images),
        len(topic_figures),
        {k: len(v) for k, v in topic_figures.items()},
    )

    # Inject media transcript chunks as additional slide content
    if media_transcript_chunks:
        try:
            import json as _json2
            _extra_chunks = _json2.loads(media_transcript_chunks)
            if isinstance(_extra_chunks, list) and _extra_chunks:
                all_slides_text = (all_slides_text + "\n\n" + "\n\n".join(_extra_chunks)).strip()
                logger.info("Media transcript: %d chunks injected into slides context", len(_extra_chunks))
        except Exception as _me:
            logger.warning("media_transcript_chunks parse failed: %s", _me)

    # Steps 6–8 — generate + verify
    fused_note, source, pipe_error = None, "local", None
    if topics:
        try:
            # Pull personalisation context (non-blocking thread)
            import asyncio as _aio_f
            try:
                from agents.behaviour_store import get_personalisation_context as _get_pctx
                _uid = user.get("id", "") if isinstance(user, dict) else ""
                _stud_ctx = await _aio_f.to_thread(_get_pctx, _uid)
            except Exception:
                _stud_ctx = ""
            fused_note, source = await asyncio.wait_for(
                run_generation_pipeline(topics=topics, topic_contexts=topic_contexts,
                                        proficiency=proficiency, refine=True,
                                        student_context=_stud_ctx),
                timeout=PIPELINE_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            pipe_error = f"Pipeline timed out after {PIPELINE_TIMEOUT_S}s"
        except Exception as exc:
            pipe_error = f"{type(exc).__name__}: {exc}"

    if not fused_note or len(fused_note.strip()) < 100:
        fused_note = generate_local_note(all_slides_text, all_textbook_text, proficiency)
        source     = "local"

    fused_note = fix_latex_delimiters(_fix_tables(fused_note))
    if fused_note and topic_figures:
        fused_note = _inject_figures_into_sections(fused_note, topic_figures)

    if source != "local":
        try:
            fused_note, _, _ = await _verify_note(fused_note, all_slides_text[:8000], all_textbook_text[:8000])
        except Exception as ve:
            logger.warning("Self-review error: %s", ve)

    if notebook_id:
        try:
            store_note_pages(notebook_id, _note_to_pages(fused_note))
            update_notebook_note(notebook_id, fused_note, proficiency)
        except Exception:
            pass

    return FusionResponse(
        fused_note=fused_note,
        source=source,
        fallback_reason=(f"AI unavailable ({pipe_error}) — offline notes used." if source == "local" and pipe_error
                         else "No AI configured — offline summariser used." if source == "local"
                         else None),
        chunks_stored=chunks_stored,
    )


@router.get("/api/images/{notebook_id}/{img_filename}")
async def serve_slide_image(notebook_id: str, img_filename: str):
    from agents.slide_images import get_image_path
    if not re.fullmatch(r'[a-zA-Z0-9_\-]+', notebook_id) or \
       not re.fullmatch(r'[a-zA-Z0-9_\-]+\.[a-zA-Z0-9]+', img_filename):
        raise HTTPException(400, "Invalid image path")
    path = get_image_path(notebook_id, img_filename)
    if not path:
        raise HTTPException(404, f"Image {img_filename} not found")
    ext  = img_filename.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "gif": "image/gif"}.get(ext, "image/png")
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "max-age=3600"})


@router.post("/api/upload-fuse", response_model=FusionResponse)
async def upload_fuse(
    slides_pdf:    UploadFile = File(...),
    textbook_pdf:  UploadFile = File(...),
    proficiency:   str = Form("Practitioner"),
    notebook_id:   str = Form(""),
    authorization: Optional[str] = Header(None),
):
    get_current_user(authorization)
    slides_pdf.filename   = slides_pdf.filename   or "slides.pdf"
    textbook_pdf.filename = textbook_pdf.filename or "textbook.pdf"
    return await upload_fuse_multi(
        slides_pdfs=[slides_pdf], textbook_pdfs=[textbook_pdf],
        proficiency=proficiency, notebook_id=notebook_id,
        authorization=authorization,
    )


@router.post("/api/upload-fuse-stream")
async def upload_fuse_stream(
    proficiency:              str              = Form("Practitioner"),
    slides_pdfs:              List[UploadFile] = File(default=[]),
    textbook_pdfs:            List[UploadFile] = File(default=[]),
    notebook_id:              Optional[str]    = Form(None),
    media_transcript_chunks:  Optional[str]    = Form(None),  # JSON list from media_ingest
    authorization: Optional[str]    = Header(None),
):
    """SSE streaming version of upload-fuse-multi."""
    import json as _json
    from agents.pdf_utils import extract_text_from_file, chunk_text
    from agents.knowledge_store import store_source_chunks, store_note_pages
    from agents.notebook_store import update_notebook_note
    from agents.local_summarizer import generate_local_note
    from agents.slide_images import extract_images_from_file, save_images
    from agents.image_ocr import describe_slide_image, is_image_file
    from agents.latex_utils import fix_latex_delimiters
    from pipeline.chunker import chunk_textbook
    from pipeline.embedder import Embedder
    from pipeline.vector_db import VectorDB
    from pipeline.slide_analyzer import analyse_slides
    from pipeline.topic_retriever import TopicRetriever
    from pipeline.note_generator import run_generation_pipeline_stream, _fix_tables

    user = get_current_user(authorization)
    _check_llm_rate_limit(user["id"])
    user_id_for_stream = user["id"]  # captured for event_generator closure
    if notebook_id:
        _require_notebook_owner(notebook_id, user)

    all_slides_text, all_textbook_text = "", ""
    all_slide_images, all_textbook_images, textbook_figures_items = [], [], []
    _total_bytes, extraction_errors = 0, []
    _global_page_offset = 0   # Global page counter across all uploaded slide files

    for upload in slides_pdfs:
        _validate_upload(upload)          # FIX: reject non-PDF/image uploads
        raw = await upload.read()
        fname = upload.filename or "slides.pdf"
        _total_bytes += len(raw)
        if _total_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(413, f"Upload exceeds {MAX_TOTAL_UPLOAD_BYTES//1024//1024} MB limit")
        pages_in_file = 0  # will be set by _renumber_pages; init here so image block can safely reference it
        try:
            marker    = f"\n\n{'='*60}\n=== FILE: {fname} ===\n{'='*60}\n\n"
            extracted = (await asyncio.to_thread(extract_text_from_file, raw, fname)
                         if is_image_file(fname)
                         else extract_text_from_file(raw, fname))
            # Renumber pages globally so each page has a unique number across all files.
            extracted, pages_in_file = _renumber_pages(extracted, _global_page_offset)
            _global_page_offset += pages_in_file
            all_slides_text += marker + extracted + "\n\n"
        except Exception as e:
            extraction_errors.append(f"{fname}: {e}")
        # Extract embedded images from non-image slide files (PDFs, PPTX)
        try:
            if not is_image_file(fname):
                file_imgs = extract_images_from_file(raw, fname)
                # Apply the same page offset used by _renumber_pages so that
                # source_label (e.g. "Page 3") matches the renumbered marker
                # (e.g. "--- Page 7 ---") when multiple files are uploaded.
                offset_before = _global_page_offset - pages_in_file if pages_in_file else 0
                for img in file_imgs:
                    img.source_label = re.sub(
                        r'^(Page|Slide)\s+(\d+)$',
                        lambda m: f"{m.group(1)} {int(m.group(2)) + offset_before}",
                        img.source_label,
                    )
                all_slide_images.extend(file_imgs)
        except Exception as e:
            logger.warning("Stream: image extraction failed %s: %s", fname, e)

    for upload in (textbook_pdfs or []):
        _validate_upload(upload)          # FIX: was missing in stream endpoint
        raw = await upload.read()
        fname = upload.filename or "textbook.pdf"
        _total_bytes += len(raw)
        if _total_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(413, f"Upload exceeds {MAX_TOTAL_UPLOAD_BYTES//1024//1024} MB limit")
        try:
            extracted = (await asyncio.to_thread(extract_text_from_file, raw, fname)
                         if is_image_file(fname)
                         else extract_text_from_file(raw, fname))
            all_textbook_text += extracted + "\n\n"
        except Exception as e:
            extraction_errors.append(f"{fname}: {e}")
        try:
            if not is_image_file(fname):
                tb_imgs = extract_images_from_file(raw, fname)
                for img in tb_imgs:
                    img.img_id       = f"tb_{img.img_id}"
                    img.source_label = f"Textbook — {img.source_label}"
                all_textbook_images.extend(tb_imgs)
        except Exception:
            pass

    # Inject media transcript chunks as additional slide content before
    # validating empty extraction so media-only flow does not 422.
    if media_transcript_chunks:
        try:
            _extra_chunks = _json.loads(media_transcript_chunks)
            if isinstance(_extra_chunks, list) and _extra_chunks:
                all_slides_text = (all_slides_text + "\n\n" + "\n\n".join(_extra_chunks)).strip()
                logger.info("Media transcript: %d chunks injected into stream context", len(_extra_chunks))
        except Exception as _me:
            logger.warning("stream media_transcript_chunks parse failed: %s", _me)

    if not all_slides_text.strip() and not all_textbook_text.strip():
        raise HTTPException(422, "Could not extract text. " + "; ".join(extraction_errors))

    # Step 1b — describe + annotate slide images (must happen before slide analysis)
    # Description + text annotation always runs regardless of notebook_id.
    # The [Figure: ...] marker in slide text is what the note generator reads —
    # it does not require saving images to disk.
    # Disk save (for serving images in the rendered note) only needs notebook_id.
    if all_slide_images:
        async def _desc(img):
            try:
                img.description = await asyncio.wait_for(
                    asyncio.to_thread(describe_slide_image, img.data, img.source_label),
                    timeout=_IMAGE_DESC_TIMEOUT_S,
                )
            except Exception:
                img.description = f"Figure from {img.source_label}"
        await asyncio.gather(*[_desc(img) for img in all_slide_images])
        if notebook_id:
            try:
                save_images(notebook_id, all_slide_images, clear_existing=True)
            except Exception as e:
                logger.warning("Stream: save_images failed: %s", e)
        # Annotate each slide marker in the text with its figure description.
        # This embeds image context into the slide text the note generator reads,
        # so images are incorporated at the correct position in notes.
        for img in all_slide_images:
            pat = re.compile(r'(---\s*' + re.escape(img.source_label) + r'\b[^\n]*---)', re.IGNORECASE)
            all_slides_text = pat.sub(
                lambda m, ann=f"\n[Figure: {img.description}]": m.group(0) + ann,
                all_slides_text, count=1,
            )

    # Step 1c — describe + annotate textbook images (notebook_id required for serving)
    if all_textbook_images and notebook_id:
        async def _desc_tb(img):
            try:
                img.description = await asyncio.wait_for(
                    asyncio.to_thread(describe_slide_image, img.data, img.source_label),
                    timeout=_IMAGE_DESC_TIMEOUT_S,
                )
            except Exception:
                img.description = f"Figure from {img.source_label}"
        await asyncio.gather(*[_desc_tb(img) for img in all_textbook_images])
        try:
            save_images(notebook_id, all_textbook_images, clear_existing=False)
            for img in all_textbook_images:
                ext = img.mime.split("/")[-1].replace("jpeg", "jpg")
                textbook_figures_items.append((img, f"/api/images/{notebook_id}/{img.img_id}.{ext}"))
        except Exception:
            all_textbook_images = []

    slide_raw_chunks    = chunk_text(all_slides_text,   max_chars=4000)
    textbook_raw_chunks = chunk_text(all_textbook_text, max_chars=4000)
    textbook_hash       = hashlib.md5(all_textbook_text.encode()).hexdigest()[:16]
    if notebook_id:
        try:
            store_source_chunks(nb_id=notebook_id, slide_chunks=slide_raw_chunks,
                                textbook_chunks=textbook_raw_chunks, textbook_hash=textbook_hash)
        except Exception as e:
            logger.warning("Knowledge store write failed: %s", e)

    textbook_semantic_chunks = []
    if all_textbook_text.strip():
        try:
            textbook_semantic_chunks = chunk_textbook(all_textbook_text)
        except Exception:
            pass

    embedder, vector_db = Embedder(), VectorDB()
    if textbook_semantic_chunks:
        try:
            loaded = bool(notebook_id) and vector_db.load(notebook_id, expected_hash=textbook_hash)
            if loaded:
                embedder.rebuild_from_chunks(vector_db.chunks)
            else:
                embedder.embed_chunks(textbook_semantic_chunks)
                vector_db.add_chunks(textbook_semantic_chunks)
                if notebook_id: vector_db.add_to_azure(notebook_id, textbook_semantic_chunks)
                if notebook_id:
                    vector_db.save(notebook_id, textbook_hash=textbook_hash)
        except Exception as e:
            logger.warning("Embedding failed: %s", e)

    topics = []
    try:
        topics = await analyse_slides(all_slides_text)
    except Exception as e:
        logger.warning("Slide analysis failed: %s", e)

    topic_contexts: dict[str, str] = {}
    if topics and vector_db.size > 0:
        try:
            retriever      = TopicRetriever(vector_db, embedder)
            topic_contexts = retriever.retrieve_all_topics(topics, nb_id=notebook_id or "")
        except Exception:
            pass

    # Step 5b — match textbook figures to topics (inject into topic_contexts)
    if textbook_figures_items and topics:
        for img, img_url in textbook_figures_items:
            best = _match_image_to_topic(img.description, topics)
            if best is not None:
                ref = f"\n\n[Textbook Figure: {img.description}]\n![{img.description}]({img_url})"
                topic_contexts[best] = topic_contexts.get(best, "") + ref

    # Step 5c — build inline figure map for post-generation injection
    # Maps topic name → list of (description, url) for all images belonging to it.
    # Used by _inject_figures_into_sections to place images under the right heading.
    # Placement: spatial heading lookup in all_slides_text (last section heading on
    # the page), with Jaccard semantic scoring as fallback.
    topic_figures: dict[str, list] = {}
    if topics:
        for img in all_slide_images:
            img_url = (
                f"/api/images/{notebook_id}/{img.img_id}."
                + img.mime.split("/")[-1].replace("jpeg", "jpg")
            ) if notebook_id else ""

            # --- Try 1: exact page match via source_label in topic slide_text ---
            # Use word-boundary anchor () so "Page 1" never matches "Page 10".
            label_pat = re.compile(
                r'---\s*' + re.escape(img.source_label) + r'\b[^\n]*---',
                re.IGNORECASE,
            )
            primary_match = None
            primary_idx   = None
            for idx, t in enumerate(topics):
                if label_pat.search(t.slide_text):
                    primary_match = t.topic
                    primary_idx   = idx
                    break

            # --- Spatial + semantic override ---
            # source_label page match gives us the page, but a single page can
            # contain multiple topics (e.g. Page 1 has "Measurable Functions" and
            # "Function of a Random Variable", with the diagram under the second).
            #
            # PRIMARY FIX — spatial locality in slide text:
            # The [Figure: ...] annotation is injected right after its page marker.
            # The slide text for that page preserves all section headings in order.
            # The last heading that appears BEFORE the [Figure:] annotation is the
            # topic the image physically belongs to — this is exact, not heuristic.
            #
            # SECONDARY FIX — semantic fallback:
            # If spatial lookup finds no heading or no matching topic, fall back to
            # Jaccard scoring across all topics (margin > 0.08 to override).
            matched = primary_match
            if primary_match is not None and primary_idx is not None:

                # --- Try spatial: find last heading on this page in the FULL slide text ---
                # We search all_slides_text (not topic.slide_text) because the LLM
                # only puts its own topic's content in slide_text and may omit headings
                # from other topics that appear later on the same page.
                # all_slides_text always has the complete verbatim page content.
                spatial_match = None
                _label_in_full = re.compile(
                    r'---\s*' + re.escape(img.source_label) + r'\b[^\n]*---',
                    re.IGNORECASE,
                )
                pm = _label_in_full.search(all_slides_text)
                if pm:
                    page_body_start = pm.end()
                    next_pm = re.search(
                        r'\n---\s*(?:Page|Slide)\s+\d+',
                        all_slides_text[page_body_start:],
                    )
                    page_body_end = (
                        page_body_start + next_pm.start() if next_pm
                        else len(all_slides_text)
                    )
                    page_body = all_slides_text[page_body_start:page_body_end]

                    _HEADING_RE = re.compile(
                        r'^(?:\d+\.\d+(?:\.\d+)?\s+(.+)'
                        r'|#{1,3}\s+(.+)'
                        r'|(\d+\s+[A-Z][^\n]{2,60}))$',
                        re.MULTILINE,
                    )
                    _PLAIN_HEADING_RE = re.compile(
                        r'^(?!(?:Definition|Remark|Example|Proof|Theorem|Lemma'
                        r'|Corollary|Note|Exercise|Figure|Table|Since|Then|Thus'
                        r'|Hence|Also|Let|For|The|This|We|It|As|So|By)\b)'
                        r'([A-Za-z][^\n]{3,55})$',
                        re.MULTILINE,
                    )
                    _SENT_END = re.compile(r'[.!?,;:]$')
                    last_heading_text = None
                    for hm in _HEADING_RE.finditer(page_body):
                        g = next(
                            (x for x in (hm.group(1), hm.group(2), hm.group(3)) if x),
                            None,
                        )
                        if g:
                            last_heading_text = g.strip()
                    if last_heading_text is None:
                        for hm in _PLAIN_HEADING_RE.finditer(page_body):
                            line = hm.group(1).strip()
                            if _SENT_END.search(line): continue
                            if len(line.split()) < 2 or len(line) > 70: continue
                            last_heading_text = line

                    if last_heading_text:
                        _stop2 = {'a','an','the','is','are','of','in','on','at',
                                   'to','for','with','its','this','that','these',
                                   'those','it','as','by','be','was','were'}
                        def _hw(s):
                            s = s.replace('-', ' ').replace('_', ' ')
                            return set(re.sub(r'[^\w\s]', '', s.lower()).split()) - _stop2
                        hw = _hw(last_heading_text)
                        best_h, best_h_name = 0.0, None
                        for t in topics:
                            tw = _hw(t.topic)
                            if not hw or not tw:
                                continue
                            score = len(hw & tw) / len(hw | tw)
                            if score > best_h:
                                best_h, best_h_name = score, t.topic
                        if best_h_name and best_h > 0.0 and best_h_name != primary_match:
                            matched = best_h_name
                            spatial_match = matched
                            logger.info(
                                "image_placement: spatial override '%s' → '%s' "
                                "(last_heading=%r score=%.2f)",
                                primary_match, matched, last_heading_text, best_h,
                            )

                # --- Semantic fallback if spatial didn't find anything ---
                if spatial_match is None:
                    _stop3 = {'a','an','the','is','are','of','in','on','at','to',
                               'for','with','its','this','that','these','those','it',
                               'as','by','be','was','were','showing','shows','figure',
                               'diagram','image','graph','chart','plot','from','and',
                               'or','not','each','which','where'}
                    def _tok(s):
                        s = s.replace('-', ' ').replace('_', ' ')
                        return set(re.sub(r'[^\w\s]', '', s.lower()).split()) - _stop3
                    def _jscore(t_obj):
                        combined = t_obj.topic + ' ' + ' '.join(
                            getattr(t_obj, 'key_points', [])[:8])
                        d = _tok(img.description)
                        c = _tok(combined)
                        if not d or not c: return 0.0
                        return len(d & c) / len(d | c)
                    s_primary = _jscore(topics[primary_idx])
                    best_score, best_name = s_primary, primary_match
                    for t in topics:
                        s = _jscore(t)
                        if s > best_score:
                            best_score, best_name = s, t.topic
                    if best_name != primary_match and best_score > s_primary + 0.08:
                        matched = best_name
                        logger.info(
                            "image_placement: semantic override '%s' → '%s' "
                            "(scores %.2f → %.2f)",
                            primary_match, matched, s_primary, best_score,
                        )

            # --- Try 2: description-based semantic match (fallback) ---
            if matched is None:
                matched = _match_image_to_topic(img.description, topics)

            if matched and img_url:
                topic_figures.setdefault(matched, []).append((img.description, img_url))

        for img, img_url in textbook_figures_items:
            best = _match_image_to_topic(img.description, topics)
            if best and img_url:
                topic_figures.setdefault(best, []).append((img.description, img_url))

    logger.info(
        "image_pipeline(stream): %d slide imgs, %d tb imgs -> %d topic_figures: %s",
        len(all_slide_images),
        len(all_textbook_images),
        len(topic_figures),
        {k: len(v) for k, v in topic_figures.items()},
    )

    async def event_generator():
        if not topics:
            fallback = generate_local_note(all_slides_text, all_textbook_text, proficiency)
            fallback = fix_latex_delimiters(_fix_tables(fallback))
            if notebook_id:
                try:
                    update_notebook_note(notebook_id, fallback, proficiency)
                except Exception:
                    pass
            yield f"data: {_json.dumps({'type':'done','note':fallback,'source':'local'})}\n\n"
            return

        yield f"data: {_json.dumps({'type':'status','message':'Starting note generation…'})}\n\n"

        # Pull personalisation for the streaming path (non-blocking)
        _stream_student_ctx = ""
        try:
            import asyncio as _aio_s
            from agents.behaviour_store import get_personalisation_context as _gpctx_s
            _stream_student_ctx = await _aio_s.to_thread(_gpctx_s, user_id_for_stream)
        except Exception:
            pass

        final_note, final_source = "", "local"
        try:
            async for event in run_generation_pipeline_stream(topics, topic_contexts, proficiency, student_context=_stream_student_ctx):
                if event["type"] == "section":
                    event["content"] = fix_latex_delimiters(_fix_tables(event["content"]))
                    final_note += ("\n\n" if final_note else "") + event["content"]
                    final_source = "azure"
                elif event["type"] == "done":
                    final_note   = fix_latex_delimiters(_fix_tables(event.get("note", "") or final_note))
                    final_source = event.get("source", "local")
                    # Inject figures into the final merged note under the correct headings.
                    # This runs after generation so images appear in the right ## sections.
                    if topic_figures:
                        final_note = _inject_figures_into_sections(final_note, topic_figures)
                    # NOTE: _verify_note is intentionally skipped on the stream path.
                    # Per-topic refine+verify already ran inside note_generator.py.
                    # Running a second full-note verify pass here truncated multi-page
                    # notes to 1 page because fusion_agent.self_review() defaults to
                    # the semantic-kernel max_tokens cap (~4096 tokens ≈ 1 page).
                    event.update({
                        "note": final_note, "source": final_source, "verified": True,
                        "corrections_made": 0,
                        "correction_summary": "",
                    })
                    if notebook_id and final_note:
                        try:
                            store_note_pages(notebook_id, _note_to_pages(final_note))
                            update_notebook_note(notebook_id, final_note, proficiency)
                        except Exception as e:
                            logger.warning("Stream persist failed: %s", e)
                yield f"data: {_json.dumps(event)}\n\n"
        except Exception as gen_exc:
            # Safety net: generator crashed — emit done with whatever was accumulated
            logger.error("Stream generator crashed: %s", gen_exc, exc_info=True)
            if not final_note:
                final_note = generate_local_note(all_slides_text, all_textbook_text, proficiency)
                final_source = "local"
            final_note = fix_latex_delimiters(_fix_tables(final_note))
            if topic_figures:
                final_note = _inject_figures_into_sections(final_note, topic_figures)
            if notebook_id and final_note:
                try:
                    store_note_pages(notebook_id, _note_to_pages(final_note))
                    update_notebook_note(notebook_id, final_note, proficiency)
                except Exception:
                    pass
            yield f"data: {_json.dumps({'type':'done','note':final_note,'source':final_source,'verified':False,'corrections_made':0,'correction_summary':''})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/api/fuse", response_model=FusionResponse)
async def fuse_knowledge(req: FusionRequest, authorization: Optional[str] = Header(None)):
    """Legacy text-based fusion (stores chunks, runs full pipeline)."""
    from agents.pdf_utils import chunk_text
    from agents.knowledge_store import store_source_chunks, store_note_pages
    from agents.notebook_store import update_notebook_note
    from agents.local_summarizer import generate_local_note
    from agents.latex_utils import fix_latex_delimiters
    from pipeline.chunker import chunk_textbook
    from pipeline.embedder import Embedder
    from pipeline.vector_db import VectorDB
    from pipeline.slide_analyzer import analyse_slides
    from pipeline.topic_retriever import TopicRetriever
    from pipeline.note_generator import run_generation_pipeline

    user = get_current_user(authorization)
    _check_llm_rate_limit(user["id"])    # FIX: legacy endpoint had no rate limit
    slide_content    = req.slide_summary[:_PROMPT_SLIDES_BUDGET]
    textbook_content = req.textbook_paragraph[:_PROMPT_TEXTBOOK_BUDGET]
    nb_id            = req.notebook_id

    if nb_id:
        _require_notebook_owner(nb_id, user)   # FIX: no ownership check before writing chunks
        try:
            tb_hash = hashlib.md5(textbook_content.encode()).hexdigest()[:16]
            store_source_chunks(nb_id=nb_id,
                               slide_chunks=chunk_text(slide_content,    max_chars=4000),
                               textbook_chunks=chunk_text(textbook_content, max_chars=4000),
                               textbook_hash=tb_hash)
        except Exception as e:
            logger.warning("/api/fuse: chunk store failed: %s", e)

    fused_note, source = None, "local"
    try:
        topics = await analyse_slides(slide_content)
        if topics:
            embedder, vector_db = Embedder(), VectorDB()
            tb_chunks = chunk_textbook(textbook_content) if textbook_content.strip() else []
            if tb_chunks:
                embedder.embed_chunks(tb_chunks)
                vector_db.add_chunks(tb_chunks)
            topic_contexts: dict[str, str] = {}
            if vector_db.size > 0:
                topic_contexts = TopicRetriever(vector_db, embedder).retrieve_all_topics(topics, nb_id=nb_id or "")
            fused_note, source = await run_generation_pipeline(
                topics=topics, topic_contexts=topic_contexts,
                proficiency=req.proficiency, refine=True,
            )
    except Exception as exc:
        logger.warning("/api/fuse pipeline failed: %s", exc)

    if not fused_note or len(fused_note.strip()) < 100:
        fused_note = generate_local_note(req.slide_summary, req.textbook_paragraph, req.proficiency)
        source     = "local"

    fused_note = fix_latex_delimiters(fused_note)
    if nb_id:
        try:
            store_note_pages(nb_id, _note_to_pages(fused_note))
        except Exception:
            pass

    return FusionResponse(
        fused_note=fused_note,
        source=source,
        fallback_reason=None if source != "local" else "No AI configured — offline summariser used.",
    )


# ── Media ingestion endpoint ──────────────────────────────────────────────────
# Accepts: video/audio URL, audio file upload, or raw transcript text
# Returns: extracted text chunks + status, which the frontend then includes
# as additional slides_pdfs context in the main fuse call — OR calls
# /api/media-ingest-fuse which handles the full pipeline in one request.

from pydantic import BaseModel as _BM2
from typing import Optional as _Opt2

class MediaIngestRequest(_BM2):
    url:        _Opt2[str] = None
    transcript: _Opt2[str] = None   # raw pasted text
    notebook_id: _Opt2[str] = None


class MediaIngestResponse(_BM2):
    ok:          bool
    chunks:      list[str]
    source_desc: str
    message:     str = ""


_MAX_MEDIA_URLS = 8
_MAX_MEDIA_AUDIO_FILES = 8
_MAX_MEDIA_TRANSCRIPT_FILES = 8
_MAX_MEDIA_SOURCES_TOTAL = 16


@router.post("/api/media-ingest", response_model=MediaIngestResponse)
async def media_ingest(
    authorization: _Opt2[str] = Header(None),
    url:           _Opt2[str]        = Form(default=None),
    urls:          List[str]         = Form(default=[]),
    transcript:    _Opt2[str]        = Form(default=None),
    notebook_id:   _Opt2[str]        = Form(default=None),
    audio_file:    _Opt2[UploadFile] = File(default=None),
    audio_files:   List[UploadFile]  = File(default=[]),
    transcript_files: List[UploadFile] = File(default=[]),
):
    """
    Ingest lecture media (video URL / audio file / transcript text) and
    return extracted text chunks ready to be used in note generation.

    Frontend calls this BEFORE or instead of /api/upload-fuse-stream to
    extract transcript, then passes the result as slides context.
    """
    from agents.media_ingest import ingest_url, ingest_audio, ingest_transcript_text

    user = get_current_user(authorization)

    all_chunks: list[str] = []
    source_descs: list[str] = []

    url_items: list[str] = []
    if url and url.strip():
        url_items.append(url.strip())
    for u in urls:
        if u and u.strip():
            url_items.append(u.strip())
    # de-dup while preserving order
    url_items = list(dict.fromkeys(url_items))

    audio_items: list[UploadFile] = []
    if audio_file is not None:
        audio_items.append(audio_file)
    audio_items.extend(audio_files or [])

    transcript_file_items = transcript_files or []

    if len(url_items) > _MAX_MEDIA_URLS:
        raise HTTPException(413, f"Too many video URLs. Max allowed is {_MAX_MEDIA_URLS}.")
    if len(audio_items) > _MAX_MEDIA_AUDIO_FILES:
        raise HTTPException(413, f"Too many audio files. Max allowed is {_MAX_MEDIA_AUDIO_FILES}.")
    if len(transcript_file_items) > _MAX_MEDIA_TRANSCRIPT_FILES:
        raise HTTPException(413, f"Too many transcript files. Max allowed is {_MAX_MEDIA_TRANSCRIPT_FILES}.")

    source_count = len(url_items) + len(audio_items) + len(transcript_file_items) + (1 if transcript and transcript.strip() else 0)
    if source_count > _MAX_MEDIA_SOURCES_TOTAL:
        raise HTTPException(413, f"Too many media sources in one request. Max allowed is {_MAX_MEDIA_SOURCES_TOTAL}.")

    # 1) pasted transcript text
    if transcript and transcript.strip():
        chunks, src = ingest_transcript_text(transcript)
        if chunks:
            all_chunks.extend(chunks)
            source_descs.append(src)

    # 2) transcript files (.txt/.vtt/.srt etc.)
    for tf in transcript_file_items:
        try:
            raw = await tf.read()
            text = raw.decode("utf-8", errors="ignore")
            chunks, _ = ingest_transcript_text(text)
            if chunks:
                all_chunks.extend(chunks)
                source_descs.append(f"Transcript file: {tf.filename or 'transcript.txt'}")
        except Exception as e:
            logger.warning("media_ingest: transcript file parse failed for %s: %s", tf.filename, e)

    # 3) audio files
    for af in audio_items:
        try:
            audio_bytes = await af.read()
            chunks, src = await ingest_audio(audio_bytes, af.filename or "recording.mp3")
            if chunks:
                all_chunks.extend(chunks)
                source_descs.append(src)
        except Exception as e:
            logger.warning("media_ingest: audio ingest failed for %s: %s", af.filename, e)

    # 4) video URLs
    no_caption_urls = []
    for u in url_items:
        try:
            chunks, src = await ingest_url(u)
            if src == "no_captions":
                no_caption_urls.append(u)
                continue
            if chunks:
                all_chunks.extend(chunks)
                source_descs.append(src)
        except Exception as e:
            logger.warning("media_ingest: url ingest failed for %s: %s", u, e)

    if not all_chunks:
        no_caption_hint = (
            " No captions found for one or more URLs."
            if no_caption_urls else ""
        )
        return MediaIngestResponse(
            ok=False, chunks=[], source_desc="",
            message="Could not extract any content. Please check inputs or try pasting transcript text." + no_caption_hint
        )

    # Optionally store in knowledge store if notebook_id provided
    if notebook_id and all_chunks:
        try:
            from agents.knowledge_store import store_source_chunks
            store_source_chunks(notebook_id, all_chunks, [])
        except Exception as e:
            logger.warning("media_ingest: store_source_chunks failed: %s", e)

    desc_preview = source_descs[:3]
    extra = len(source_descs) - len(desc_preview)
    summary = "; ".join(desc_preview)
    if extra > 0:
        summary = f"{summary}; +{extra} more"
    if not summary:
        summary = f"{len(all_chunks)} transcript segments"

    return MediaIngestResponse(ok=True, chunks=all_chunks, source_desc=summary)
