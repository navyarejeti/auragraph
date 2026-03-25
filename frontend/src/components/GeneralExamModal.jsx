import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';
import { X, Loader2 } from 'lucide-react';
import { API, authHeaders } from './utils';

export default function GeneralExamModal({ nodes, notebookId, onClose, onQuizCompleted }) {
    const allLabels = nodes.map(n => n.label);
    const [questions, setQuestions] = React.useState([]);
    const [loading, setLoading] = React.useState(true);
    const [qIdx, setQIdx] = React.useState(0);
    const [selected, setSelected] = React.useState(null);
    const [revealed, setRevealed] = React.useState(false);
    const [score, setScore] = React.useState(0);
    const [done, setDone] = React.useState(false);
    const rewardsSent = React.useRef(false);

    React.useEffect(() => {
        (async () => {
            try {
                const res = await fetch(`${API}/api/general-exam`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', ...authHeaders() },
                    body: JSON.stringify({
                        all_concepts: allLabels,
                        ...(notebookId ? { notebook_id: notebookId } : {}),
                    }),
                });
                const data = await res.json();
                setQuestions(data.questions || []);
            } catch {
                setQuestions([]);
            } finally {
                setLoading(false);
            }
        })();
    }, []);

    const current = questions[qIdx];
    const total = questions.length;

    const handleSelect = (opt) => {
        if (revealed) return;
        setSelected(opt);
        setRevealed(true);
        if (opt === current.correct) setScore(s => s + 1);
    };

    const next = () => {
        if (qIdx + 1 >= total) { setDone(true); return; }
        setQIdx(i => i + 1);
        setSelected(null);
        setRevealed(false);
    };

    const pct = total > 0 ? Math.round((score / total) * 100) : 0;

    const [xpEarned, setXpEarned] = React.useState(0);
    React.useEffect(() => {
        if (!done || loading || rewardsSent.current || total <= 0) return;
        rewardsSent.current = true;
        const gained = onQuizCompleted?.(score, total);
        if (gained > 0) setXpEarned(gained);
    }, [done, loading, score, total, onQuizCompleted]);

    return (
        <div className="modal-backdrop" onClick={onClose}>
            <div className="modal fade-in-scale" onClick={e => e.stopPropagation()} style={{ maxWidth: 560, width: '96vw' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{ fontSize: 22 }}>📝</div>
                        <div>
                            <h3 style={{ marginBottom: 1 }}>General Exam</h3>
                            <p style={{ fontSize: 11, color: 'var(--text3)' }}>Test all your concepts</p>
                        </div>
                    </div>
                    <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)' }}><X size={18} /></button>
                </div>

                {loading && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '30px 0', justifyContent: 'center', color: 'var(--text3)', fontSize: 13 }}>
                        <Loader2 className="spin" size={18} /> Generating exam questions…
                    </div>
                )}

                {!loading && done && (
                    <div style={{ textAlign: 'center', padding: '20px 0' }}>
                        <div style={{ fontSize: 48, marginBottom: 12 }}>{pct >= 70 ? '🏆' : pct >= 40 ? '📈' : '💪'}</div>
                        <div style={{ fontSize: 22, fontWeight: 800, marginBottom: 6 }}>{score}/{total} correct</div>
            {xpEarned > 0 && (
                <div style={{ fontSize: 12, color: '#7C3AED', fontWeight: 700, marginBottom: 8 }}>
                    ⚡ +{xpEarned} Aura XP earned!{pct >= 80 ? ' (includes accuracy bonus 🎯)' : ''}
                </div>
            )}
                        <div style={{ fontSize: 14, color: 'var(--text3)', marginBottom: 20 }}>
                            {pct >= 70 ? 'Excellent! You have a strong grasp of the material.' : pct >= 40 ? 'Good effort — review the topics you missed.' : 'Keep studying — revisit your notes and try again.'}
                        </div>
                        <div className="progress-bar-track" style={{ marginBottom: 20 }}>
                            <div className="progress-bar-fill" style={{ width: `${pct}%`, background: pct >= 70 ? 'linear-gradient(90deg,#10B981,#34D399)' : pct >= 40 ? 'linear-gradient(90deg,#F59E0B,#FCD34D)' : 'linear-gradient(90deg,#EF4444,#FCA5A5)' }} />
                        </div>
                        <button className="btn btn-primary" onClick={onClose}>Done</button>
                    </div>
                )}

                {!loading && !done && total === 0 && (
                    <div style={{ textAlign: 'center', padding: '30px 0' }}>
                        <div style={{ fontSize: 48, marginBottom: 12 }}>⚠️</div>
                        <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 6, color: 'var(--text)' }}>Could not generate questions</div>
                        <div style={{ fontSize: 13, color: 'var(--text3)', marginBottom: 20 }}>Please try again later.</div>
                        <button className="btn btn-primary" onClick={onClose}>Close</button>
                    </div>
                )}

                {!loading && !done && current && (
                    <>
                        <div style={{ marginBottom: 14 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text3)', marginBottom: 5, fontWeight: 600 }}>
                                <span>Question {qIdx + 1} of {total}</span>
                                <span style={{ color: 'var(--ag-emerald)' }}>Score: {score}</span>
                            </div>
                            <div className="progress-bar-track">
                                <div className="progress-bar-fill" style={{ width: `${((qIdx) / total) * 100}%`, background: 'linear-gradient(90deg,#2563EB,#7C3AED)' }} />
                            </div>
                        </div>

                        {current.concept && (
                            <div style={{ marginBottom: 10, display: 'inline-flex', alignItems: 'center', gap: 5, background: 'var(--purple-light)', color: 'var(--purple)', borderRadius: 6, padding: '3px 10px', fontSize: 11, fontWeight: 600 }}>
                                📝 {current.concept}
                            </div>
                        )}

                        <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.7, color: 'var(--text)', marginBottom: 16, padding: '12px 14px', background: 'var(--surface)', borderRadius: 10, border: '1px solid var(--border)' }}>
                            <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]}>{current.question}</ReactMarkdown>
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 16 }}>
                            {['A', 'B', 'C', 'D'].map(opt => (
                                <button key={opt}
                                    className={`sniper-option${revealed && opt === current.correct ? ' correct' : revealed && opt === selected && opt !== current.correct ? ' wrong' : ''}`}
                                    onClick={() => handleSelect(opt)}
                                    disabled={revealed}
                                >
                                    <span style={{ fontWeight: 700, marginRight: 8 }}>{opt})</span>
                                    <span style={{ flex: 1 }}><ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]}>{current.options?.[opt] || ''}</ReactMarkdown></span>
                                    {revealed && opt === current.correct && <span style={{ flexShrink: 0 }}>✅</span>}
                                    {revealed && opt === selected && opt !== current.correct && <span style={{ flexShrink: 0 }}>❌</span>}
                                </button>
                            ))}
                        </div>

                        {revealed && current.explanation && (
                            <div style={{ padding: '10px 12px', borderRadius: 8, background: selected === current.correct ? '#DCFCE7' : '#FEF2F2', border: `1px solid ${selected === current.correct ? '#BBF7D0' : '#FECACA'}`, fontSize: 12, lineHeight: 1.7, marginBottom: 14, color: selected === current.correct ? '#065F46' : '#991B1B' }}>
                                <span style={{ fontWeight: 700 }}>Explanation: </span>
                                <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]}>{current.explanation}</ReactMarkdown>
                            </div>
                        )}

                        {revealed && (
                            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                                <button className="btn btn-primary" onClick={next}>
                                    {qIdx + 1 >= total ? 'See Results' : 'Next Question →'}
                                </button>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}
