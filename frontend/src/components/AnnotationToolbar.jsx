import React, { useState, useRef, useEffect } from 'react';
import {
    Highlighter, Pin, PenLine, Eraser,
    Cloud, CloudOff, Trash2, Save, ChevronDown
} from 'lucide-react';

const HIGHLIGHT_COLORS = [
    { value: '#FDE68A', label: 'Yellow' },
    { value: '#BBF7D0', label: 'Green'  },
    { value: '#FBCFE8', label: 'Pink'   },
    { value: '#BAE6FD', label: 'Blue'   },
    { value: '#DDD6FE', label: 'Purple' },
];

const DRAW_COLORS = ['#7C3AED','#EF4444','#F59E0B','#10B981','#3B82F6','#EC4899','#111827'];

export default function AnnotationToolbar({
    activeTool, setActiveTool,
    highlightColor, setHighlightColor,
    drawingColor, setDrawingColor,
    autoSave, setAutoSave,
    onClearAll, onSaveNow,
    annotationCount = 0,
}) {
    const [open, setOpen] = useState(false);
    const [showHLColors, setShowHLColors] = useState(false);
    const [showDrawColors, setShowDrawColors] = useState(false);
    const ref = useRef(null);

    // Close on outside click
    useEffect(() => {
        const handler = (e) => {
            if (ref.current && !ref.current.contains(e.target)) {
                setOpen(false);
                setShowHLColors(false);
                setShowDrawColors(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    const selectTool = (tool) => {
        setActiveTool(prev => prev === tool ? null : tool);
        setOpen(false);
    };

    // Label shown on the button
    const toolLabel =
        activeTool === 'highlight' ? 'Highlight' :
        activeTool === 'sticky'    ? 'Sticky' :
        activeTool === 'drawing'   ? 'Draw' :
        activeTool === 'eraser'    ? 'Eraser' :
        'Annotate';

    const toolIcon =
        activeTool === 'highlight' ? <Highlighter size={12} /> :
        activeTool === 'sticky'    ? <Pin size={12} /> :
        activeTool === 'drawing'   ? <PenLine size={12} /> :
        activeTool === 'eraser'    ? <Eraser size={12} /> :
        <PenLine size={12} />;

    return (
        <div ref={ref} style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}>

            {/* Trigger button — compact, fits in 38px row */}
            <button
                onClick={() => setOpen(o => !o)}
                title="Annotation tools"
                style={{
                    display: 'inline-flex', alignItems: 'center', gap: 4,
                    padding: '3px 8px',
                    height: 26,
                    borderRadius: 6,
                    border: activeTool
                        ? '1px solid var(--ag-purple)'
                        : '1px solid var(--border)',
                    background: activeTool ? 'var(--ag-purple)' : 'var(--bg)',
                    color: activeTool ? '#fff' : 'var(--text2)',
                    cursor: 'pointer',
                    fontSize: 12,
                    fontWeight: 600,
                    transition: 'all 0.15s',
                    whiteSpace: 'nowrap',
                    flexShrink: 0,
                }}
                onMouseEnter={e => { if (!activeTool) e.currentTarget.style.background = 'var(--surface2)'; }}
                onMouseLeave={e => { if (!activeTool) e.currentTarget.style.background = 'var(--bg)'; }}
            >
                {toolIcon}
                <span>{toolLabel}</span>
                {annotationCount > 0 && !activeTool && (
                    <span style={{
                        fontSize: 9, fontWeight: 700,
                        background: 'var(--ag-purple-bg)',
                        color: 'var(--ag-purple)',
                        border: '1px solid var(--ag-purple-border)',
                        borderRadius: 8, padding: '0 4px',
                    }}>{annotationCount}</span>
                )}
                <ChevronDown size={10} style={{ opacity: 0.6 }} />
            </button>

            {/* Dropdown — opens downward below the toolbar button */}
            {open && (
                <div style={{
                    position: 'fixed',
                    top: -9999,
                    left: -9999,
                    zIndex: 99999,
                    background: 'var(--bg)',
                    border: '1px solid var(--border)',
                    borderRadius: 10,
                    boxShadow: '0 -4px 32px rgba(0,0,0,0.18)',
                    minWidth: 220,
                    overflow: 'hidden',
                }} ref={el => {
                    if (el && ref.current) {
                        const btn = ref.current.querySelector('button');
                        if (btn) {
                            const r = btn.getBoundingClientRect();
                            const w = el.offsetWidth || 220;
                            const viewportW = window.innerWidth || document.documentElement.clientWidth;
                            const left = Math.min(Math.max(8, r.left), Math.max(8, viewportW - w - 8));
                            el.style.top = (r.bottom + 6) + 'px';
                            el.style.left = left + 'px';
                        }
                    }
                }}>
                    {/* Tools section */}
                    <div style={{ padding: '6px 6px 4px', borderBottom: '1px solid var(--border)' }}>
                        <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.1em', padding: '2px 8px 6px' }}>Tools</div>

                        <ToolRow icon={<Highlighter size={13} />} label="Highlight" active={activeTool === 'highlight'}
                            onClick={() => selectTool('highlight')} accent="#FDE68A"
                            extra={
                                <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginLeft: 'auto' }}>
                                    <button onClick={e => { e.stopPropagation(); setShowHLColors(p => !p); setShowDrawColors(false); }}
                                        style={{ width: 16, height: 16, borderRadius: 3, background: highlightColor, border: '2px solid rgba(0,0,0,0.15)', cursor: 'pointer', flexShrink: 0 }} />
                                </div>
                            }
                        />
                        {showHLColors && (
                            <div style={{ display: 'flex', gap: 5, padding: '4px 10px 8px 32px' }}>
                                {HIGHLIGHT_COLORS.map(c => (
                                    <button key={c.value} onClick={() => { setHighlightColor(c.value); setShowHLColors(false); }}
                                        title={c.label}
                                        style={{ width: 20, height: 20, borderRadius: 4, background: c.value, border: highlightColor === c.value ? '2px solid var(--ag-purple)' : '2px solid rgba(0,0,0,0.1)', cursor: 'pointer' }}
                                    />
                                ))}
                            </div>
                        )}

                        <ToolRow icon={<Pin size={13} />} label="Sticky Note" active={activeTool === 'sticky'}
                            onClick={() => selectTool('sticky')} accent="#BAE6FD" />

                        <ToolRow icon={<PenLine size={13} />} label="Draw" active={activeTool === 'drawing'}
                            onClick={() => selectTool('drawing')} accent="#FBCFE8"
                            extra={
                                <button onClick={e => { e.stopPropagation(); setShowDrawColors(p => !p); setShowHLColors(false); }}
                                    style={{ width: 16, height: 16, borderRadius: 3, background: drawingColor, border: '2px solid rgba(0,0,0,0.15)', cursor: 'pointer', flexShrink: 0, marginLeft: 'auto' }} />
                            }
                        />
                        {showDrawColors && (
                            <div style={{ display: 'flex', gap: 5, padding: '4px 10px 8px 32px' }}>
                                {DRAW_COLORS.map(c => (
                                    <button key={c} onClick={() => { setDrawingColor?.(c); setShowDrawColors(false); }}
                                        title={c}
                                        style={{ width: 20, height: 20, borderRadius: 4, background: c, border: drawingColor === c ? '2px solid rgba(0,0,0,0.5)' : '2px solid rgba(0,0,0,0.1)', cursor: 'pointer' }}
                                    />
                                ))}
                            </div>
                        )}

                        <ToolRow icon={<Eraser size={13} />} label="Eraser" active={activeTool === 'eraser'}
                            onClick={() => selectTool('eraser')} accent="#E5E7EB" />
                    </div>

                    {/* Storage section */}
                    <div style={{ padding: '4px 6px 6px' }}>
                        <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.1em', padding: '4px 8px 6px' }}>Storage</div>

                        <button onClick={() => setAutoSave(p => !p)}
                            style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '6px 10px', borderRadius: 6, background: 'transparent', border: 'none', cursor: 'pointer', fontSize: 12, color: 'var(--text2)', textAlign: 'left' }}
                            onMouseEnter={e => e.currentTarget.style.background = 'var(--surface2)'}
                            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                        >
                            {autoSave ? <Cloud size={13} color="#10B981" /> : <CloudOff size={13} color="#9CA3AF" />}
                            <span style={{ flex: 1, fontWeight: 500 }}>Auto-save</span>
                            <span style={{ width: 30, height: 16, borderRadius: 8, background: autoSave ? '#10B981' : '#D1D5DB', display: 'inline-flex', alignItems: 'center', justifyContent: autoSave ? 'flex-end' : 'flex-start', padding: '2px', transition: 'background 0.2s', flexShrink: 0 }}>
                                <span style={{ width: 12, height: 12, borderRadius: '50%', background: '#fff', boxShadow: '0 1px 2px rgba(0,0,0,0.2)' }} />
                            </span>
                        </button>

                        {!autoSave && (
                            <button onClick={() => { onSaveNow?.(); setOpen(false); }}
                                style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '6px 10px', borderRadius: 6, background: 'transparent', border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 500, color: 'var(--text2)', textAlign: 'left' }}
                                onMouseEnter={e => e.currentTarget.style.background = 'var(--surface2)'}
                                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                            >
                                <Save size={13} /> <span>Save now</span>
                            </button>
                        )}

                        <button onClick={() => { if (window.confirm('Clear ALL annotations? This cannot be undone.')) { onClearAll?.(); setOpen(false); } }}
                            style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '6px 10px', borderRadius: 6, background: 'transparent', border: 'none', cursor: 'pointer', fontSize: 12, fontWeight: 500, color: '#EF4444', textAlign: 'left', marginTop: 2 }}
                            onMouseEnter={e => e.currentTarget.style.background = '#FEF2F2'}
                            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                        >
                            <Trash2 size={13} /> <span>Clear all</span>
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}

function ToolRow({ icon, label, active, onClick, accent, extra }) {
    return (
        <button onClick={onClick}
            style={{
                display: 'flex', alignItems: 'center', gap: 8,
                width: '100%', padding: '6px 10px', borderRadius: 6,
                background: active ? 'var(--ag-purple)' : 'transparent',
                border: active ? '1px solid var(--ag-purple)' : '1px solid transparent',
                cursor: 'pointer',
                fontSize: 12, fontWeight: active ? 600 : 400,
                color: active ? '#fff' : 'var(--text2)',
                textAlign: 'left', transition: 'all 0.1s',
            }}
            onMouseEnter={e => { if (!active) e.currentTarget.style.background = 'var(--surface2)'; }}
            onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent'; }}
        >
            <span style={{ width: 8, height: 8, borderRadius: 2, background: accent, flexShrink: 0, border: '1px solid rgba(0,0,0,0.1)' }} />
            {icon}
            <span style={{ flex: 1 }}>{label}</span>
            {extra}
            {active && <span style={{ fontSize: 9, fontWeight: 700, background: '#fff', color: 'var(--ag-purple)', borderRadius: 4, padding: '1px 5px', flexShrink: 0 }}>ON</span>}
        </button>
    );
}
