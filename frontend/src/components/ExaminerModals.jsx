import React, { useState, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';
import { CheckCircle2, X, Loader2, RefreshCw } from 'lucide-react';
import { API, authHeaders } from './utils';

// ── PracticeQuestions ─────────────────────────────────────────────────────────
export function PracticeQuestions({ text, notebookId = '', concept = '' }) {
    const [revealed, setRevealed] = useState(new Set());
    const blocks = text.split(/(?=^Q\d+\.)/m).filter(b => b.trim());
    if (!blocks.length) {
        return <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false, errorColor: '#cc0000' }]]}>{text}</ReactMarkdown>;
    }
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {blocks.map((block, i) => {
                const markerIdx = block.search(/✅|Correct:/);
                const hasAnswer = markerIdx !== -1;
                const questionPart = hasAnswer ? block.slice(0, markerIdx).trimEnd() : block;
                const answerPart = hasAnswer ? block.slice(markerIdx) : '';
                const isRevealed = revealed.has(i);
                return (
                    <div key={i} style={{ background: 'var(--bg)', borderRadius: 10, border: '1px solid var(--border)', overflow: 'hidden' }}>
                        <div style={{ padding: '14px 16px', fontSize: 13, lineHeight: 1.8 }}>
                            <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false, errorColor: '#cc0000' }]]}>{questionPart}</ReactMarkdown>
                        </div>
                        {hasAnswer && (
                            <div style={{ borderTop: '1px solid var(--border)' }}>
                                {!isRevealed ? (
                                    <button onClick={() => {
                                        setRevealed(prev => new Set([...prev, i]));
                                        // Track as a quiz attempt (revealing = attempting)
                                        if (notebookId) {
                                            fetch('/api/behaviour/track-quiz', {
                                                method: 'POST',
                                                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('ag_token') || ''}` },
                                                body: JSON.stringify({ notebook_id: notebookId, concept: concept || '', question: questionPart.slice(0, 200), correct: true }),
                                            }).catch(() => {});
                                        }
                                    }} style={{ width: '100%', padding: '9px 16px', background: 'var(--surface)', border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 600, color: 'var(--ag-purple)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
                                        <CheckCircle2 size={13} /> Show Answer
                                    </button>
                                ) : (
                                    <div style={{ padding: '12px 16px', background: '#F0FDF4', fontSize: 13, lineHeight: 1.8 }}>
                                        <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false, errorColor: '#cc0000' }]]}>{answerPart}</ReactMarkdown>
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
}

// ── ExaminerModal ─────────────────────────────────────────────────────────────
export function ExaminerModal({ concept, notebookId, onClose }) {
    const [questions, setQuestions] = useState('');
    const [loading, setLoading] = useState(true);
    const [customInstruction, setCustomInstruction] = useState('');

    const generate = useCallback(async (ci) => {
        setLoading(true);
        try {
            const res = await fetch(`${API}/api/examine`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
                body: JSON.stringify({
                    concept_name: concept,
                    ...(notebookId ? { notebook_id: notebookId } : {}),
                    ...(ci.trim() ? { custom_instruction: ci.trim() } : {}),
                }),
            });
            const data = await res.json();
            setQuestions(data.practice_questions);
        } catch { setQuestions(`## Practice Questions: ${concept}\n\nBackend not reachable.`); }
        finally { setLoading(false); }
    }, [concept]);

    useEffect(() => { generate(''); }, [concept]);

    return (
        <div className="modal-backdrop" onClick={onClose}>
            <div className="modal fade-in" onClick={e => e.stopPropagation()} style={{ width: 600, maxWidth: '96vw', maxHeight: '80vh', display: 'flex', flexDirection: 'column' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                    <div><h3 style={{ marginBottom: 2 }}>Practice Questions</h3><p style={{ fontSize: 12, color: 'var(--text3)' }}>Generated for: <b>{concept}</b></p></div>
                    <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)' }}><X size={18} /></button>
                </div>
                <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                    <input
                        value={customInstruction}
                        onChange={e => setCustomInstruction(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter') generate(customInstruction); }}
                        placeholder="Custom focus, e.g. numerical only, proof-based, match exam pattern…"
                        style={{ flex: 1, fontSize: 12, padding: '7px 11px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', outline: 'none', fontFamily: 'inherit' }}
                    />
                    <button onClick={() => generate(customInstruction)} disabled={loading} className="btn btn-secondary btn-sm" style={{ flexShrink: 0, gap: 5 }}>
                        {loading ? <Loader2 className="spin" size={13} /> : <RefreshCw size={13} />}
                        {loading ? 'Generating…' : 'Generate'}
                    </button>
                </div>
                <div style={{ flex: 1, overflowY: 'auto', background: 'var(--surface)', borderRadius: 10, padding: 16, border: '1px solid var(--border)' }}>
                    {loading
                        ? <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text3)', fontSize: 13 }}><Loader2 className="spin" size={16} /> Generating questions…</div>
                        : <PracticeQuestions text={questions} notebookId={notebookId} concept={concept} />}
                </div>
                <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end' }}><button className="btn btn-secondary btn-sm" onClick={onClose}>Close</button></div>
            </div>
        </div>
    );
}
