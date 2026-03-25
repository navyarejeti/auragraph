/**
 * FeedbackWidget — floating AI-assistant-style feedback bubble.
 * Two modes:
 *   'dashboard'  — detailed multi-section form (notes quality, quizzes, mutation, UI)
 *   'notebook'   — brief single issue report pinned to a specific notebook
 */
import React, { useState, useRef, useEffect } from 'react';
import { MessageCircle, X, Star, Send, ChevronDown, ChevronUp, CheckCircle2, Loader2 } from 'lucide-react';
import { API, authHeaders } from './utils';

const CATEGORIES = [
    { key: 'notes',    label: '📝 Notes quality',       placeholder: 'e.g. Notes were too long, missing diagrams...' },
    { key: 'questions',label: '🎯 Quiz questions',       placeholder: 'e.g. Options were confusing, wrong difficulty...' },
    { key: 'mutation', label: '⚡ Note mutation/doubts', placeholder: 'e.g. Mutation rewrote too much, wrong answer...' },
    { key: 'ui',       label: '🎨 App UI/UX',            placeholder: 'e.g. Hard to find a feature, slow loading...' },
    { key: 'general',  label: '💬 General',              placeholder: 'Anything else on your mind...' },
];

function StarRating({ value, onChange, label }) {
    const [hover, setHover] = useState(0);
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <span style={{ fontSize: 12, color: 'var(--text2)', fontWeight: 600, minWidth: 80 }}>{label}</span>
            <div style={{ display: 'flex', gap: 3 }}>
                {[1,2,3,4,5].map(n => (
                    <button
                        key={n}
                        type="button"
                        onMouseEnter={() => setHover(n)}
                        onMouseLeave={() => setHover(0)}
                        onClick={() => onChange(n)}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 2, color: n <= (hover || value) ? '#F59E0B' : 'var(--border2)', transition: 'color 0.1s' }}
                    >
                        <Star size={18} fill={n <= (hover || value) ? '#F59E0B' : 'none'} />
                    </button>
                ))}
            </div>
            {value > 0 && <span style={{ fontSize: 11, color: 'var(--text3)' }}>{['','Poor','Fair','Good','Great','Excellent'][value]}</span>}
        </div>
    );
}

// ── Detailed Dashboard Feedback ────────────────────────────────────────────────
function DetailedFeedbackForm({ notebookId, onDone }) {
    const [rating, setRating] = useState(0);
    const [category, setCategory] = useState('general');
    const [liked, setLiked] = useState('');
    const [disliked, setDisliked] = useState('');
    const [message, setMessage] = useState('');
    const [submitting, setSubmitting] = useState(false);
    const cat = CATEGORIES.find(c => c.key === category) || CATEGORIES[4];

    const submit = async () => {
        if (!message.trim() && !liked.trim() && !disliked.trim()) return;
        setSubmitting(true);
        try {
            await fetch(`${API}/api/feedback`, {
                method: 'POST',
                headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    context: notebookId ? 'notebook' : 'dashboard',
                    notebook_id: notebookId || null,
                    rating,
                    liked,
                    disliked,
                    category,
                    message,
                    page_url: window.location.pathname,
                }),
            });
        } catch { /* offline — silently ignore */ }
        setSubmitting(false);
        onDone();
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
            <StarRating value={rating} onChange={setRating} label="Overall" />

            {/* Category selector */}
            <div style={{ marginBottom: 12 }}>
                <label style={{ fontSize: 11, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', display: 'block', marginBottom: 6 }}>What are you reviewing?</label>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                    {CATEGORIES.map(c => (
                        <button key={c.key} type="button" onClick={() => setCategory(c.key)}
                            style={{ padding: '4px 10px', borderRadius: 20, border: `1px solid ${category === c.key ? 'var(--ag-purple)' : 'var(--border)'}`, background: category === c.key ? 'var(--ag-purple-bg)' : 'var(--surface)', color: category === c.key ? 'var(--ag-purple)' : 'var(--text2)', fontSize: 11, fontWeight: 600, cursor: 'pointer', transition: 'all 0.12s' }}>
                            {c.label}
                        </button>
                    ))}
                </div>
            </div>

            <div style={{ marginBottom: 10 }}>
                <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text2)', display: 'block', marginBottom: 5 }}>👍 What worked well?</label>
                <textarea
                    rows={2}
                    value={liked}
                    onChange={e => setLiked(e.target.value)}
                    placeholder="What did you like?"
                    maxLength={500}
                    style={{ width: '100%', fontSize: 12, padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', resize: 'none', fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box' }}
                />
            </div>

            <div style={{ marginBottom: 10 }}>
                <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text2)', display: 'block', marginBottom: 5 }}>👎 What could be better?</label>
                <textarea
                    rows={2}
                    value={disliked}
                    onChange={e => setDisliked(e.target.value)}
                    placeholder="What frustrated you or didn't work?"
                    maxLength={500}
                    style={{ width: '100%', fontSize: 12, padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', resize: 'none', fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box' }}
                />
            </div>

            <div style={{ marginBottom: 14 }}>
                <label style={{ fontSize: 12, fontWeight: 600, color: 'var(--text2)', display: 'block', marginBottom: 5 }}>💬 Anything else?</label>
                <textarea
                    rows={2}
                    value={message}
                    onChange={e => setMessage(e.target.value)}
                    placeholder={cat.placeholder}
                    maxLength={1000}
                    style={{ width: '100%', fontSize: 12, padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', resize: 'none', fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box' }}
                />
            </div>

            <button
                type="button"
                onClick={submit}
                disabled={submitting || (!message.trim() && !liked.trim() && !disliked.trim())}
                style={{ width: '100%', padding: '10px', borderRadius: 10, border: 'none', background: 'linear-gradient(135deg, var(--ag-purple), #2563EB)', color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 7, opacity: (!message.trim() && !liked.trim() && !disliked.trim()) ? 0.5 : 1, transition: 'opacity 0.15s' }}
            >
                {submitting ? <Loader2 className="spin" size={14} /> : <Send size={14} />}
                {submitting ? 'Sending…' : 'Send Feedback'}
            </button>
        </div>
    );
}

// ── Brief Notebook Feedback ────────────────────────────────────────────────────
function BriefFeedbackForm({ notebookId, onDone }) {
    const [category, setCategory] = useState('notes');
    const [message, setMessage] = useState('');
    const [submitting, setSubmitting] = useState(false);

    const submit = async () => {
        if (!message.trim()) return;
        setSubmitting(true);
        try {
            await fetch(`${API}/api/feedback`, {
                method: 'POST',
                headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    context: 'notebook',
                    notebook_id: notebookId,
                    category,
                    message,
                    page_url: window.location.pathname,
                }),
            });
        } catch { }
        setSubmitting(false);
        onDone();
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                {CATEGORIES.slice(0, 4).map(c => (
                    <button key={c.key} type="button" onClick={() => setCategory(c.key)}
                        style={{ padding: '3px 9px', borderRadius: 20, border: `1px solid ${category === c.key ? 'var(--ag-purple)' : 'var(--border)'}`, background: category === c.key ? 'var(--ag-purple-bg)' : 'var(--surface)', color: category === c.key ? 'var(--ag-purple)' : 'var(--text2)', fontSize: 10, fontWeight: 600, cursor: 'pointer' }}>
                        {c.label}
                    </button>
                ))}
            </div>
            <textarea
                autoFocus
                rows={3}
                value={message}
                onChange={e => setMessage(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit(); }}
                placeholder="Briefly describe the issue you faced…"
                maxLength={500}
                style={{ width: '100%', fontSize: 12, padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', resize: 'none', fontFamily: 'inherit', outline: 'none', boxSizing: 'border-box' }}
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 10, color: 'var(--text3)' }}>Ctrl+Enter to send</span>
                <button type="button" onClick={submit} disabled={submitting || !message.trim()}
                    style={{ padding: '6px 14px', borderRadius: 8, border: 'none', background: 'var(--ag-purple)', color: '#fff', fontSize: 12, fontWeight: 700, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5, opacity: !message.trim() ? 0.5 : 1 }}>
                    {submitting ? <Loader2 className="spin" size={12} /> : <Send size={12} />} Send
                </button>
            </div>
        </div>
    );
}

// ── Thank-you screen ───────────────────────────────────────────────────────────
function ThankYou({ onClose }) {
    useEffect(() => { const t = setTimeout(onClose, 3000); return () => clearTimeout(t); }, []);
    return (
        <div style={{ textAlign: 'center', padding: '24px 16px' }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>🙏</div>
            <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--text)', marginBottom: 6 }}>Thank you!</div>
            <div style={{ fontSize: 13, color: 'var(--text3)', lineHeight: 1.6 }}>Your feedback helps us make AuraGraph better for every student.</div>
        </div>
    );
}

// ── Main FeedbackWidget ────────────────────────────────────────────────────────
export default function FeedbackWidget({ mode = 'dashboard', notebookId = null, darkMode = false }) {
    const [open, setOpen] = useState(false);
    const [done, setDone] = useState(false);
    const ref = useRef(null);

    // Close on outside click
    useEffect(() => {
        if (!open) return;
        const onOut = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
        setTimeout(() => document.addEventListener('mousedown', onOut), 100);
        return () => document.removeEventListener('mousedown', onOut);
    }, [open]);

    const handleDone = () => { setDone(true); };
    const handleClose = () => { setOpen(false); setTimeout(() => setDone(false), 400); };

    return (
        <div ref={ref} style={{ position: 'fixed', bottom: 24, right: 24, zIndex: 8000 }}>
            {/* Popover panel */}
            {open && (
                <div style={{
                    position: 'absolute', bottom: 60, right: 0,
                    width: mode === 'dashboard' ? 360 : 300,
                    background: 'var(--bg)',
                    border: '1px solid var(--border)',
                    borderRadius: 16,
                    boxShadow: '0 8px 48px rgba(0,0,0,0.18)',
                    overflow: 'hidden',
                    animation: 'feedbackSlideUp 0.18s ease',
                }}>
                    {/* Header */}
                    <div style={{ background: 'linear-gradient(135deg, var(--ag-purple), #2563EB)', padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                        <div>
                            <div style={{ fontSize: 14, fontWeight: 800, color: '#fff' }}>
                                {mode === 'dashboard' ? '💬 Share your feedback' : '⚠ Report an issue'}
                            </div>
                            <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.75)', marginTop: 1 }}>
                                {mode === 'dashboard' ? 'Help us make AuraGraph better' : 'Something wrong? Tell us quickly.'}
                            </div>
                        </div>
                        <button onClick={handleClose} style={{ background: 'rgba(255,255,255,0.2)', border: 'none', borderRadius: 8, cursor: 'pointer', color: '#fff', padding: 6, display: 'flex' }}>
                            <X size={14} />
                        </button>
                    </div>

                    <div style={{ padding: '16px 18px' }}>
                        {done
                            ? <ThankYou onClose={handleClose} />
                            : mode === 'dashboard'
                                ? <DetailedFeedbackForm notebookId={notebookId} onDone={handleDone} />
                                : <BriefFeedbackForm notebookId={notebookId} onDone={handleDone} />
                        }
                    </div>
                </div>
            )}

            {/* Floating bubble button */}
            <button
                onClick={() => setOpen(o => !o)}
                title={open ? 'Close feedback' : 'Share feedback'}
                style={{
                    width: 52, height: 52, borderRadius: '50%',
                    background: open ? 'var(--ag-purple)' : 'linear-gradient(135deg, var(--ag-purple), #2563EB)',
                    border: 'none', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    boxShadow: '0 4px 20px rgba(124,58,237,0.45)',
                    color: '#fff',
                    transition: 'all 0.2s',
                    transform: open ? 'scale(0.9)' : 'scale(1)',
                }}
                onMouseEnter={e => { if (!open) e.currentTarget.style.transform = 'scale(1.08)'; }}
                onMouseLeave={e => { if (!open) e.currentTarget.style.transform = 'scale(1)'; }}
            >
                {open ? <X size={20} /> : <MessageCircle size={22} />}
            </button>

            {/* Pulse dot indicator */}
            {!open && (
                <span style={{ position: 'absolute', top: 0, right: 0, width: 12, height: 12, borderRadius: '50%', background: '#10B981', border: '2px solid var(--bg)', animation: 'feedbackPulse 2s ease-in-out infinite' }} />
            )}
        </div>
    );
}
