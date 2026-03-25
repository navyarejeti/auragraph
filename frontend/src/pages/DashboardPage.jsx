import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import { setUser } from '../store';
import { ls_getNotebooks, ls_createNotebook, ls_deleteNotebook } from '../localNotebooks';
import { useAura } from '../hooks/useAura';
import { useFullscreen } from '../hooks/useFullscreen';
import AuraPanel from '../components/AuraPanel';
import FeedbackWidget from '../components/FeedbackWidget';
import { API, apiFetch } from '../components/utils';
import {
    BookOpen, Plus, Trash2, ChevronRight, LogOut, Loader2, BookMarked,
    Calendar, Moon, Sun, Target, TrendingUp, Clock, Award, Star,
    ChevronDown, FolderOpen, Folder
} from 'lucide-react';

function getUserId(user) {
    return user?.id || 'demo-user';
}

// ─── Streak helpers ────────────────────────────────────────────────────────────
function getStreak() {
    try {
        const data = JSON.parse(localStorage.getItem('ag_streak') || '{}');
        const today = new Date().toDateString();
        const yesterday = new Date(Date.now() - 86400000).toDateString();
        if (data.lastDate === today) return data.count || 1;
        if (data.lastDate === yesterday) return data.count || 0;
        return 0;
    } catch { return 0; }
}
function touchStreak() {
    try {
        const today = new Date().toDateString();
        const yesterday = new Date(Date.now() - 86400000).toDateString();
        const data = JSON.parse(localStorage.getItem('ag_streak') || '{}');
        if (data.lastDate === today) return;
        const count = data.lastDate === yesterday ? (data.count || 0) + 1 : 1;
        localStorage.setItem('ag_streak', JSON.stringify({ lastDate: today, count }));
    } catch { }
}

// ─── Mastery summary across notebooks ─────────────────────────────────────────
function getMasteryStats(notebooks) {
    let mastered = 0, partial = 0, struggling = 0;
    for (const nb of notebooks) {
        for (const n of (nb.graph?.nodes || [])) {
            if (n.status === 'mastered') mastered++;
            else if (n.status === 'partial') partial++;
            else if (n.status === 'struggling') struggling++;
        }
    }
    return { mastered, partial, struggling, total: mastered + partial + struggling };
}

// ─── Mini donut chart ──────────────────────────────────────────────────────────
function MiniDonut({ mastered, partial, struggling, total }) {
    if (total === 0) return (
        <svg width={72} height={72} viewBox="0 0 72 72">
            <circle cx={36} cy={36} r={26} fill="none" stroke="var(--border)" strokeWidth={10} />
            <text x={36} y={40} textAnchor="middle" fontSize={13} fontWeight={700} fill="var(--text3)">–</text>
        </svg>
    );
    const R = 26, C = 2 * Math.PI * R;
    const segments = [
        { val: mastered, color: 'var(--ag-emerald)' },
        { val: partial, color: 'var(--ag-gold)' },
        { val: struggling, color: 'var(--ag-red)' },
    ];
    let offset = 0;
    const arcs = segments.map(s => {
        const len = (s.val / total) * C;
        const arc = { ...s, len, offset };
        offset += len;
        return arc;
    });
    const pct = Math.round((mastered / total) * 100);
    return (
        <svg width={72} height={72} viewBox="0 0 72 72" style={{ transform: 'rotate(-90deg)' }}>
            <circle cx={36} cy={36} r={R} fill="none" stroke="var(--border)" strokeWidth={10} />
            {arcs.map((a, i) => a.len > 0 && (
                <circle key={i} cx={36} cy={36} r={R} fill="none"
                    stroke={a.color} strokeWidth={10}
                    strokeDasharray={`${a.len} ${C - a.len}`}
                    strokeDashoffset={-a.offset}
                    strokeLinecap="butt"
                />
            ))}
            <text x={36} y={40} textAnchor="middle" fontSize={13} fontWeight={800}
                fill="var(--text)" style={{ transform: 'rotate(90deg)', transformOrigin: '36px 36px' }}>
                {pct}%
            </text>
        </svg>
    );
}

// ─── Create Notebook Modal ─────────────────────────────────────────────────────
function CreateNotebookModal({ onClose, onCreate }) {
    const [name, setName] = useState('');
    const [course, setCourse] = useState('');
    const [loading, setLoading] = useState(false);
    const [nameError, setNameError] = useState('');
    const [courseError, setCourseError] = useState('');

    const validateName = (v) => {
        if (!v.trim()) return 'Title is required.';
        if (v.trim().length < 2) return 'Title must be at least 2 characters.';
        if (v.length > 120) return 'Title must be 120 characters or less.';
        return '';
    };
    const validateCourse = (v) => {
        if (!v.trim()) return 'Course / subject is required.';
        if (v.length > 80) return 'Course code must be 80 characters or less.';
        return '';
    };

    const submit = async (e) => {
        e.preventDefault();
        const ne = validateName(name);
        const ce = validateCourse(course);
        setNameError(ne); setCourseError(ce);
        if (ne || ce) return;
        setLoading(true);
        await onCreate(name.trim(), course.trim());
        setLoading(false);
        onClose();
    };

    return (
        <div className="modal-backdrop" onClick={onClose}>
            <div className="modal fade-in-scale" onClick={e => e.stopPropagation()}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
                    <div style={{ width: 40, height: 40, borderRadius: 10, background: 'var(--purple)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <BookOpen size={18} color="#fff" />
                    </div>
                    <div>
                        <h3 style={{ marginBottom: 2 }}>New Notebook</h3>
                        <p style={{ fontSize: 12, color: 'var(--text3)' }}>Create a notebook for a course or subject</p>
                    </div>
                </div>
                <form onSubmit={submit}>
                    <div style={{ marginBottom: 14 }}>
                        <label>Notebook Title</label>
                        <input className={`input${nameError ? ' input-error' : ''}`} placeholder="e.g. Digital Signal Processing" value={name}
                            onChange={e => { setName(e.target.value); if (nameError) setNameError(validateName(e.target.value)); }}
                            maxLength={120} autoFocus />
                        {nameError && <p style={{ fontSize: 11, color: 'var(--ag-red)', marginTop: 4 }}>{nameError}</p>}
                    </div>
                    <div style={{ marginBottom: 24 }}>
                        <label>Course Code / Subject</label>
                        <input className={`input${courseError ? ' input-error' : ''}`} placeholder="e.g. EC301 — DSP" value={course}
                            onChange={e => { setCourse(e.target.value); if (courseError) setCourseError(validateCourse(e.target.value)); }}
                            maxLength={80} />
                        {courseError && <p style={{ fontSize: 11, color: 'var(--ag-red)', marginTop: 4 }}>{courseError}</p>}
                    </div>
                    <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                        <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
                        <button type="submit" className="btn btn-primary" disabled={loading}>
                            {loading ? <Loader2 className="spin" size={14} /> : <><Plus size={14} /> Create Notebook</>}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
}

// ─── Notebook Card ─────────────────────────────────────────────────────────────
function NotebookCard({ nb, onOpen, onDelete, darkMode = false }) {
    const [deleting, setDeleting] = useState(false);
    const dateStr = new Date(nb.created_at).toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' });
    const hasNote = nb.note?.length > 0;
    const nodes = nb.graph?.nodes || [];
    const mastered = nodes.filter(n => n.status === 'mastered').length;
    const total = nodes.length;
    const pct = total > 0 ? Math.round((mastered / total) * 100) : null;

    const profColor = darkMode
        ? {
            Foundations: { bg: 'rgba(16,185,129,0.16)', text: '#6EE7B7', border: 'rgba(16,185,129,0.35)' },
            Practitioner: { bg: 'rgba(124,58,237,0.2)', text: '#C4B5FD', border: 'rgba(124,58,237,0.45)' },
            Expert: { bg: 'rgba(37,99,235,0.2)', text: '#93C5FD', border: 'rgba(59,130,246,0.45)' },
        }[nb.proficiency] || { bg: 'rgba(148,163,184,0.15)', text: '#CBD5E1', border: 'rgba(148,163,184,0.35)' }
        : {
            Foundations: { bg: '#ECFDF5', text: '#059669', border: '#A7F3D0' },
            Practitioner: { bg: 'var(--ag-purple-bg)', text: 'var(--ag-purple)', border: 'var(--ag-purple-border)' },
            Expert: { bg: '#EFF6FF', text: '#2563EB', border: '#BFDBFE' },
        }[nb.proficiency] || { bg: 'var(--surface2)', text: 'var(--text3)', border: 'var(--border)' };

    return (
        <div className="card" style={{ padding: '20px', cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 14 }}
            onClick={() => onOpen(nb.id)}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{ width: 42, height: 42, borderRadius: 11, background: 'linear-gradient(135deg,#7C3AED22,#7C3AED44)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, border: '1px solid #7C3AED33' }}>
                        <BookMarked size={19} color="var(--ag-purple)" />
                    </div>
                    <div>
                        <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)', lineHeight: 1.3 }}>{nb.name}</div>
                        <div style={{ fontSize: 12, color: 'var(--text3)', marginTop: 2 }}>{nb.course}</div>
                    </div>
                </div>
                <button className="btn btn-ghost btn-sm" style={{ flexShrink: 0, padding: '4px', opacity: 0.5 }}
                    onClick={async e => { e.stopPropagation(); setDeleting(true); await onDelete(nb.id); setDeleting(false); }}>
                    {deleting ? <Loader2 className="spin" size={14} /> : <Trash2 size={14} color="var(--text3)" />}
                </button>
            </div>

            <div style={{ fontSize: 12, color: 'var(--text3)', background: 'var(--surface)', borderRadius: 8, padding: '8px 10px', minHeight: 36, lineHeight: 1.65, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', borderLeft: hasNote ? '3px solid var(--purple)' : '3px solid var(--border)' }}>
                {hasNote ? nb.note.replace(/[#*`\\]/g, '').replace(/\$[^$]*\$/g, '').replace(/\$\$[\s\S]*?\$\$/g, '[formula]').slice(0, 130) + '…' : 'No notes yet — open to upload slides & textbook'}
            </div>

            {/* Progress bar */}
            {pct !== null && (
                <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                        <span style={{ fontSize: 11, color: 'var(--text3)', fontWeight: 600 }}>Mastery</span>
                        <span style={{ fontSize: 11, fontWeight: 700, color: pct >= 70 ? 'var(--ag-emerald)' : pct >= 40 ? 'var(--ag-gold)' : 'var(--ag-red)' }}>{pct}%</span>
                    </div>
                    <div className="progress-bar-track">
                        <div className="progress-bar-fill" style={{ width: `${pct}%`, background: pct >= 70 ? 'linear-gradient(90deg,#10B981,#34D399)' : pct >= 40 ? 'linear-gradient(90deg,#F59E0B,#FCD34D)' : 'linear-gradient(90deg,#EF4444,#FCA5A5)' }} />
                    </div>
                </div>
            )}

            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--text3)' }}>
                        <Calendar size={11} /> {dateStr}
                    </div>
                    {nb.proficiency && (
                        <span style={{ fontSize: 10, fontWeight: 600, padding: '1px 7px', borderRadius: 10, background: profColor.bg, color: profColor.text, border: `1px solid ${profColor.border}` }}>
                            {nb.proficiency}
                        </span>
                    )}
                    {total > 0 && <span style={{ fontSize: 10, color: 'var(--text3)' }}>· {total} concepts</span>}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, fontWeight: 600, color: 'var(--purple)' }}>
                    Open <ChevronRight size={14} />
                </div>
            </div>
        </div>
    );
}

// ─── Stat Info Modal ───────────────────────────────────────────────────────────
function StatInfoModal({ title, color, icon, onClose, children }) {
    return (
        <div className="modal-backdrop" onClick={onClose}>
            <div className="modal fade-in-scale" onClick={e => e.stopPropagation()}
                style={{ maxWidth: 400, width: '94vw', padding: 0, overflow: 'hidden', borderRadius: 14 }}>
                <div style={{ background: color + '15', borderBottom: `1px solid ${color}30`, padding: '16px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
                    <div style={{ width: 36, height: 36, borderRadius: 9, background: color + '25', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                        {React.cloneElement(icon, { size: 18, color })}
                    </div>
                    <div style={{ flex: 1, fontWeight: 800, fontSize: 15, color: 'var(--text)' }}>{title}</div>
                    <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', padding: 4 }}>
                        <svg width={14} height={14} viewBox="0 0 14 14" fill="none"><path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth={2} strokeLinecap="round"/></svg>
                    </button>
                </div>
                <div style={{ padding: '18px 20px', background: 'var(--bg)' }}>
                    {children}
                </div>
            </div>
        </div>
    );
}

// ─── Stat card ─────────────────────────────────────────────────────────────────
function StatCard({ icon, label, value, color, sublabel, onClick }) {
    return (
        <div
            onClick={onClick}
            style={{
                background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 12,
                padding: '16px 18px', display: 'flex', alignItems: 'center', gap: 14,
                boxShadow: 'var(--shadow)', flex: 1,
                cursor: onClick ? 'pointer' : 'default',
                transition: 'all 0.15s',
                userSelect: 'none',
            }}
            onMouseEnter={e => { if (onClick) { e.currentTarget.style.transform = 'translateY(-1px)'; e.currentTarget.style.boxShadow = 'var(--shadow-md)'; e.currentTarget.style.borderColor = color + '60'; } }}
            onMouseLeave={e => { if (onClick) { e.currentTarget.style.transform = 'none'; e.currentTarget.style.boxShadow = 'var(--shadow)'; e.currentTarget.style.borderColor = 'var(--border)'; } }}
        >
            <div style={{ width: 40, height: 40, borderRadius: 10, background: color + '20', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                {React.cloneElement(icon, { size: 18, color })}
            </div>
            <div style={{ flex: 1 }}>
                <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--text)', lineHeight: 1 }}>{value}</div>
                <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 3, fontWeight: 500 }}>{label}</div>
                {sublabel && <div style={{ fontSize: 10, color, fontWeight: 600, marginTop: 2 }}>{sublabel}</div>}
            </div>
            {onClick && <svg width={12} height={12} viewBox="0 0 12 12" style={{ flexShrink: 0, opacity: 0.35 }}><path d="M5 2l4 4-4 4" stroke={color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" fill="none"/></svg>}
        </div>
    );
}

// ─── Dashboard Page ────────────────────────────────────────────────────────────
export default function DashboardPage() {
    const navigate = useNavigate();
    const dispatch = useDispatch();
    const user = useSelector(s => s.graph.user);
    const aura = useAura();
    const { isFullscreen, toggle: toggleFullscreen } = useFullscreen();

    const [notebooks, setNotebooks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showCreate, setShowCreate] = useState(false);
    const [showAuraPanel, setShowAuraPanel] = useState(false);
    const [showStatModal, setShowStatModal] = useState(null); // 'notebooks' | 'concepts' | 'streak'
    const [darkMode, setDarkMode] = useState(() => localStorage.getItem('ag_dark') === '1');
    const [streak] = useState(getStreak);
    const [collapsedCourses, setCollapsedCourses] = useState(() => {
        try { return new Set(JSON.parse(localStorage.getItem('ag_collapsed_courses') || '[]')); }
        catch { return new Set(); }
    });

    const byCourse = useMemo(() => {
        const map = {};
        for (const nb of notebooks) {
            const key = (nb.course?.trim()) || 'Uncategorized';
            (map[key] = map[key] || []).push(nb);
        }
        // For each notebook, effective recency = max(created_at, last localStorage open)
        const nbRecency = (nb) => {
            const created = new Date(nb.created_at || 0).getTime();
            const used = parseInt(localStorage.getItem(`ag_nb_used:${nb.id}`) || '0', 10);
            return Math.max(created, used);
        };
        return Object.entries(map).sort(([keyA, nbsA], [keyB, nbsB]) => {
            if (keyA === 'Uncategorized') return 1;
            if (keyB === 'Uncategorized') return -1;
            // Course recency = most recent notebook in that course
            const latestA = Math.max(...nbsA.map(nbRecency));
            const latestB = Math.max(...nbsB.map(nbRecency));
            return latestB - latestA;
        });
    }, [notebooks]);

    const toggleCourse = (key) => {
        setCollapsedCourses(prev => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key); else next.add(key);
            localStorage.setItem('ag_collapsed_courses', JSON.stringify([...next]));
            return next;
        });
    };

    const userId = getUserId(user);

    // Apply dark mode
    useEffect(() => {
        document.documentElement.setAttribute('data-theme', darkMode ? 'dark' : 'light');
        localStorage.setItem('ag_dark', darkMode ? '1' : '0');
    }, [darkMode]);

    useEffect(() => { touchStreak(); }, []);

    const loadNotebooks = async () => {
        try {
            const res = await apiFetch(`${API}/notebooks`);
            if (res.ok) {
                const data = await res.json();
                setNotebooks(data.notebooks || data || []);
                setLoading(false);
                return;
            }
        } catch { }
        setNotebooks(ls_getNotebooks(userId));
        setLoading(false);
    };

    useEffect(() => { loadNotebooks(); }, []);

    const handleCreate = async (name, course) => {
        let nb;
        try {
            const res = await apiFetch(`${API}/notebooks`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, course }) });
            if (res.ok) nb = await res.json();
        } catch { }
        if (!nb) {
            nb = ls_createNotebook(userId, name, course);
        } else {
            const existing = ls_getNotebooks(userId);
            if (!existing.find(e => e.id === nb.id)) {
                const stored = JSON.parse(localStorage.getItem('ag_notebooks') || '[]');
                stored.unshift({ ...nb, user_id: userId });
                localStorage.setItem('ag_notebooks', JSON.stringify(stored));
            }
        }
        setNotebooks(prev => [nb, ...prev]);
    };

    const handleDelete = async (id) => {
        try { await apiFetch(`${API}/notebooks/${id}`, { method: 'DELETE' }); } catch { }
        ls_deleteNotebook(id);
        setNotebooks(prev => prev.filter(nb => nb.id !== id));
    };

    const handleLogout = () => {
        localStorage.removeItem('ag_token');
        localStorage.removeItem('ag_user');
        dispatch(setUser(null));
        navigate('/');
    };

    const displayName = user?.name || (user?.email?.split('@')[0]) || 'Student';
    const masteryStats = getMasteryStats(notebooks);
    const notebooksWithNotes = notebooks.filter(nb => nb.note?.length > 0).length;
    const totalConcepts = masteryStats.total;

    const greetingHour = new Date().getHours();
    const greeting = greetingHour < 12 ? 'Good morning' : greetingHour < 17 ? 'Good afternoon' : 'Good evening';

    return (
        <div style={{ minHeight: '100vh', background: 'var(--surface)' }}>
            {/* Demo banner — only shown when truly offline (backend unreachable) */}
            {localStorage.getItem('ag_offline_mode') === '1' && (
                <div style={{ background: darkMode ? '#1a1200' : '#FEF3C7', borderBottom: '1px solid #FDE68A', padding: '8px 32px', display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: '#92400E' }}>
                    <span style={{ fontSize: 14 }}>⚠️</span>
                    <span><b>Offline demo mode:</b> Backend is unreachable. Notes are stored in your browser only.</span>
                </div>
            )}

            {/* Header */}
            <header style={{ background: 'var(--bg)', borderBottom: '1px solid var(--border)', padding: '0 32px', height: 60, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{ background: '#fff', borderRadius: 10, padding: '4px 12px', display: 'flex', alignItems: 'center' }}>
                        <img src="/logo.jpeg" alt="AuraGraph" style={{ height: 30, width: 'auto' }} />
                    </div>
                    {streak > 0 && (
                        <div className="streak-badge" style={{ marginLeft: 4 }}>
                            🔥 {streak} day streak
                        </div>
                    )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <button onClick={() => setDarkMode(d => !d)} className="btn btn-ghost btn-sm" title="Toggle dark mode" style={{ padding: '6px 8px' }}>
                        {darkMode ? <Sun size={16} /> : <Moon size={16} />}
                    </button>
                    <button onClick={toggleFullscreen} className="btn btn-ghost btn-sm" title={isFullscreen ? 'Exit fullscreen (F11)' : 'Fullscreen (F11)'} style={{ padding: '6px 8px' }}>
                        {isFullscreen
                            ? <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3"/></svg>
                            : <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3"/></svg>
                        }
                    </button>
                    <div style={{ width: 32, height: 32, borderRadius: '50%', background: 'linear-gradient(135deg,#7C3AED,#2563EB)', color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: 13 }}>
                        {displayName[0]?.toUpperCase()}
                    </div>
                    <span style={{ fontSize: 14, color: 'var(--text2)', fontWeight: 600 }}>{displayName}</span>
                    <button className="btn btn-ghost btn-sm" onClick={handleLogout} style={{ gap: 5 }}>
                        <LogOut size={14} /> Logout
                    </button>
                </div>
            </header>

            <main style={{ maxWidth: 1100, margin: '0 auto', padding: '36px 32px' }}>
                {/* Welcome row */}
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28, gap: 16 }}>
                    <div>
                        <div style={{ fontSize: 13, color: 'var(--text3)', fontWeight: 500, marginBottom: 4 }}>{greeting}, {displayName} 👋</div>
                        <h1 style={{ fontSize: 26, fontWeight: 800, letterSpacing: '-0.5px', marginBottom: 6 }}>My Notebooks</h1>
                        <p style={{ fontSize: 14, color: 'var(--text3)' }}>Upload slides & textbooks to create AI-fused study notes</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => setShowCreate(true)} style={{ gap: 6, flexShrink: 0, marginTop: 4 }}>
                        <Plus size={16} /> New Notebook
                    </button>
                </div>

                {/* Stats row */}
                {!loading && (notebooks.length > 0 || masteryStats.total > 0) && (
                    <div style={{ display: 'flex', gap: 12, marginBottom: 28, flexWrap: 'wrap' }}>
                        <StatCard icon={<BookOpen />} label="Notebooks" value={notebooks.length} color="var(--ag-purple)" sublabel={notebooksWithNotes > 0 ? `${notebooksWithNotes} with notes` : null} onClick={() => setShowStatModal('notebooks')} />
                        <StatCard icon={<Target />} label="Concepts tracked" value={totalConcepts || '—'} color="#2563EB" sublabel={totalConcepts > 0 ? `${masteryStats.mastered} mastered` : null} onClick={totalConcepts > 0 ? () => setShowStatModal('concepts') : null} />
                        <StatCard icon={<TrendingUp />} label="Study streak" value={streak > 0 ? `${streak}d` : '0d'} color="#FF6B35" sublabel={streak > 0 ? 'Keep it up! 🔥' : 'Start today!'} onClick={() => setShowStatModal('streak')} />
                        {/* Aura XP card */}
                        <div
                            onClick={() => setShowAuraPanel(true)}
                            style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 12, padding: '16px 18px', display: 'flex', alignItems: 'center', gap: 12, boxShadow: 'var(--shadow)', cursor: 'pointer', textAlign: 'left', transition: 'all 0.15s', flex: 1, minWidth: 150, userSelect: 'none' }}
                            onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-1px)'; e.currentTarget.style.boxShadow = 'var(--shadow-md)'; e.currentTarget.style.borderColor = aura.badge.color + '60'; }}
                            onMouseLeave={e => { e.currentTarget.style.transform = 'none'; e.currentTarget.style.boxShadow = 'var(--shadow)'; e.currentTarget.style.borderColor = 'var(--border)'; }}
                        >
                            <div style={{ width: 40, height: 40, borderRadius: 10, background: aura.badge.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, fontSize: 22 }}>
                                {aura.badge.emoji}
                            </div>
                            <div style={{ flex: 1 }}>
                                <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--text)', lineHeight: 1 }}>{aura.data.xp.toLocaleString()} XP</div>
                                <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 3, fontWeight: 500 }}>Aura Rank</div>
                                <div style={{ fontSize: 10, color: aura.badge.color, fontWeight: 700, marginTop: 2 }}>{aura.badge.name}{aura.nextBadge ? ` · ${aura.nextBadge.minXp - aura.data.xp} to ${aura.nextBadge.name}` : ' · Max rank!'}</div>
                            </div>
                            <svg width={12} height={12} viewBox="0 0 12 12" style={{ flexShrink: 0, opacity: 0.35 }}><path d="M5 2l4 4-4 4" stroke={aura.badge.color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" fill="none"/></svg>
                        </div>
                        {/* Overall Mastery card */}
                        {masteryStats.total > 0 && (
                            <div
                                onClick={() => setShowStatModal('concepts')}
                                style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 12, padding: '14px 18px', display: 'flex', alignItems: 'center', gap: 14, boxShadow: 'var(--shadow)', flex: 1, cursor: 'pointer', transition: 'all 0.15s', userSelect: 'none' }}
                                onMouseEnter={e => { e.currentTarget.style.transform = 'translateY(-1px)'; e.currentTarget.style.boxShadow = 'var(--shadow-md)'; e.currentTarget.style.borderColor = '#2563EB60'; }}
                                onMouseLeave={e => { e.currentTarget.style.transform = 'none'; e.currentTarget.style.boxShadow = 'var(--shadow)'; e.currentTarget.style.borderColor = 'var(--border)'; }}
                            >
                                <MiniDonut {...masteryStats} />
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', marginBottom: 6 }}>Overall Mastery</div>
                                    {[['mastered', 'var(--ag-emerald)'], ['partial', 'var(--ag-gold)'], ['struggling', 'var(--ag-red)']].map(([k, c]) => (
                                        <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                                            <div style={{ width: 8, height: 8, borderRadius: '50%', background: c, flexShrink: 0 }} />
                                            <span style={{ fontSize: 11, color: 'var(--text3)', textTransform: 'capitalize' }}>{k}</span>
                                            <span style={{ fontSize: 11, fontWeight: 700, color: c, marginLeft: 'auto' }}>{masteryStats[k]}</span>
                                        </div>
                                    ))}
                                </div>
                                <svg width={12} height={12} viewBox="0 0 12 12" style={{ flexShrink: 0, opacity: 0.35, alignSelf: 'center' }}><path d="M5 2l4 4-4 4" stroke="#2563EB" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" fill="none"/></svg>
                            </div>
                        )}
                    </div>
                )}

                {/* Notebook grid — grouped by course */}
                {loading ? (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(280px,1fr))', gap: 16 }}>
                        {[...Array(4)].map((_, i) => (
                            <div key={i} style={{ borderRadius: 14, border: '1px solid var(--border)', background: 'var(--card)', padding: 20, display: 'flex', flexDirection: 'column', gap: 12 }}>
                                <div style={{ height: 14, width: '60%', borderRadius: 6, background: 'var(--border)', animation: 'skeleton-pulse 1.4s ease-in-out infinite' }} />
                                <div style={{ height: 11, width: '40%', borderRadius: 6, background: 'var(--border)', animation: 'skeleton-pulse 1.4s ease-in-out 0.2s infinite' }} />
                                <div style={{ height: 6, borderRadius: 4, background: 'var(--border)', animation: 'skeleton-pulse 1.4s ease-in-out 0.3s infinite' }} />
                                <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                                    <div style={{ height: 11, width: 60, borderRadius: 6, background: 'var(--border)', animation: 'skeleton-pulse 1.4s ease-in-out 0.4s infinite' }} />
                                    <div style={{ height: 11, width: 80, borderRadius: 6, background: 'var(--border)', animation: 'skeleton-pulse 1.4s ease-in-out 0.5s infinite' }} />
                                </div>
                            </div>
                        ))}
                    </div>
                ) : notebooks.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '80px 0' }}>
                        <div style={{ width: 72, height: 72, borderRadius: 18, background: 'linear-gradient(135deg,#7C3AED22,#2563EB22)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 20px', border: '1px solid #7C3AED33' }}>
                            <BookOpen size={30} color="var(--ag-purple)" />
                        </div>
                        <h3 style={{ color: 'var(--text)', marginBottom: 10, fontSize: 18 }}>No notebooks yet</h3>
                        <p style={{ fontSize: 14, color: 'var(--text3)', marginBottom: 28, lineHeight: 1.75, maxWidth: 360, margin: '0 auto 28px' }}>
                            Create your first notebook for a course.<br />Upload slides + textbook → get AI-powered, personalised notes.
                        </p>
                        <button className="btn btn-primary btn-lg" onClick={() => setShowCreate(true)} style={{ gap: 6 }}>
                            <Plus size={16} /> Create First Notebook
                        </button>
                    </div>
                ) : (
                    <>
                        {/* ── My Courses section heading ──────────────────── */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
                            <div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                    <span style={{ fontSize: 16, fontWeight: 800, color: 'var(--text)', letterSpacing: '-0.2px' }}>My Courses</span>
                                    <span style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 20, background: 'var(--ag-purple-bg)', color: 'var(--ag-purple)', border: '1px solid var(--ag-purple-border)' }}>
                                        {byCourse.length} course{byCourse.length !== 1 ? 's' : ''} · {notebooks.length} notebook{notebooks.length !== 1 ? 's' : ''}
                                    </span>
                                </div>
                                <p style={{ fontSize: 12, color: 'var(--text3)', marginTop: 3 }}>
                                    Sorted by most recently active · click a course to collapse it · click a notebook to open it
                                </p>
                            </div>
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
                            {byCourse.map(([courseKey, nbs]) => {
                                const collapsed = collapsedCourses.has(courseKey);
                                // Most recent activity for this course (create or open)
                                const latestTs = Math.max(...nbs.map(n => {
                                    const created = new Date(n.created_at || 0).getTime();
                                    const used = parseInt(localStorage.getItem(`ag_nb_used:${n.id}`) || '0', 10);
                                    return Math.max(created, used);
                                }));
                                const latestDate = new Date(latestTs);
                                const relativeDate = (() => {
                                    const diffDays = Math.floor((Date.now() - latestDate.getTime()) / 86400000);
                                    if (diffDays === 0) return 'active today';
                                    if (diffDays === 1) return 'active yesterday';
                                    if (diffDays < 7) return `active ${diffDays}d ago`;
                                    return `active ${latestDate.toLocaleDateString('en-IN', { month: 'short', day: 'numeric' })}`;
                                })();
                                return (
                                    <div key={courseKey}>
                                        {/* Course header */}
                                        <button
                                            onClick={() => toggleCourse(courseKey)}
                                            style={{
                                                display: 'flex', alignItems: 'center', gap: 10, marginBottom: collapsed ? 0 : 14,
                                                background: collapsed ? 'var(--surface)' : 'var(--bg)',
                                                border: '1px solid var(--border)',
                                                borderRadius: collapsed ? 10 : '10px 10px 0 0',
                                                borderBottom: collapsed ? '1px solid var(--border)' : '1px solid var(--border)',
                                                cursor: 'pointer', padding: '10px 14px', width: '100%',
                                                transition: 'all 0.15s',
                                            }}
                                        >
                                            <div style={{ width: 30, height: 30, borderRadius: 8, background: 'linear-gradient(135deg,#7C3AED22,#2563EB22)', display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid #7C3AED22', flexShrink: 0 }}>
                                                {collapsed
                                                    ? <Folder size={14} color="var(--ag-purple)" />
                                                    : <FolderOpen size={14} color="var(--ag-purple)" />}
                                            </div>
                                            <div style={{ flex: 1, textAlign: 'left', minWidth: 0 }}>
                                                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                    {courseKey === 'Uncategorized' ? '📂 Uncategorized' : courseKey}
                                                </div>
                                                <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 1 }}>
                                                    {nbs.length} notebook{nbs.length !== 1 ? 's' : ''} · {relativeDate}
                                                </div>
                                            </div>
                                            <ChevronDown size={14} color="var(--text3)"
                                                style={{ transform: collapsed ? 'rotate(-90deg)' : 'none', transition: 'transform 0.2s', flexShrink: 0 }} />
                                        </button>

                                        {/* Notebooks grid for this course */}
                                        {!collapsed && (
                                            <div style={{
                                                display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16,
                                                padding: '16px',
                                                border: '1px solid var(--border)', borderTop: 'none',
                                                borderRadius: '0 0 10px 10px',
                                                background: 'var(--surface)',
                                            }}>
                                                {nbs.map(nb => (
                                                    <NotebookCard key={nb.id} nb={nb}
                                                        darkMode={darkMode}
                                                        onOpen={id => { localStorage.setItem(`ag_nb_used:${id}`, String(Date.now())); navigate(`/notebook/${id}`); }}
                                                        onDelete={handleDelete} />
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    </>
                )}
            </main>

            {showCreate && <CreateNotebookModal onClose={() => setShowCreate(false)} onCreate={handleCreate} />}

            {/* Notebooks modal */}
            {showStatModal === 'notebooks' && (
                <StatInfoModal title="Your Notebooks" color="var(--ag-purple)" icon={<BookOpen />} onClose={() => setShowStatModal(null)}>
                    <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 14 }}>
                        You have <strong style={{ color: 'var(--ag-purple)' }}>{notebooks.length}</strong> notebook{notebooks.length !== 1 ? 's' : ''}.
                        {notebooksWithNotes > 0 && <> <strong style={{ color: 'var(--ag-purple)' }}>{notebooksWithNotes}</strong> of them have generated notes.</>}
                    </div>
                    {notebooks.slice(0, 6).map(nb => (
                        <div key={nb.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border)', marginBottom: 6, cursor: 'pointer', background: 'var(--surface)' }}
                            onClick={() => { setShowStatModal(null); localStorage.setItem(`ag_nb_used:${nb.id}`, String(Date.now())); navigate(`/notebook/${nb.id}`); }}>
                            <div style={{ width: 8, height: 8, borderRadius: '50%', background: nb.note?.length > 0 ? 'var(--ag-purple)' : 'var(--border2)', flexShrink: 0 }} />
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{nb.name}</div>
                                <div style={{ fontSize: 10, color: 'var(--text3)' }}>{nb.course || 'No course set'}</div>
                            </div>
                            <svg width={12} height={12} viewBox="0 0 12 12" fill="none"><path d="M4 2l4 4-4 4" stroke="var(--ag-purple)" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round"/></svg>
                        </div>
                    ))}
                    {notebooks.length > 6 && <div style={{ fontSize: 11, color: 'var(--text3)', textAlign: 'center', marginTop: 4 }}>+{notebooks.length - 6} more below</div>}
                </StatInfoModal>
            )}

            {/* Concepts modal */}
            {showStatModal === 'concepts' && (
                <StatInfoModal title="Concept Mastery" color="#2563EB" icon={<Target />} onClose={() => setShowStatModal(null)}>
                    <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
                        {[['mastered', 'var(--ag-emerald)', masteryStats.mastered], ['partial', 'var(--ag-gold)', masteryStats.partial], ['struggling', 'var(--ag-red)', masteryStats.struggling]].map(([k, c, v]) => (
                            <div key={k} style={{ flex: 1, textAlign: 'center', background: c + '15', borderRadius: 8, padding: '10px 4px', border: `1px solid ${c}30` }}>
                                <div style={{ fontSize: 22, fontWeight: 800, color: c }}>{v}</div>
                                <div style={{ fontSize: 9, color: c, textTransform: 'uppercase', fontWeight: 700, marginTop: 2 }}>{k}</div>
                            </div>
                        ))}
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.7 }}>
                        You're tracking <strong>{masteryStats.total}</strong> concepts across all notebooks.
                        {masteryStats.mastered > 0 && <> <strong style={{ color: 'var(--ag-emerald)' }}>{Math.round(masteryStats.mastered / masteryStats.total * 100)}%</strong> are mastered.</>}
                        {masteryStats.struggling > 0 && <> Open a notebook and use the <strong>Sniper Exam</strong> to target the <strong style={{ color: 'var(--ag-red)' }}>{masteryStats.struggling}</strong> struggling concept{masteryStats.struggling !== 1 ? 's' : ''}.</>}
                    </div>
                </StatInfoModal>
            )}

            {/* Streak modal */}
            {showStatModal === 'streak' && (
                <StatInfoModal title="Study Streak" color="#FF6B35" icon={<TrendingUp />} onClose={() => setShowStatModal(null)}>
                    <div style={{ textAlign: 'center', padding: '8px 0 16px' }}>
                        <div style={{ fontSize: 56, lineHeight: 1, marginBottom: 8 }}>{streak > 0 ? '🔥' : '💤'}</div>
                        <div style={{ fontSize: 32, fontWeight: 800, color: '#FF6B35' }}>{streak} day{streak !== 1 ? 's' : ''}</div>
                        <div style={{ fontSize: 13, color: 'var(--text3)', marginTop: 4 }}>{streak > 0 ? 'Current streak — keep it going!' : 'Open a notebook today to start your streak.'}</div>
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.7, background: 'var(--surface)', borderRadius: 8, padding: '10px 12px', border: '1px solid var(--border)' }}>
                        💡 <strong>Tip:</strong> A streak is counted when you open AuraGraph on consecutive days. Consistent daily review is proven to increase long-term retention by up to 80%.
                    </div>
                </StatInfoModal>
            )}

            {showAuraPanel && <AuraPanel aura={aura} onClose={() => setShowAuraPanel(false)} darkMode={darkMode} />}
            <FeedbackWidget mode="dashboard" darkMode={darkMode} />
        </div>
    );
}
