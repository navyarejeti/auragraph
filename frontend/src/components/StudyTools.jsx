import React from 'react';
import { createPortal } from 'react-dom';
import { Timer, X, RefreshCw, Search } from 'lucide-react';

// ─── Study Timer (Pomodoro) ───────────────────────────────────────────────────
export function StudyTimer() {
    const MODES = { focus: 25 * 60, short: 5 * 60, long: 15 * 60 };
    const [mode, setMode] = React.useState('focus');
    const [secs, setSecs] = React.useState(MODES.focus);
    const [running, setRunning] = React.useState(false);
    const [sessions, setSessions] = React.useState(() => parseInt(localStorage.getItem('ag_sessions') || '0'));
    const [open, setOpen] = React.useState(false);
    const timerRef = React.useRef();
    const endAtRef = React.useRef(null);
    const triggerRef = React.useRef(null);
    const dragRef = React.useRef({ dragging: false, dx: 0, dy: 0 });
    const [panelPos, setPanelPos] = React.useState({ x: 0, y: 0 });

    const completeTimer = React.useCallback(() => {
        clearInterval(timerRef.current);
        endAtRef.current = null;
        setRunning(false);
        setSecs(MODES[mode]);
        if (mode === 'focus') {
            setSessions(prev => {
                const n = prev + 1;
                localStorage.setItem('ag_sessions', String(n));
                return n;
            });
        }
        try { new Audio('data:audio/wav;base64,//uQRAAAAWMSLwUIYAAsYkXgoQwAEaYLWfkWgAI0wWs/ItAAAGDgYtAgAyN+QWaAAihwMWm4G8QQRDiMcCBcH3Cc+CDv/7xA4Tvh9Rz/y8QADBwMWgQAZG/ILNAARQ4GLTcDeIIIhxGOBAuD7hOfBB3/94gcJ3w+o5/5eIAIAAAVwWgQAVQ2ORaIQwEMAJiDg95G4nQL7mQVWI6GwRcfsZAcsKkJvxgxEjzFUgfHoSQ9Qq7KNwqHwuB13MA4a1q/DmBrHgPcmjiGoh//EwC5nGPEmS4RcfkVKOhJf+WOgoxJclFz3kgn//dBA+ya1GhurNn8zb//9NNutNuhz31f////9vt///z+IdAEAAAK4LQIAKobHItEIYCGAExBwe8jcToF9zIKrEdDYIuP2MgOWFSE34wYiR5iqQPj0JIeoVdlG4VD4XA67mAcNa1fhzA1jwHuTRxDUQ//iYBczjHiTJcIuPyKlHQkv/LHQUYkuSi57yQT//uggfZNajQ3Vmz+Zt//+mm3Wm3Q576v////+32///5/EOgAAADVghQAAAAA==').play(); } catch { }
    }, [mode]);

    React.useEffect(() => {
        const syncFromClock = () => {
            if (!endAtRef.current) return;
            const remaining = Math.max(0, Math.ceil((endAtRef.current - Date.now()) / 1000));
            setSecs(remaining);
            if (remaining <= 0) completeTimer();
        };

        if (running) {
            syncFromClock();
            timerRef.current = setInterval(syncFromClock, 250);
        }

        const onVisibility = () => {
            if (running) syncFromClock();
        };
        document.addEventListener('visibilitychange', onVisibility);

        return () => {
            clearInterval(timerRef.current);
            document.removeEventListener('visibilitychange', onVisibility);
        };
    }, [running, completeTimer]);

    React.useEffect(() => {
        if (!open || !triggerRef.current) return;
        const r = triggerRef.current.getBoundingClientRect();
        const width = 220;
        const maxX = Math.max(8, window.innerWidth - width - 8);
        const x = Math.min(maxX, Math.max(8, r.right - width));
        const y = Math.max(8, r.bottom + 8);
        setPanelPos({ x, y });
    }, [open]);

    React.useEffect(() => {
        const onMove = (e) => {
            if (!dragRef.current.dragging) return;
            const width = 220;
            const height = 236;
            const maxX = Math.max(8, window.innerWidth - width - 8);
            const maxY = Math.max(8, window.innerHeight - height - 8);
            const nextX = Math.min(maxX, Math.max(8, e.clientX - dragRef.current.dx));
            const nextY = Math.min(maxY, Math.max(8, e.clientY - dragRef.current.dy));
            setPanelPos({ x: nextX, y: nextY });
        };
        const onUp = () => {
            dragRef.current.dragging = false;
            document.body.style.userSelect = '';
        };
        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onUp);
        return () => {
            window.removeEventListener('mousemove', onMove);
            window.removeEventListener('mouseup', onUp);
        };
    }, [open]);

    const startDrag = (e) => {
        const target = e.target;
        if (!(target instanceof HTMLElement) || !target.closest('[data-drag-handle="timer"]')) return;
        dragRef.current.dragging = true;
        dragRef.current.dx = e.clientX - panelPos.x;
        dragRef.current.dy = e.clientY - panelPos.y;
        document.body.style.userSelect = 'none';
    };

    const switchMode = (m) => {
        clearInterval(timerRef.current);
        endAtRef.current = null;
        setRunning(false);
        setMode(m);
        setSecs(MODES[m]);
    };
    const toggleRunning = () => {
        if (running) {
            clearInterval(timerRef.current);
            endAtRef.current = null;
            setRunning(false);
            return;
        }
        endAtRef.current = Date.now() + (secs * 1000);
        setRunning(true);
    };
    const mm = String(Math.floor(secs / 60)).padStart(2, '0');
    const ss = String(secs % 60).padStart(2, '0');
    const total = MODES[mode];
    const pct = secs / total;
    const R = 18, C = 2 * Math.PI * R;
    const isAlmostDone = secs < 60 && mode === 'focus';
    const isDark = typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark';

    return (
        <div ref={triggerRef} style={{ position: 'relative', flexShrink: 0 }}>
            {!open && (
                <button onClick={() => setOpen(true)} title="Pomodoro timer"
                    style={{ padding: '0 8px', height: 26, borderRadius: 6, border: '1px solid transparent', background: 'transparent', color: running ? 'var(--ag-purple)' : 'var(--text2)', cursor: 'pointer', display: 'flex', alignItems: 'center', position: 'relative' }}>
                    <Timer size={13} />
                    {sessions > 0 && <span style={{ position: 'absolute', top: -2, right: -2, background: 'var(--ag-purple)', color: '#fff', fontSize: 8, fontWeight: 700, width: 14, height: 14, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{sessions}</span>}
                </button>
            )}

            {open && typeof document !== 'undefined' && createPortal(
                <div
                    onMouseDown={startDrag}
                    style={{ position: 'fixed', left: panelPos.x, top: panelPos.y, zIndex: 99999, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 12, padding: '12px 14px', boxShadow: 'var(--shadow-md)', width: 220, animation: 'slideUpFade 0.15s ease' }}
                >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, gap: 8 }}>
                        <span data-drag-handle="timer" style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)', cursor: 'grab' }}>⏱ Focus Timer</span>
                        <button onClick={() => setOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)' }}><X size={13} /></button>
                    </div>
                    <div style={{ display: 'flex', gap: 3, marginBottom: 12, background: 'var(--surface)', borderRadius: 7, padding: 2 }}>
                        {[['focus', '25m'], ['short', '5m'], ['long', '15m']].map(([m, l]) => (
                            <button key={m} onClick={() => switchMode(m)} style={{ flex: 1, padding: '4px 0', borderRadius: 5, border: 'none', cursor: 'pointer', background: mode === m ? 'var(--ag-purple)' : 'transparent', color: mode === m ? '#fff' : 'var(--text3)', fontSize: 10, fontWeight: 600, transition: 'all 0.15s' }}>{l}</button>
                        ))}
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 12 }}>
                        <svg width={80} height={80} viewBox="0 0 50 50">
                            <circle cx={25} cy={25} r={R} fill="none" stroke="var(--border)" strokeWidth={4} />
                            <circle cx={25} cy={25} r={R} fill="none"
                                stroke={isAlmostDone ? 'var(--ag-red)' : mode === 'focus' ? 'var(--ag-purple)' : 'var(--ag-emerald)'}
                                strokeWidth={4}
                                strokeDasharray={`${pct * C} ${C}`}
                                strokeDashoffset={C * 0.25}
                                strokeLinecap="round"
                                style={{ transition: 'stroke-dasharray 0.5s ease, stroke 0.5s ease', transform: 'rotate(-90deg)', transformOrigin: '25px 25px' }}
                            />
                            <text x={25} y={28} textAnchor="middle" fontSize={9} fontWeight={700} fill={isAlmostDone ? 'var(--ag-red)' : (isDark ? '#F8FAFC' : '#111827')} fontFamily="Space Grotesk, monospace">{mm}:{ss}</text>
                        </svg>
                    </div>
                    <div style={{ display: 'flex', gap: 6 }}>
                        <button className="btn btn-primary btn-sm" style={{ flex: 1, fontSize: 11 }} onClick={toggleRunning}>
                            {running ? '⏸ Pause' : '▶ Start'}
                        </button>
                        <button className="btn btn-ghost btn-sm" style={{ padding: '6px 8px' }} onClick={() => { clearInterval(timerRef.current); endAtRef.current = null; setSecs(MODES[mode]); setRunning(false); }} title="Reset">
                            <RefreshCw size={12} />
                        </button>
                    </div>
                    {sessions > 0 && <div style={{ marginTop: 8, fontSize: 10, color: 'var(--text3)', textAlign: 'center' }}>🍅 {sessions} session{sessions > 1 ? 's' : ''} today</div>}
                </div>,
                document.body
            )}
        </div>
    );
}

// ─── NoteSearch ───────────────────────────────────────────────────────────────
export function NoteSearch({ pages, onJumpToPage, onClose }) {
    const [query, setQuery] = React.useState('');
    const inputRef = React.useRef();
    React.useEffect(() => { inputRef.current?.focus(); }, []);

    const results = React.useMemo(() => {
        if (!query.trim() || query.length < 2) return [];
        const q = query.toLowerCase();
        return pages.map((page, idx) => {
            const lower = page.toLowerCase();
            const pos = lower.indexOf(q);
            if (pos === -1) return null;
            const start = Math.max(0, pos - 40);
            const end = Math.min(page.length, pos + query.length + 60);
            const preview = (start > 0 ? '…' : '') + page.slice(start, end) + (end < page.length ? '…' : '');
            return { idx, preview, pos: pos - start + (start > 0 ? 1 : 0) };
        }).filter(Boolean);
    }, [query, pages]);

    const highlight = (text, q) => {
        const idx = text.toLowerCase().indexOf(q.toLowerCase());
        if (idx === -1) return text;
        return <>{text.slice(0, idx)}<mark style={{ background: 'rgba(250,204,21,0.5)', borderRadius: 2, padding: '0 1px' }}>{text.slice(idx, idx + q.length)}</mark>{text.slice(idx + q.length)}</>;
    };

    return (
        <div className="modal-backdrop" onClick={onClose}>
            <div className="modal fade-in-scale" onClick={e => e.stopPropagation()} style={{ maxWidth: 500, padding: '16px 16px 10px' }}>
                <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                    <input ref={inputRef} className="input" placeholder="Search in notes… (e.g. Fourier, gradient)" value={query} onChange={e => setQuery(e.target.value)} onKeyDown={e => e.key === 'Escape' && onClose()} style={{ flex: 1 }} />
                    <button className="btn btn-ghost btn-sm" onClick={onClose}><X size={14} /></button>
                </div>
                <div style={{ maxHeight: 320, overflowY: 'auto' }}>
                    {query.length >= 2 && results.length === 0 && (
                        <div style={{ padding: '16px 0', textAlign: 'center', color: 'var(--text3)', fontSize: 13 }}>No results for "{query}"</div>
                    )}
                    {results.map(r => (
                        <button key={r.idx} onClick={() => { onJumpToPage(r.idx, query); onClose(); }}
                            style={{ display: 'block', width: '100%', textAlign: 'left', padding: '10px 12px', borderRadius: 8, border: '1px solid transparent', background: 'var(--surface)', marginBottom: 6, cursor: 'pointer', transition: 'all 0.12s' }}
                            onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--purple)'; e.currentTarget.style.background = 'var(--purple-light)'; }}
                            onMouseLeave={e => { e.currentTarget.style.borderColor = 'transparent'; e.currentTarget.style.background = 'var(--surface)'; }}>
                            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--purple)', marginBottom: 3 }}>Page {r.idx + 1}</div>
                            <div style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.6 }}>{highlight(r.preview.replace(/[#*`]/g, ''), query)}</div>
                        </button>
                    ))}
                </div>
                {query.length < 2 && <div style={{ padding: '8px 0', textAlign: 'center', fontSize: 11, color: 'var(--text3)' }}>Type at least 2 characters to search</div>}
            </div>
        </div>
    );
}

// ─── Keyboard Shortcuts Modal ─────────────────────────────────────────────────
export function ShortcutsModal({ onClose }) {
    const shorts = [
        ['← / →', 'Previous / Next page'],
        ['Click page counter', 'Jump to any page number'],
        ['Ctrl+D', 'Ask a doubt / Rewrite page'],
        ['Ctrl+F', 'Search in notes'],
        ['Ctrl+Enter', 'Submit doubt in modal'],
        ['Esc', 'Close modal / selection'],
    ];
    return (
        <div className="modal-backdrop" onClick={onClose}>
            <div className="modal fade-in-scale" onClick={e => e.stopPropagation()} style={{ maxWidth: 360 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                    <h3>⌨️ Keyboard Shortcuts</h3>
                    <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)' }}><X size={16} /></button>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {shorts.map(([k, d]) => (
                        <div key={k} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '7px 10px', borderRadius: 8, background: 'var(--surface)', border: '1px solid var(--border)' }}>
                            <kbd>{k}</kbd>
                            <span style={{ fontSize: 12, color: 'var(--text2)' }}>{d}</span>
                        </div>
                    ))}
                </div>
                <div style={{ marginTop: 14, fontSize: 11, color: 'var(--text3)', textAlign: 'center' }}>Press <kbd>Esc</kbd> to close</div>
            </div>
        </div>
    );
}
