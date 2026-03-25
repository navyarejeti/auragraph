import React, { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';
import { Brain, CheckCircle2, AlertCircle, MinusCircle, X, ChevronRight, Loader2 } from 'lucide-react';
import { ExaminerModal } from './ExaminerModals';
import SniperExamModal from './SniperExamModal';
import GeneralExamModal from './GeneralExamModal';
import { KnowledgeGraph, SC } from './Graph';
import { authHeaders, API } from './utils';

// ─── Question Cards ───────────────────────────────────────────────────────────
export function QuestionCards({ questions, level, onAllAssessed, darkMode = null }) {
    const isDark = darkMode ?? (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark');
    const [revealed, setRevealed] = useState(new Set());
    const [assessments, setAssessments] = useState({});
    const LC = {
        mastered:  { bg: isDark ? '#052E16' : '#DCFCE7', border: isDark ? '#166534' : '#BBF7D0', accent: 'var(--ag-emerald)', text: isDark ? '#BBF7D0' : '#065F46' },
        partial:   { bg: isDark ? '#422006' : '#FEF9C3', border: isDark ? '#92400E' : '#FDE68A', accent: '#D97706', text: isDark ? '#FDE68A' : '#78350F' },
        struggling:{ bg: isDark ? '#3F1D1D' : '#FEF2F2', border: isDark ? '#7F1D1D' : '#FECACA', accent: '#DC2626', text: isDark ? '#FECACA' : '#7F1D1D' },
    };
    const lc = LC[level] || LC.partial;

    const markAssessment = (i, gotIt) => {
        const next = { ...assessments, [i]: gotIt };
        setAssessments(next);
        const total = (questions || []).length;
        const assessed = Object.keys(next).length;
        const correct = Object.values(next).filter(Boolean).length;
        if (assessed === total && total > 0) onAllAssessed?.(correct, total);
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {(questions || []).map((q, i) => {
                const isRev = revealed.has(i);
                const wasAssessed = assessments[i] !== undefined;
                return (
                    <div key={i} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
                        <div style={{ padding: '10px 12px', fontSize: 12.5, lineHeight: 1.65, color: 'var(--text)' }}>
                            <span style={{ fontWeight: 700, color: 'var(--ag-purple)', marginRight: 5 }}>{i + 1})</span>
                            <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]} components={{ p: ({ children }) => <span>{children}</span> }}>{q.question || ''}</ReactMarkdown>
                        </div>
                        <div style={{ padding: '4px 12px 8px', display: 'flex', flexDirection: 'column', gap: 4, borderTop: '1px solid var(--border)' }}>
                            {['A', 'B', 'C', 'D'].map(opt => {
                                const isCorrect = isRev && opt === q.correct;
                                return (
                                    <div key={opt} style={{ display: 'flex', gap: 7, padding: '5px 9px', borderRadius: 7, background: isCorrect ? lc.bg : 'transparent', border: `1px solid ${isCorrect ? lc.border : 'transparent'}`, fontSize: 12, lineHeight: 1.5, transition: 'background 0.2s' }}>
                                        <span style={{ fontWeight: 700, color: isCorrect ? lc.accent : '#9CA3AF', minWidth: 16, flexShrink: 0 }}>{opt})</span>
                                        <span style={{ color: isCorrect ? lc.text : 'var(--text2)', flex: 1 }}>
                                            <ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]} components={{ p: ({ children }) => <span>{children}</span> }}>{q.options?.[opt] || ''}</ReactMarkdown>
                                        </span>
                                        {isCorrect && <CheckCircle2 size={11} color={lc.accent} style={{ flexShrink: 0, marginTop: 2 }} />}
                                    </div>
                                );
                            })}
                        </div>
                        <div style={{ borderTop: '1px solid var(--border)' }}>
                            {!isRev ? (
                                <button onClick={() => setRevealed(p => new Set([...p, i]))} style={{ width: '100%', padding: '8px 12px', background: 'var(--bg)', border: 'none', cursor: 'pointer', fontSize: 11, fontWeight: 600, color: 'var(--ag-purple)', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5 }}>
                                    <CheckCircle2 size={12} /> Show Answer
                                </button>
                            ) : (
                                <>
                                    <div style={{ padding: '10px 12px', background: lc.bg }}>
                                        <div style={{ fontSize: 11, fontWeight: 700, color: lc.accent, marginBottom: 3, display: 'flex', alignItems: 'center', gap: 4 }}>
                                            <CheckCircle2 size={11} /> Answer: {q.correct}
                                        </div>
                                        <div style={{ fontSize: 11, lineHeight: 1.65, color: lc.text }}>
                                            <span style={{ fontWeight: 600 }}>Explanation: </span>{q.explanation || ''}
                                        </div>
                                    </div>
                                    {!wasAssessed ? (
                                        <div style={{ display: 'flex', borderTop: '1px solid var(--border)' }}>
                                            <button onClick={() => markAssessment(i, true)} style={{ flex: 1, padding: '6px 0', background: isDark ? '#052E16' : '#DCFCE7', border: 'none', borderRight: isDark ? '1px solid #166534' : '1px solid #BBF7D0', cursor: 'pointer', fontSize: 10, fontWeight: 700, color: isDark ? '#86EFAC' : '#065F46', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                                                <CheckCircle2 size={10} /> Got it
                                            </button>
                                            <button onClick={() => markAssessment(i, false)} style={{ flex: 1, padding: '6px 0', background: isDark ? '#3F1D1D' : '#FEF2F2', border: 'none', cursor: 'pointer', fontSize: 10, fontWeight: 700, color: isDark ? '#FCA5A5' : '#991B1B', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                                                <X size={10} /> Missed it
                                            </button>
                                        </div>
                                    ) : (
                                        <div style={{ padding: '4px 12px', fontSize: 10, fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4, color: assessments[i] ? '#059669' : '#DC2626' }}>
                                            {assessments[i] ? <><CheckCircle2 size={10} /> Marked correct</> : <><X size={10} /> Marked incorrect</>}
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

// ─── Concept Detail Panel ─────────────────────────────────────────────────────
export function ConceptDetailPanel({ node, notebookId, onClose, onStatusChange, onJumpToSection, onFullPractice, darkMode = null }) {
    const isDark = darkMode ?? (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark');
    const [activeLevel, setActiveLevel] = useState(null);
    const [questions, setQuestions] = useState(null);
    const [loadingQ, setLoadingQ] = useState(false);
    const [promotion, setPromotion] = useState(null);
    const [customInstruction, setCustomInstruction] = useState('');

    const LEVELS = [
        { key: 'struggling', label: 'Beginner',     color: 'var(--ag-red)',     icon: <AlertCircle size={11} />,  desc: 'Definitions & recall' },
        { key: 'partial',    label: 'Intermediate', color: 'var(--ag-gold)',    icon: <MinusCircle size={11} />,  desc: 'Exam-style problems' },
        { key: 'mastered',   label: 'Expert',       color: 'var(--ag-emerald)', icon: <CheckCircle2 size={11} />, desc: 'Derivations & edge cases' },
    ];
    const statusColors = { mastered: 'var(--ag-emerald)', partial: 'var(--ag-gold)', struggling: 'var(--ag-red)' };

    const fetchLevel = async (lk) => {
        if (activeLevel === lk && !customInstruction) { setActiveLevel(null); setQuestions(null); setPromotion(null); return; }
        setActiveLevel(lk); setLoadingQ(true); setQuestions(null); setPromotion(null);
        try {
            const res = await fetch(`${API}/api/concept-practice`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
                body: JSON.stringify({
                    concept_name: node.full_label || node.label,
                    level: lk,
                    ...(notebookId ? { notebook_id: notebookId } : {}),
                    ...(customInstruction.trim() ? { custom_instruction: customInstruction.trim() } : {}),
                }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            setQuestions(data.questions || []);
        } catch (e) {
            console.error('concept-practice error:', e);
            setQuestions([]);
        }
        setLoadingQ(false);
    };

    const handleAllAssessed = (correct, total) => {
        if (correct < Math.ceil(total * 0.67)) return;
        const NEXT = { struggling: 'partial', partial: 'mastered', mastered: null };
        const promoted = NEXT[node.status];
        if (promoted) { onStatusChange(node, promoted); setPromotion(promoted); }
        else setPromotion('top');
    };

    return (
        <div style={{ background: 'var(--bg)', borderRadius: 12, border: '1px solid var(--border)', boxShadow: 'var(--shadow-md)', margin: '0 10px 10px', overflow: 'hidden' }}>
            <div style={{ padding: '11px 14px 9px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', background: isDark ? 'var(--surface)' : 'var(--ag-purple-bg)' }}>
                <div>
                    <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--ag-purple)' }}>{node.full_label || node.label}</div>
                    <div style={{ fontSize: 10, color: statusColors[node.status] || '#9CA3AF', fontWeight: 600, marginTop: 2, textTransform: 'capitalize' }}>&#9679; {node.status} — tap a difficulty to practise</div>
                </div>
                <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', padding: '2px 0 0' }}><X size={14} /></button>
            </div>
            <div style={{ padding: '10px 14px', overflowY: 'auto' }}>
                {/* Mastery buttons */}
                <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 5, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5 }}>Set mastery level</div>
                <div style={{ display: 'flex', gap: 5, marginBottom: 10 }}>
                    {LEVELS.map(l => (
                        <button key={l.key} onClick={() => onStatusChange(node, l.key)} style={{ flex: 1, padding: '5px 3px', borderRadius: 7, border: `1px solid ${node.status === l.key ? l.color : 'var(--border)'}`, background: node.status === l.key ? l.color + '18' : 'transparent', color: node.status === l.key ? l.color : 'var(--text3)', fontSize: 10, fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 3 }}>
                            {node.status === l.key && l.icon} {l.label}
                        </button>
                    ))}
                </div>
                <button onClick={() => onJumpToSection(node.full_label || node.label)} style={{ width: '100%', padding: '7px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text2)', fontSize: 11, fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5, marginBottom: 12 }}>
                    <ChevronRight size={12} /> Jump to this concept in Notes
                </button>
                {/* Practice difficulty buttons */}
                <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 6, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5 }}>🎯 Practice Questions</div>
                <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
                    {LEVELS.map(l => (
                        <button key={l.key} onClick={() => fetchLevel(l.key)} style={{ flex: 1, padding: '7px 4px', borderRadius: 8, border: `1px solid ${activeLevel === l.key ? l.color : 'var(--border)'}`, background: activeLevel === l.key ? l.color + '18' : 'var(--surface)', color: activeLevel === l.key ? l.color : 'var(--text3)', fontSize: 10, fontWeight: 600, cursor: 'pointer', textAlign: 'center', transition: 'all 0.15s' }}>
                            <div>{l.label}</div>
                            <div style={{ fontSize: 9, opacity: 0.7, marginTop: 1 }}>{l.desc}</div>
                        </button>
                    ))}
                </div>
                <div style={{ display: 'flex', gap: 5, marginBottom: 10 }}>
                    <input
                        value={customInstruction}
                        onChange={e => setCustomInstruction(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter' && activeLevel) fetchLevel(activeLevel); }}
                        placeholder="Custom focus, e.g. numerical only, derivations…"
                        style={{ flex: 1, fontSize: 11, padding: '5px 9px', borderRadius: 7, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text)', outline: 'none', fontFamily: 'inherit' }}
                    />
                    {activeLevel && (
                        <button onClick={() => fetchLevel(activeLevel)} disabled={loadingQ} title="Regenerate with this focus"
                            style={{ padding: '5px 9px', borderRadius: 7, border: '1px solid var(--ag-purple-border)', background: 'var(--ag-purple-bg)', color: 'var(--ag-purple)', fontSize: 11, fontWeight: 700, cursor: 'pointer', flexShrink: 0 }}>
                            {loadingQ ? <Loader2 className="spin" size={11} /> : '↺'}
                        </button>
                    )}
                </div>
                {loadingQ && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '10px 0', fontSize: 12, color: 'var(--text3)' }}>
                        <Loader2 className="spin" size={13} /> Generating {activeLevel} questions…
                    </div>
                )}
                {questions && !loadingQ && (
                    questions.length === 0
                        ? <div style={{ fontSize: 12, color: 'var(--text3)', padding: '8px 0' }}>No questions returned — try again.</div>
                        : <QuestionCards questions={questions} level={activeLevel} onAllAssessed={handleAllAssessed} darkMode={isDark} />
                )}
                {!loadingQ && promotion && (
                    <div style={{ margin: '10px 0 4px', padding: '9px 12px', borderRadius: 8, background: promotion === 'top' ? (isDark ? '#052E16' : '#DCFCE7') : 'var(--ag-purple-soft)', border: `1px solid ${promotion === 'top' ? (isDark ? '#166534' : '#86EFAC') : 'var(--ag-ring-left)'}`, fontSize: 11, fontWeight: 600, color: promotion === 'top' ? (isDark ? '#86EFAC' : '#065F46') : 'var(--ag-purple-medium)', display: 'flex', alignItems: 'center', gap: 6 }}>
                        <CheckCircle2 size={12} /> {promotion === 'top' ? '🏆 Already at peak mastery — well done!' : `⬆️ Level upgraded to ${promotion}! Graph updated.`}
                    </div>
                )}
            </div>
        </div>
    );
}

// ─── Knowledge Panel ──────────────────────────────────────────────────────────
export default function KnowledgePanel({ nodes, edges, notebookId, onNodeStatusChange, onJumpToSection, onQuizCompleted, darkMode = null, currentPageContent = '' }) {
    const isDark = darkMode ?? (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark');
    const [selectedNode, setSelectedNode] = useState(null);
    const [examinerConcept, setExaminerConcept] = useState(null);
    const [sniperOpen, setSniperOpen] = useState(false);
    const [generalOpen, setGeneralOpen] = useState(false);

    // ── Resizable split: graphH is the graph section height ─────────────────
    const [graphH, setGraphH] = useState(220);
    const [graphOpen, setGraphOpen] = useState(true); // open by default now — user can collapse
    const dragRef = useRef({ dragging: false, startY: 0, startH: 0 });

    const onSplitterMouseDown = useCallback((e) => {
        e.preventDefault();
        dragRef.current = { dragging: true, startY: e.clientY, startH: graphH };
        document.body.style.userSelect = 'none';
        document.body.style.cursor = 'row-resize';
    }, [graphH]);

    useEffect(() => {
        const onMove = (e) => {
            if (!dragRef.current.dragging) return;
            const delta = e.clientY - dragRef.current.startY;
            const newH = Math.max(140, Math.min(480, dragRef.current.startH + delta));
            setGraphH(newH);
        };
        const onUp = () => {
            if (!dragRef.current.dragging) return;
            dragRef.current.dragging = false;
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
        };
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
        return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
    }, []);

    // ── Match current page headings to graph nodes ───────────────────────────
    // We extract ## headings from the markdown page, then find the best-matching
    // node. On page change, auto-select that node so the user sees the quiz panel.
    const pageTopicNode = useMemo(() => {
        if (!currentPageContent || !nodes.length) return null;
        const headings = [];
        const re = /^#{1,3}\s+(.+)$/gm;
        let m;
        while ((m = re.exec(currentPageContent)) !== null) {
            // Use full_label for matching where available
            headings.push(m[1].toLowerCase().replace(/[^a-z0-9 ]/g, ' ').trim());
        }
        if (!headings.length) return null;

        // Score each node against headings: prefer longest common substring
        let bestNode = null, bestScore = 0;
        for (const n of nodes) {
            const lbl = ((n.full_label || n.label) || '').toLowerCase().replace(/[^a-z0-9 ]/g, ' ').trim();
            const lblWords = lbl.split(' ').filter(Boolean);
            for (const h of headings) {
                // Word overlap score
                const overlap = lblWords.filter(w => w.length > 2 && h.includes(w)).length;
                const score = overlap / Math.max(lblWords.length, 1);
                if (score > bestScore) { bestScore = score; bestNode = n; }
            }
        }
        return bestScore >= 0.4 ? bestNode : null;
    }, [currentPageContent, nodes]);

    // Auto-select the best matching node when page changes
    useEffect(() => {
        if (pageTopicNode) {
            setSelectedNode(pageTopicNode);
        }
    }, [pageTopicNode?.id]);

    // All nodes on this page (for highlighting in graph)
    const pageTopicNodeIds = useMemo(() => {
        if (!pageTopicNode) return [];
        return [pageTopicNode.id];
    }, [pageTopicNode]);

    const handleNodeClick = n => setSelectedNode(p => p?.id === n.id ? null : n);
    const handleStatusChange = (node, status) => {
        onNodeStatusChange(node, status);
        setSelectedNode(p => p?.id === node.id ? { ...p, status } : p);
    };

    const mc = nodes.filter(n => n.status === 'mastered').length;
    const pc = nodes.filter(n => n.status === 'partial').length;
    const sc = nodes.filter(n => n.status === 'struggling').length;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>

            {/* ── Stats header ──────────────────────────────────────────── */}
            <div style={{ padding: '8px 14px 6px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                    <span style={{ fontWeight: 700, fontSize: 12, color: 'var(--text)' }}>Cognitive Knowledge Map</span>
                    {nodes.length > 0 && (
                        <span style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 500 }}>
                            Click a node to practise · drag ↕ to resize
                        </span>
                    )}
                </div>
                {nodes.length > 0 && (
                    <div style={{ display: 'flex', gap: 5 }}>
                        {[['mastered', 'var(--ag-emerald)', mc], ['partial', 'var(--ag-gold)', pc], ['struggling', 'var(--ag-red)', sc]].map(([k, c, count]) => (
                            <div key={k} style={{ flex: 1, textAlign: 'center', background: c + '15', borderRadius: 5, padding: '3px 4px', border: `1px solid ${c}33` }}>
                                <div style={{ fontSize: 15, fontWeight: 800, color: c }}>{count}</div>
                                <div style={{ fontSize: 8, color: c, textTransform: 'uppercase', fontWeight: 600 }}>{k}</div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* ── Graph collapse/expand toggle ──────────────────────────── */}
            <div
                onClick={() => { setGraphOpen(o => !o); }}
                style={{
                    padding: '5px 14px',
                    borderBottom: graphOpen ? 'none' : '1px solid var(--border)',
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    cursor: 'pointer', flexShrink: 0,
                    background: graphOpen ? 'var(--ag-purple-bg)' : 'var(--surface)',
                    transition: 'background 0.15s', userSelect: 'none',
                }}
                title={graphOpen ? 'Collapse graph' : 'Expand graph'}
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 12 }}>🕸️</span>
                    <span style={{ fontSize: 11, fontWeight: 700, color: graphOpen ? 'var(--ag-purple)' : 'var(--text2)' }}>Galaxy Graph</span>
                    {nodes.length > 0 && (
                        <span style={{ fontSize: 9, fontWeight: 700, color: 'var(--ag-purple)', background: 'var(--ag-purple-bg)', border: '1px solid var(--ag-purple-border)', borderRadius: 8, padding: '1px 6px' }}>
                            {nodes.length} concepts
                        </span>
                    )}
                    {pageTopicNode && graphOpen && (
                        <span style={{ fontSize: 9, fontWeight: 600, color: isDark ? '#93C5FD' : '#2563EB', background: isDark ? 'rgba(59,130,246,0.15)' : '#EFF6FF', border: isDark ? '1px solid #1e3a5f' : '1px solid #BFDBFE', borderRadius: 8, padding: '1px 6px' }}>
                            auto-selected: {(pageTopicNode.label || '').slice(0, 18)}{(pageTopicNode.label || '').length > 18 ? '…' : ''}
                        </span>
                    )}
                </div>
                <svg width={13} height={13} viewBox="0 0 14 14" fill="none"
                    style={{ transform: graphOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s', flexShrink: 0 }}>
                    <path d="M3 5l4 4 4-4" stroke={graphOpen ? 'var(--ag-purple)' : 'var(--text3)'} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
            </div>

            {/* ── Graph canvas (resizable) ───────────────────────────────── */}
            {graphOpen && (
                <>
                    <div style={{ height: graphH, flexShrink: 0, overflow: 'hidden', position: 'relative', borderBottom: '1px solid var(--border)' }}>
                        <KnowledgeGraph
                            nodes={nodes}
                            edges={edges}
                            onNodeClick={handleNodeClick}
                            selectedNodeId={selectedNode?.id}
                            highlightNodeIds={pageTopicNodeIds}
                        />
                    </div>
                    {/* Drag handle — resize between graph and concept list */}
                    <div
                        onMouseDown={onSplitterMouseDown}
                        title="Drag up/down to resize graph vs quiz area"
                        style={{
                            height: 12, flexShrink: 0, cursor: 'row-resize',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            background: 'var(--surface)', borderBottom: '1px solid var(--border)',
                            userSelect: 'none',
                        }}
                    >
                        <div style={{ width: 40, height: 3, borderRadius: 2, background: 'var(--border2)' }} />
                    </div>
                </>
            )}

            {/* ── Concept list + ConceptDetailPanel (scrollable) ────────── */}
            <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
                <div style={{ flex: 1 }}>
                    {/* ConceptDetailPanel — shown when a node is selected */}
                    {selectedNode && (
                        <ConceptDetailPanel
                            node={selectedNode}
                            notebookId={notebookId}
                            onClose={() => setSelectedNode(null)}
                            onStatusChange={handleStatusChange}
                            onJumpToSection={label => { onJumpToSection(label); setSelectedNode(null); }}
                            onFullPractice={label => { setExaminerConcept(label); setSelectedNode(null); }}
                            darkMode={isDark}
                        />
                    )}

                    {/* All-concepts list */}
                    {nodes.length > 0 && (
                        <div style={{ padding: '6px 12px 4px' }}>
                            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text3)', marginBottom: 5, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                                All Concepts
                                {pageTopicNode && <span style={{ marginLeft: 6, color: isDark ? '#93C5FD' : '#2563EB', fontWeight: 600 }}>· current page highlighted</span>}
                            </div>
                            {nodes.map(n => {
                                const c = SC[n.status] || SC.partial;
                                const isCurrentPage = n.id === pageTopicNode?.id;
                                const isSelected = selectedNode?.id === n.id;
                                return (
                                    <div key={n.id} onClick={() => handleNodeClick(n)} style={{
                                        display: 'flex', alignItems: 'center', gap: 8,
                                        padding: '6px 8px', borderRadius: 7, marginBottom: 3, cursor: 'pointer',
                                        background: isSelected ? 'var(--surface2)' : isCurrentPage ? (isDark ? 'rgba(59,130,246,0.1)' : '#EFF6FF') : 'transparent',
                                        border: isSelected ? '1px solid var(--ag-purple-border)' : isCurrentPage ? (isDark ? '1px solid #1e3a5f' : '1px solid #BFDBFE') : '1px solid transparent',
                                        transition: 'all 0.1s',
                                    }}>
                                        <div style={{ width: 8, height: 8, borderRadius: '50%', background: c.fill, flexShrink: 0, boxShadow: `0 0 4px ${c.fill}88` }} />
                                        <div style={{ flex: 1, fontSize: 11.5, fontWeight: isCurrentPage ? 700 : 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: isSelected ? 'var(--ag-purple)' : 'var(--text)' }}>
                                            {n.full_label || n.label}
                                        </div>
                                        {isCurrentPage && !isSelected && (
                                            <span style={{ fontSize: 8, fontWeight: 700, color: isDark ? '#93C5FD' : '#2563EB', flexShrink: 0, opacity: 0.8, whiteSpace: 'nowrap' }}>ON PAGE</span>
                                        )}
                                        <button onClick={e => { e.stopPropagation(); onJumpToSection(n.full_label || n.label); }}
                                            title="Jump to concept in notes"
                                            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', padding: '1px 2px', borderRadius: 4, display: 'flex', alignItems: 'center', flexShrink: 0, opacity: 0.5 }}
                                            onMouseEnter={e => e.currentTarget.style.opacity = '1'}
                                            onMouseLeave={e => e.currentTarget.style.opacity = '0.5'}>
                                            <ChevronRight size={12} />
                                        </button>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>

                {/* ── Footer: legend + exam buttons ─────────────────────── */}
                <div style={{ padding: '8px 14px', borderTop: '1px solid var(--border)', flexShrink: 0 }}>
                    <div style={{ display: 'flex', gap: 12, marginBottom: 8 }}>
                        {[['mastered', 'var(--ag-emerald)'], ['partial', 'var(--ag-gold)'], ['struggling', 'var(--ag-red)']].map(([k, c]) => (
                            <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 9, color: 'var(--text3)' }}>
                                <div style={{ width: 7, height: 7, borderRadius: '50%', background: c }} /> {k}
                            </div>
                        ))}
                    </div>
                    {sc > 0 && (
                        <button onClick={() => setSniperOpen(true)} style={{ width: '100%', padding: '7px 0', borderRadius: 8, border: 'none', background: 'linear-gradient(90deg,#EF4444,#F59E0B)', color: '#fff', fontSize: 11, fontWeight: 700, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5, marginBottom: 5 }}>
                            🎯 Sniper Test — {sc} weak concept{sc !== 1 ? 's' : ''}
                        </button>
                    )}
                    {nodes.length > 0 && (
                        <button onClick={() => setGeneralOpen(true)} style={{ width: '100%', padding: '7px 0', borderRadius: 8, border: 'none', background: 'linear-gradient(90deg,#2563EB,#7C3AED)', color: '#fff', fontSize: 11, fontWeight: 700, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5 }}>
                            📝 Full Test — {nodes.length} concept{nodes.length !== 1 ? 's' : ''}
                        </button>
                    )}
                </div>
            </div>

            {examinerConcept && <ExaminerModal concept={examinerConcept} notebookId={notebookId} onClose={() => setExaminerConcept(null)} />}
            {sniperOpen && <SniperExamModal nodes={nodes} notebookId={notebookId} onClose={() => setSniperOpen(false)} onQuizCompleted={onQuizCompleted} />}
            {generalOpen && <GeneralExamModal nodes={nodes} notebookId={notebookId} onClose={() => setGeneralOpen(false)} onQuizCompleted={onQuizCompleted} />}
        </div>
    );
}
