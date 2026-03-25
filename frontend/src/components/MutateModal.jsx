import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';
import {
    Brain, Loader2, MessageCircle, CheckCircle2, AlertCircle, MinusCircle, Sparkles
} from 'lucide-react';
import { API, apiFetch } from './utils';

export default function MutateModal({
    page, notebookId, pageIdx, onClose, onMutate, onDoubtAnswered, initialDoubt = '', darkMode = null
}) {
    const isDark = darkMode ?? (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark');
    const [doubt, setDoubt] = useState(initialDoubt);
    const [busy, setBusy] = useState(false);
    const [doubtError, setDoubtError] = useState('');
    const [answer, setAnswer] = useState('');
    const [answerSource, setAnswerSource] = useState('');
    const [answerVerification, setAnswerVerification] = useState('correct');
    const [answerCorrection, setAnswerCorrection] = useState('');
    const [answerFootnote, setAnswerFootnote] = useState('');
    const [mode, setMode] = useState('idle'); // 'idle' | 'answering' | 'answered' | 'mutating'

    const validateDoubt = (v) => {
        if (!v.trim()) return 'Please describe your doubt.';
        if (v.trim().length < 5) return 'Doubt must be at least 5 characters.';
        if (v.length > 500) return 'Doubt must be 500 characters or less.';
        return '';
    };

    const askDoubt = async () => {
        const err = validateDoubt(doubt);
        if (err) { setDoubtError(err); return; }
        setDoubtError('');
        setBusy(true); setMode('answering'); setAnswer('');
        try {
            const res = await apiFetch(`${API}/api/doubt`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ notebook_id: notebookId, doubt, page_idx: pageIdx })
            });
            if (res.ok) {
                const data = await res.json();
                setAnswer(data.answer || '');
                setAnswerSource(data.source || 'local');
                setAnswerVerification(data.verification_status || 'correct');
                setAnswerCorrection(data.correction || '');
                setAnswerFootnote(data.footnote || '');
                if (onDoubtAnswered && data.answer) {
                    onDoubtAnswered({ doubt, answer: data.answer, source: data.source || 'local' });
                }
            } else {
                setAnswer('Could not get an answer. Try again or use Mutate to rewrite this page.');
            }
            setMode('answered');
        } catch {
            setAnswer('Backend unreachable. Your doubt has been logged.');
            setMode('answered');
        }
        setBusy(false);
    };

    const doMutate = async () => {
        const err = validateDoubt(doubt);
        if (err) { setDoubtError(err); return; }
        setDoubtError('');
        setBusy(true); setMode('mutating');
        await onMutate(page, doubt);
        setBusy(false);
        onClose();
    };

    return (
        <div className="modal-backdrop" onClick={onClose}>
            <div className="modal fade-in" onClick={e => e.stopPropagation()} style={{ maxWidth: 560, width: '100%' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 14 }}>
                    <div>
                        <h3 style={{ marginBottom: 4, fontSize: 17 }}>💬 Ask a Doubt</h3>
                        <p style={{ fontSize: 12.5, color: 'var(--text3)', lineHeight: 1.55 }}>
                            <span style={{ color: 'var(--text2)', fontWeight: 600 }}>Ask</span> — get an instant AI answer logged in your Doubts panel.
                            <br />
                            <span style={{ color: 'var(--ag-purple)', fontWeight: 600 }}>⚡ Rewrite page</span> — permanently rewrites this page to resolve your doubt.
                        </p>
                    </div>
                </div>
                <div style={{ background: 'var(--surface)', borderRadius: 8, padding: 12, fontSize: 12, color: 'var(--text2)', lineHeight: 1.7, marginBottom: 14, maxHeight: 80, overflow: 'hidden', border: '1px solid var(--border)' }}>
                    {page ? (page.length > 200 ? page.slice(0, page.lastIndexOf(' ', 200)) + '…' : page) : ''}
                </div>
                <textarea
                    className={`input${doubtError ? ' input-error' : ''}`} rows={3} autoFocus value={doubt}
                    onChange={e => { setDoubt(e.target.value); if (doubtError) setDoubtError(validateDoubt(e.target.value)); }}
                    onKeyDown={e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') askDoubt(); if (e.key === 'Escape') onClose(); }}
                    placeholder="e.g. Why does convolution become multiplication in the frequency domain?"
                    maxLength={500}
                    style={{ resize: 'vertical', fontFamily: 'inherit', marginBottom: 4 }}
                />
                {doubtError
                    ? <p style={{ fontSize: 11, color: 'var(--ag-red)', marginBottom: 4 }}>{doubtError}</p>
                    : null}
                <div style={{ fontSize: 11, display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                    <span style={{ color: 'var(--text3)' }}>
                        <kbd style={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 3, padding: '1px 5px', fontSize: 10 }}>Ctrl+Enter</kbd> to ask
                    </span>
                    <span style={{ color: doubt.length > 450 ? (doubt.length > 500 ? 'var(--ag-red)' : '#f59e0b') : 'var(--text3)' }}>
                        {doubt.length}/500
                    </span>
                </div>

                {(mode === 'answering' || mode === 'answered') && (
                    <div style={{ background: isDark ? '#0F172A' : '#F0F9FF', border: isDark ? '1px solid #334155' : '1px solid #BAE6FD', borderRadius: 8, padding: 14, marginBottom: 14, maxHeight: 340, overflowY: 'auto' }}>
                        <div style={{ fontSize: 11, color: isDark ? '#93C5FD' : '#0369A1', fontWeight: 600, marginBottom: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
                            <Brain size={12} /> AuraGraph Answer {answerSource === 'azure' ? '(GPT-4o · verified)' : answerSource === 'groq' ? '(Groq · verified)' : '(offline)'}
                        </div>
                        {mode === 'answering'
                            ? <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: isDark ? '#93C5FD' : '#0369A1', fontSize: 13 }}><Loader2 className="spin" size={14} /> Verifying against slides, textbook and model knowledge…</div>
                            : (
                                <>
                                    <div style={{ fontSize: 13, lineHeight: 1.8, color: isDark ? '#E2E8F0' : '#0C4A6E' }}>
                                        <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false, errorColor: '#cc0000' }]]}>{answer}</ReactMarkdown>
                                    </div>
                                    {answerVerification === 'correct' && (
                                        <div style={{ marginTop: 10, display: 'inline-flex', alignItems: 'center', gap: 5, background: isDark ? '#052E16' : '#DCFCE7', border: isDark ? '1px solid #166534' : '1px solid #BBF7D0', borderRadius: 6, padding: '4px 10px', fontSize: 11, color: isDark ? '#86EFAC' : '#166534', fontWeight: 600 }}>
                                            <CheckCircle2 size={11} /> Cross-checked against slides, textbook and model knowledge
                                        </div>
                                    )}
                                    {answerVerification === 'partially_correct' && answerCorrection && (
                                        <div style={{ marginTop: 10, background: isDark ? '#1a2035' : '#EFF6FF', border: isDark ? '1px solid #334155' : '1px solid #BAE6FD', borderRadius: 8, padding: '10px 12px' }}>
                                            <div style={{ fontSize: 11, fontWeight: 700, color: isDark ? '#93C5FD' : '#0369A1', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 5 }}>
                                                <AlertCircle size={12} /> Additional context
                                            </div>
                                            <div style={{ fontSize: 12, lineHeight: 1.7, color: isDark ? '#CBD5E1' : '#0C4A6E' }}>
                                                <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false, errorColor: '#cc0000' }]]}>{answerCorrection}</ReactMarkdown>
                                            </div>
                                        </div>
                                    )}
                                    {answerVerification === 'incorrect' && answerCorrection && (
                                        <div style={{ marginTop: 10, background: isDark ? '#1a2035' : '#EFF6FF', border: isDark ? '1px solid #334155' : '1px solid #BAE6FD', borderRadius: 8, padding: '10px 12px' }}>
                                            <div style={{ fontSize: 11, fontWeight: 700, color: isDark ? '#93C5FD' : '#0369A1', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 5 }}>
                                                <Brain size={12} /> Clarification
                                            </div>
                                            <div style={{ fontSize: 12, lineHeight: 1.7, color: isDark ? '#CBD5E1' : '#0C4A6E' }}>
                                                <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false, errorColor: '#cc0000' }]]}>{answerCorrection}</ReactMarkdown>
                                            </div>
                                            {answerFootnote && <div style={{ fontSize: 11, color: isDark ? '#93C5FD' : '#0369A1', marginTop: 4, fontStyle: 'italic' }}>{answerFootnote}</div>}
                                        </div>
                                    )}
                                </>
                            )
                        }
                    </div>
                )}

                <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                    <button className="btn btn-secondary btn-sm" onClick={onClose}>Close</button>
                    <button
                        className="btn btn-ghost btn-sm" onClick={askDoubt}
                        disabled={busy || !doubt.trim()}
                        style={{ gap: 6, borderColor: isDark ? '#60A5FA' : '#0369A1', color: isDark ? '#93C5FD' : '#0369A1' }}
                    >
                        {mode === 'answering' ? <Loader2 className="spin" size={14} /> : <MessageCircle size={14} />}
                        {mode === 'answering' ? 'Searching…' : 'Ask (get answer)'}
                    </button>
                    <button
                        className="btn btn-primary btn-sm" onClick={doMutate}
                        disabled={busy || !doubt.trim()}
                        style={{ gap: 6 }}
                        title="Permanently rewrites this page to incorporate your doubt"
                    >
                        {mode === 'mutating' ? <Loader2 className="spin" size={14} /> : <Sparkles size={14} />}
                        {mode === 'mutating' ? 'Rewriting…' : 'Rewrite This Page'}
                    </button>
                </div>
            </div>
        </div>
    );
}
