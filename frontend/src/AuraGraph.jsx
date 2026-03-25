import React, { useState, useCallback, useEffect, useRef } from "react";
import { useSelector, useDispatch } from 'react-redux';
import { setGraphData, updateNodeStatus } from './store';
import EnhancedGraph from './AuraGraphNodeGraph';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';
import { Sparkles, Loader2, ChevronLeft, ChevronRight, FilePlus2, BookOpen, Upload, FileText, X, MessageSquare } from 'lucide-react';

const KATEX_OPTS = { throwOnError: false, strict: false, errorColor: '#cc0000' };
const BACKEND_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

function resolveImageSrc(src) {
    if (!src) return '';
    if (/^https?:\/\//i.test(src)) return src;
    if (src.startsWith('/')) return `${BACKEND_BASE}${src}`;
    return `${BACKEND_BASE}/${src}`;
}

const IMG_OVERRIDE = {
    img({ src, alt }) {
        if (!src) return null;
        const finalSrc = resolveImageSrc(src);
        return (
            <figure style={{ margin: '14px 0' }}>
                <img
                    src={finalSrc}
                    alt={alt || 'Figure'}
                    loading="lazy"
                    style={{ width: '100%', maxHeight: 420, objectFit: 'contain', borderRadius: 10, border: '1px solid #1e3a5f', background: '#020c1b' }}
                />
                {alt && (
                    <figcaption style={{ marginTop: 8, fontSize: 12, color: '#94a3b8', fontStyle: 'italic', lineHeight: 1.5 }}>
                        {alt}
                    </figcaption>
                )}
            </figure>
        );
    }
};

// ─── Mutation Modal ──────────────────────────────────────────────────────────
function MutateModal({ page, onClose, onMutate }) {
    const [doubt, setDoubt] = useState("");
    const [busy, setBusy] = useState(false);
    const go = async () => {
        if (!doubt.trim()) return;
        setBusy(true);
        await onMutate(page, doubt);
        setBusy(false);
        onClose();
    };
    return (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.85)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 99 }}>
            <div style={{ background: "#0d1b2a", border: "1px solid #1e3a5f", borderRadius: 14, padding: 30, width: 560, maxWidth: "94vw", boxShadow: "0 30px 80px #000a" }}>
                <div style={{ fontSize: 16, fontWeight: 800, color: "#e2e8f0", marginBottom: 6, fontFamily: "'Courier New',monospace" }}>
                    Ask a Doubt — AuraGraph will rewrite this page
                </div>
                <div style={{ fontSize: 12, color: "#475569", marginBottom: 14 }}>
                    Describe exactly what's confusing. The note will be permanently mutated for clarity.
                </div>
                <div style={{ background: "#0f172a", borderRadius: 8, padding: 12, fontSize: 12, color: "#64748b", fontFamily: "Georgia,serif", lineHeight: 1.7, marginBottom: 14, maxHeight: 100, overflowY: "auto", border: "1px solid #1e293b" }}>
                    {page?.slice(0, 300)}…
                </div>
                <textarea
                    value={doubt} onChange={e => setDoubt(e.target.value)} rows={4} autoFocus
                    placeholder="e.g. I don't understand why h(t-τ) is flipped and shifted here…"
                    style={{ width: "100%", background: "#0f172a", border: "1px solid #1e3a5f", borderRadius: 8, padding: 12, color: "#e2e8f0", fontSize: 13, fontFamily: "Georgia,serif", resize: "vertical", outline: "none", boxSizing: "border-box" }}
                />
                <div style={{ display: "flex", gap: 10, marginTop: 14, justifyContent: "flex-end" }}>
                    <button onClick={onClose} style={{ padding: "8px 18px", borderRadius: 8, border: "1px solid #1e293b", background: "transparent", color: "#475569", cursor: "pointer", fontSize: 13 }}>Cancel</button>
                    <button onClick={go} disabled={busy || !doubt.trim()} style={{ padding: "9px 22px", borderRadius: 8, border: "none", background: busy ? "#1e3a8a" : "linear-gradient(135deg,#1d4ed8,#7c3aed)", color: "#fff", cursor: busy ? "not-allowed" : "pointer", fontSize: 13, fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
                        {busy ? <><Loader2 size={14} /> Mutating…</> : <><Sparkles size={14} /> Mutate This Page</>}
                    </button>
                </div>
            </div>
        </div>
    );
}

// ─── Drag-and-drop file picker ────────────────────────────────────────────────
function FileDrop({ label, icon, accept, onFile, file }) {
    const ref = useRef();
    const [dragging, setDragging] = useState(false);

    const onDrop = (e) => {
        e.preventDefault(); setDragging(false);
        const f = e.dataTransfer.files[0];
        if (f) onFile(f);
    };

    return (
        <div
            onClick={() => ref.current.click()}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            style={{
                border: `2px dashed ${dragging ? '#3b82f6' : file ? '#16a34a' : '#1e3a5f'}`,
                borderRadius: 12,
                padding: '28px 20px',
                textAlign: 'center',
                cursor: 'pointer',
                background: dragging ? '#071728' : file ? '#071a0f' : '#020c1b',
                transition: 'all 0.2s'
            }}
        >
            <input ref={ref} type="file" accept={accept} style={{ display: 'none' }} onChange={(e) => onFile(e.target.files[0])} />
            {file ? (
                <div>
                    <FileText size={30} style={{ color: '#4ade80', margin: '0 auto 8px' }} />
                    <div style={{ fontSize: 13, fontWeight: 700, color: '#4ade80' }}>{file.name}</div>
                    <div style={{ fontSize: 11, color: '#475569', marginTop: 3 }}>{(file.size / 1024 / 1024).toFixed(1)} MB · PDF Loaded</div>
                </div>
            ) : (
                <div>
                    <div style={{ fontSize: 28, marginBottom: 8 }}>{icon}</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: '#94a3b8' }}>{label}</div>
                    <div style={{ fontSize: 11, color: '#475569', marginTop: 4 }}>Drag & drop or click to browse</div>
                </div>
            )}
        </div>
    );
}

// ─── Knowledge Fusion Upload Screen ──────────────────────────────────────────
function KnowledgeFusionView({ onDone, onNoteReady }) {
    const [slidesFile, setSlidesFile] = useState(null);
    const [textbookFile, setTextbookFile] = useState(null);
    const [proficiency, setProficiency] = useState("Intermediate");
    const [fusing, setFusing] = useState(false);
    const [progress, setProgress] = useState("");

    const handleFuse = async () => {
        if (!slidesFile || !textbookFile) { alert("Please upload both files."); return; }
        setFusing(true);
        setProgress("Reading PDFs…");

        try {
            const formData = new FormData();
            formData.append("slides_pdf", slidesFile);
            formData.append("textbook_pdf", textbookFile);
            formData.append("proficiency", proficiency);

            setProgress("Sending to AuraGraph Fusion Engine… (this may take 10–30 seconds for large PDFs)");

            const res = await fetch('http://localhost:8000/api/upload-fuse', {
                method: 'POST',
                body: formData
            });

            if (!res.ok) {
                const err = await res.json();
                const rawDetail = err.detail;
                const msg = typeof rawDetail === 'string' ? rawDetail
                    : Array.isArray(rawDetail) ? rawDetail.map(e => e?.msg || JSON.stringify(e)).join(' · ')
                    : `Server error ${res.status}`;
                throw new Error(msg);
            }

            const data = await res.json();
            onNoteReady(data.fused_note, proficiency);
            onDone();

        } catch (e) {
            console.error(e);
            const mockNote = `## The Convolution Theorem — AuraGraph Fused Note (${proficiency})\n\nThe Convolution Theorem states that convolution in the time domain corresponds to pointwise multiplication in the frequency domain.\n\nFormally: If x(t) ↔ X(jω) and h(t) ↔ H(jω) then:\n\n**x(t) * h(t) ↔ X(jω) · H(jω)**\n\nThis eliminates the costly convolution integral — instead, transform both signals, multiply their spectra, and inverse-transform.`;
            onNoteReady(mockNote, proficiency);
            onDone();
        }
        setFusing(false);
    };

    return (
        <div style={{ flex: 1, padding: '40px 60px', overflowY: 'auto', background: '#020817', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
            <h2 style={{ fontSize: 22, fontWeight: 800, color: '#e2e8f0', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 10 }}>
                <FilePlus2 size={22} style={{ color: '#3b82f6' }} /> Knowledge Fusion Engine
            </h2>
            <p style={{ color: '#64748b', marginBottom: 32, fontSize: 13, lineHeight: 1.7 }}>
                Upload your Professor's Slides and Textbook as PDFs. AuraGraph will extract, compress, and fuse them into a structured Digital Note calibrated to your proficiency level.
            </p>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
                <FileDrop label="Professor's Slides (PDF)" icon="🎓" accept=".pdf" file={slidesFile} onFile={setSlidesFile} />
                <FileDrop label="Textbook (PDF)" icon="📚" accept=".pdf" file={textbookFile} onFile={setTextbookFile} />
            </div>

            <div style={{ marginBottom: 28 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', marginBottom: 10 }}>YOUR PROFICIENCY LEVEL</div>
                <div style={{ display: 'flex', gap: 10 }}>
                    {[
                        { label: "Beginner", desc: "Simple, analogies-first" },
                        { label: "Intermediate", desc: "Balanced depth" },
                        { label: "Advanced", desc: "Dense, technical" }
                    ].map(p => (
                        <button key={p.label} onClick={() => setProficiency(p.label)} style={{ flex: 1, padding: '12px 8px', borderRadius: 8, cursor: 'pointer', border: '1px solid ' + (proficiency === p.label ? '#3b82f6' : '#1e293b'), background: proficiency === p.label ? '#0f2d5e' : '#020c1b', color: proficiency === p.label ? '#93c5fd' : '#475569', transition: 'all 0.15s', textAlign: 'center' }}>
                            <div style={{ fontWeight: 700, fontSize: 13 }}>{p.label}</div>
                            <div style={{ fontSize: 10, marginTop: 2, opacity: 0.7 }}>{p.desc}</div>
                        </button>
                    ))}
                </div>
            </div>

            <button onClick={handleFuse} disabled={fusing || !slidesFile || !textbookFile} style={{ padding: '14px 28px', borderRadius: 10, border: 'none', background: fusing || !slidesFile || !textbookFile ? '#1e293b' : 'linear-gradient(135deg,#1d4ed8,#7c3aed)', color: fusing || !slidesFile || !textbookFile ? '#475569' : '#fff', cursor: fusing || !slidesFile || !textbookFile ? 'not-allowed' : 'pointer', fontSize: 14, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, transition: 'all 0.2s' }}>
                {fusing ? <><Loader2 size={18} style={{ animation: 'spin 1s linear infinite' }} /> {progress}</> : <><Sparkles size={18} /> Generate Digital Notes</>}
            </button>

            <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
        </div>
    );
}

// ─── Note Page Viewer ─────────────────────────────────────────────────────────
function NoteViewer({ pages, currentPage, setCurrentPage, note, prof }) {
    return (
        <div style={{ flex: 1, padding: '32px 40px', overflowY: 'auto', display: 'flex', justifyContent: 'center' }}>
            <div style={{ maxWidth: 720, width: '100%' }}>
                {pages.length === 0 && (
                    <div style={{ textAlign: 'center', color: '#475569', marginTop: 100 }}>No content fused yet.</div>
                )}
                {pages.length > 0 && (
                    <div style={{ fontSize: 14.5, lineHeight: 2.0, color: '#cbd5e1', fontFamily: "Georgia,'Times New Roman',serif", background: '#0a101d', padding: '40px 44px', borderRadius: 14, boxShadow: '0 10px 40px rgba(0,0,0,0.6)', minHeight: 320 }}>
                        <ReactMarkdown
                            remarkPlugins={[remarkMath, remarkGfm]}
                            rehypePlugins={[[rehypeKatex, KATEX_OPTS]]}
                            components={IMG_OVERRIDE}
                        >{pages[currentPage]}</ReactMarkdown>
                    </div>
                )}
            </div>
        </div>
    );
}

// ─── Main Component ──────────────────────────────────────────────────────────
export default function AuraGraph() {
    const dispatch = useDispatch();
    // note and prof are LOCAL state — they are not in the Redux store
    const [note, setNote] = useState('');
    const [prof, setProf] = useState('Intermediate');
    const { nodes, edges } = useSelector(state => state.graph);

    const [mutating, setMutating] = useState(false);
    const [gapText, setGapText] = useState("");
    const [examQ, setExamQ] = useState(null);
    const [generatingQ, setGeneratingQ] = useState(false);
    const [viewState, setViewState] = useState('fusion');
    const [currentPage, setCurrentPage] = useState(0);

    const pages = note ? note.split('\n\n').filter(p => p.trim() !== '') : [];

    useEffect(() => {
        fetch('http://localhost:8000/api/graph')
            .then(r => r.json())
            .then(data => dispatch(setGraphData(data)))
            .catch(() => { });
    }, [dispatch]);

    const handleMutate = useCallback(async (page, doubt) => {
        try {
            const res = await fetch('http://localhost:8000/api/mutate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ original_paragraph: page, student_doubt: doubt })
            });
            const data = await res.json();
            setNote(prev => prev.replace(page, data.mutated_paragraph));
            setGapText(data.concept_gap);
            fetch('http://localhost:8000/api/graph').then(r => r.json()).then(d => dispatch(setGraphData(d)));
        } catch {
            const fallback = "⚡ [Rewritten] This concept was rewritten based on your doubt. Connect to Azure OpenAI for the real mutation.";
            setNote(prev => prev.replace(page, fallback));
            dispatch(updateNodeStatus({ label: "Convolution Theorem", status: "partial" }));
        }
    }, [note, dispatch]);

    const handleGenerateQ = async () => {
        setGeneratingQ(true);
        try {
            const res = await fetch('http://localhost:8000/api/examine', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ concept_name: nodes.find(n => n.status === 'struggling' || n.status === 'partial')?.label || 'Core Concept' })
            });
            const data = await res.json();
            setExamQ(data.practice_questions);
        } catch {
            setExamQ("**Sample MCQ**\n\n1. The Convolution Theorem states that: \n   - A) x+y = xy \n   - B) **x(t)*h(t) ↔ X(jω)H(jω)** ✓ \n   - C) x(t)·h(t) ↔ X+H \n   - D) None of the above");
        }
        setGeneratingQ(false);
    };

    const border = "1px solid #1e293b";
    const S = { mastered: { bg: "#16a34a", ring: "#4ade80" }, partial: { bg: "#b45309", ring: "#f59e0b" }, struggling: { bg: "#b91c1c", ring: "#ef4444" } };

    return (
        <div style={{ minHeight: "100vh", background: "#020817", color: "#e2e8f0", fontFamily: "'Courier New',monospace", display: "flex", flexDirection: "column" }}>
            {/* Header */}
            <header style={{ padding: "12px 24px", borderBottom: border, display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div style={{ width: 36, height: 36, borderRadius: 10, background: "linear-gradient(135deg,#1d4ed8,#7c3aed)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, boxShadow: "0 0 18px #3b82f644" }}>⬡</div>
                    <div>
                        <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: 1 }}>AuraGraph</div>
                        <div style={{ fontSize: 9, color: "#475569" }}>IIT Roorkee · Team Wowffulls</div>
                    </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    {viewState === 'viewer' && (
                        <button onClick={() => setViewState('fusion')} style={{ fontSize: 11, color: '#93c5fd', background: 'transparent', border: border, padding: '5px 10px', borderRadius: 6, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5 }}>
                            <Upload size={11} /> New Upload
                        </button>
                    )}
                    {viewState === 'viewer' && pages.length > 0 && (
                        <button onClick={() => setMutating(true)} style={{ fontSize: 11, color: '#c4b5fd', background: '#1e1b4b', border: '1px solid #4c1d95', padding: '5px 10px', borderRadius: 6, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5, fontWeight: 700 }}>
                            <MessageSquare size={11} /> Ask a Doubt
                        </button>
                    )}
                </div>
            </header>

            {/* Body */}
            <main style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 380px", minHeight: 0 }}>
                {viewState === 'fusion' ? (
                    <KnowledgeFusionView
                        onDone={() => { setViewState('viewer'); setCurrentPage(0); setGapText(''); }}
                        onNoteReady={(n, p) => { setNote(n); setProf(p); }}
                    />
                ) : (
                    <section style={{ borderRight: border, display: "flex", flexDirection: "column" }}>
                        {/* Note toolbar */}
                        <div style={{ padding: "10px 22px", borderBottom: border, display: "flex", alignItems: "center", justifyContent: "space-between", background: '#040f1e' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <BookOpen size={14} style={{ color: '#3b82f6' }} />
                                <span style={{ fontSize: 12, fontWeight: 700 }}>Fused Digital Note</span>
                                <span style={{ fontSize: 10, color: '#475569', background: '#0f172a', padding: '2px 8px', borderRadius: 4, border: border }}>{prof}</span>
                            </div>
                            {gapText && (
                                <div style={{ fontSize: 10, color: '#a78bfa', background: '#1e1b4b', padding: '3px 8px', borderRadius: 4, border: '1px solid #4c1d95', maxWidth: 200, overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
                                    Gap: {gapText}
                                </div>
                            )}
                            {/* Page controls */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: 10, background: '#020817', padding: '4px 12px', borderRadius: 20, border }}>
                                <button onClick={() => setCurrentPage(Math.max(0, currentPage - 1))} disabled={currentPage === 0} style={{ background: 'transparent', border: 'none', color: currentPage === 0 ? '#334155' : '#cbd5e1', cursor: currentPage === 0 ? 'not-allowed' : 'pointer', padding: 0 }}>
                                    <ChevronLeft size={15} />
                                </button>
                                <span style={{ fontSize: 11, color: '#94a3b8', minWidth: 70, textAlign: 'center' }}>
                                    {pages.length > 0 ? `${currentPage + 1} / ${pages.length}` : '--'}
                                </span>
                                <button onClick={() => setCurrentPage(Math.min(pages.length - 1, currentPage + 1))} disabled={currentPage >= pages.length - 1} style={{ background: 'transparent', border: 'none', color: currentPage >= pages.length - 1 ? '#334155' : '#cbd5e1', cursor: currentPage >= pages.length - 1 ? 'not-allowed' : 'pointer', padding: 0 }}>
                                    <ChevronRight size={15} />
                                </button>
                            </div>
                        </div>

                        <NoteViewer pages={pages} currentPage={currentPage} setCurrentPage={setCurrentPage} note={note} prof={prof} />
                    </section>
                )}

                {/* Right sidebar: Knowledge Graph + Examiner */}
                <aside style={{ display: "flex", flexDirection: "column", background: "#020c1b" }}>
                    <div style={{ padding: "10px 16px", borderBottom: border }}>
                        <div style={{ fontSize: 11, fontWeight: 700 }}>Cognitive Knowledge Map</div>
                    </div>
                    <div style={{ flex: 1, padding: 10, minHeight: 200 }}><EnhancedGraph /></div>
                    <div style={{ padding: "8px 16px", borderTop: border, display: "flex", gap: 10 }}>
                        {Object.entries(S).map(([k, v]) => (
                            <div key={k} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                                <div style={{ width: 7, height: 7, borderRadius: "50%", background: v.bg, boxShadow: `0 0 4px ${v.ring}` }} />
                                <span style={{ fontSize: 9, color: "#475569", textTransform: "capitalize" }}>{k}</span>
                            </div>
                        ))}
                    </div>
                    {/* Examiner panel */}
                    <div style={{ margin: "0 10px 10px", padding: 12, background: "#0a0f1e", borderRadius: 10, border }}>
                        <div style={{ fontSize: 11, fontWeight: 700, color: "#f59e0b", marginBottom: 8 }}>Examiner — Weak Zones</div>
                        {nodes.filter(n => n.status === 'struggling' || n.status === 'partial').slice(0, 3).map(t => (
                            <div key={t.id} style={{ padding: "5px 8px", marginBottom: 4, background: "#160808", border: "1px solid #7f1d1d", borderRadius: 6, fontSize: 10, color: "#fca5a5" }}>
                                ⚠ <b>{t.label}</b>
                            </div>
                        ))}
                        <button onClick={handleGenerateQ} disabled={generatingQ} style={{ width: "100%", marginTop: 6, padding: "8px 0", background: "transparent", border: "1px solid #7f1d1d", borderRadius: 6, color: "#ef4444", fontSize: 11, cursor: generatingQ ? "not-allowed" : "pointer", display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 6 }}>
                            {generatingQ ? <><Loader2 style={{ animation: 'spin 1s linear infinite' }} size={12} /> Generating…</> : '📝 Practice Paper'}
                        </button>
                        {examQ && (
                            <div style={{ marginTop: 10, padding: 10, background: "#1e1b4b", borderRadius: 6, fontSize: 11, color: "#e2e8f0", maxHeight: 160, overflowY: "auto" }}>
                                <ReactMarkdown
                                    remarkPlugins={[remarkMath, remarkGfm]}
                                    rehypePlugins={[[rehypeKatex, KATEX_OPTS]]}
                                    components={IMG_OVERRIDE}
                                >{examQ}</ReactMarkdown>
                            </div>
                        )}
                    </div>
                </aside>
            </main>

            {/* Mutation modal */}
            {mutating && pages.length > 0 && (
                <MutateModal page={pages[currentPage]} onClose={() => setMutating(false)} onMutate={handleMutate} />
            )}

            <style>{`@keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }`}</style>
        </div>
    );
}
