/**
 * AnnotationLayer v5
 * ──────────────────
 * Highlights applied via DOM after render — works on plain text AND KaTeX output.
 * Uses requestAnimationFrame to defer DOM mutation until after React finishes painting,
 * so it never conflicts with the user's text selection.
 *
 * The popup approach (user clicks "Highlight" button to confirm) means the selection
 * is already gone before the DOM mutation runs — zero interference.
 */
import React, { useEffect, useRef, useState, useCallback } from 'react';
import { X, GripHorizontal, Trash2 } from 'lucide-react';
import { findTextInContainer } from '../hooks/useAnnotations';

const HIGHLIGHT_COLORS = ['#FDE68A', '#BBF7D0', '#FBCFE8', '#BAE6FD', '#DDD6FE'];
const COLOR_TEXT = {
    '#FDE68A': '#78350F', '#BBF7D0': '#065F46',
    '#FBCFE8': '#831843', '#BAE6FD': '#0C4A6E', '#DDD6FE': '#4C1D95',
};
const textColorFor = (bg) => COLOR_TEXT[bg] || '#1C1917';
const uid = () => Math.random().toString(36).slice(2) + Date.now().toString(36);

// ── Highlight Popover ─────────────────────────────────────────────────────────
function HighlightPopover({ annId, color, x, y, onRecolor, onDelete, onClose }) {
    const ref = useRef(null);
    useEffect(() => {
        const onKey = (e) => { if (e.key === 'Escape') onClose(); };
        const onOutside = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
        const t = setTimeout(() => {
            document.addEventListener('mousedown', onOutside);
            document.addEventListener('keydown', onKey);
        }, 80);
        return () => { clearTimeout(t); document.removeEventListener('mousedown', onOutside); document.removeEventListener('keydown', onKey); };
    }, [onClose]);

    return (
        <div ref={ref} style={{ position: 'fixed', left: x, top: y - 8, transform: 'translateX(-50%) translateY(-100%)', zIndex: 99999, background: '#1E1B4B', borderRadius: 10, padding: '8px 10px', display: 'flex', alignItems: 'center', gap: 8, boxShadow: '0 6px 24px rgba(0,0,0,0.4)', pointerEvents: 'auto' }}>
            <span style={{ fontSize: 10, color: '#A5B4FC', fontWeight: 600, whiteSpace: 'nowrap' }}>Highlight</span>
            <div style={{ display: 'flex', gap: 4 }}>
                {HIGHLIGHT_COLORS.map(c => (
                    <button key={c} onClick={() => { onRecolor(annId, c); onClose(); }}
                        style={{ width: 16, height: 16, borderRadius: 4, background: c, padding: 0, cursor: 'pointer', border: color === c ? '2px solid #fff' : '2px solid rgba(255,255,255,0.2)', transition: 'transform 0.1s' }}
                        onMouseEnter={e => e.currentTarget.style.transform = 'scale(1.2)'}
                        onMouseLeave={e => e.currentTarget.style.transform = 'scale(1)'}
                    />
                ))}
            </div>
            <div style={{ width: 1, height: 16, background: 'rgba(255,255,255,0.15)' }} />
            <button onClick={() => { onDelete(annId); onClose(); }}
                style={{ background: 'rgba(239,68,68,0.15)', border: '1px solid rgba(239,68,68,0.4)', borderRadius: 6, padding: '3px 7px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, color: '#FCA5A5', fontSize: 11, fontWeight: 600 }}
                onMouseEnter={e => e.currentTarget.style.background = 'rgba(239,68,68,0.3)'}
                onMouseLeave={e => e.currentTarget.style.background = 'rgba(239,68,68,0.15)'}
            >
                <Trash2 size={11} /> Remove
            </button>
            <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6B7280', padding: 2, display: 'flex' }}><X size={11} /></button>
        </div>
    );
}

// ═══════════════════════════════════════════════════════════════════════════════
// ── getTextNodesInRange ───────────────────────────────────────────────────────
// Returns all text nodes within `range` with their local start/end offsets.
// This lets us highlight text across element boundaries (e.g. inside KaTeX spans,
// across <strong>/<em> tags) without ever touching element node structure.
function getTextNodesInRange(range, container) {
    const result = [];
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
    let node;
    while ((node = walker.nextNode())) {
        // Check if this text node overlaps the range
        const nodeRange = document.createRange();
        nodeRange.selectNodeContents(node);

        // No overlap if node ends before range starts or node starts after range ends
        if (nodeRange.compareBoundaryPoints(Range.END_TO_START, range) >= 0) continue;
        if (nodeRange.compareBoundaryPoints(Range.START_TO_END, range) <= 0) continue;

        // Calculate local start/end within this text node
        const start = node === range.startContainer ? range.startOffset : 0;
        const end   = node === range.endContainer   ? range.endOffset   : node.textContent.length;
        if (start < end) result.push({ node, start, end });
    }
    return result;
}


export default function AnnotationLayer({
    containerRef,
    annotations = [],
    activeTool,
    highlightColor,
    drawingColor = '#7C3AED',
    pageIdx,
    onAdd,
    onUpdate,
    onDelete,
}) {
    const canvasRef = useRef(null);
    const isDrawing = useRef(false);
    const lastPoint = useRef(null);
    const currentPath = useRef([]);
    const rafRef = useRef(null);
    const [popover, setPopover] = useState(null);

    // ── DOM-based highlight re-application ────────────────────────────────────
    // Works on plain text AND KaTeX rendered output.
    // Strategy: wrap individual TEXT NODES — never move element nodes.
    // This preserves React DOM, KaTeX layout, and inline styling completely.
    // No extractContents, no surroundContents, no DOM structure changes.
    useEffect(() => {
        if (rafRef.current) cancelAnimationFrame(rafRef.current);
        rafRef.current = requestAnimationFrame(() => {
            const container = containerRef?.current;
            if (!container) return;

            // Remove existing marks cleanly — move children back, then remove mark
            container.querySelectorAll('mark[data-ann-id]').forEach(m => {
                const parent = m.parentNode;
                if (!parent) return;
                while (m.firstChild) parent.insertBefore(m.firstChild, m);
                parent.removeChild(m);
                parent.normalize();
            });

            const highlights = annotations.filter(a => a.type === 'highlight');
            for (const ann of highlights) {
                const { selectedText, contextBefore = '', color } = ann.data || {};
                if (!selectedText) continue;
                try {
                    const range = findTextInContainer(container, selectedText, contextBefore, '');
                    if (!range) continue;

                    // Get all text nodes touched by this range with their local offsets
                    const textNodes = getTextNodesInRange(range, container);
                    if (!textNodes.length) continue;

                    for (const { node, start, end } of textNodes) {
                        const segment = (node.textContent || '').slice(start, end);
                        // Skip pure whitespace/newline segments; wrapping them with
                        // padded <mark> creates visible spacer bars between paragraphs.
                        if (!segment.trim()) continue;
                        // Isolate exactly the portion to highlight by splitting
                        let target = node;
                        if (end < target.textContent.length) target.splitText(end);
                        if (start > 0) target = target.splitText(start);
                        // Wrap that text node in a mark — parent element structure untouched
                        const mark = document.createElement('mark');
                        mark.dataset.annId = ann.id;
                        mark.style.cssText = 'background:' + (color || '#FDE68A') + ';color:' + textColorFor(color || '#FDE68A') + ';border-radius:3px;padding:0 2px;cursor:pointer;';
                        mark.addEventListener('mouseenter', () => { mark.style.opacity = '0.75'; });
                        mark.addEventListener('mouseleave', () => { mark.style.opacity = '1'; });
                        mark.addEventListener('click', (e) => {
                            e.stopPropagation();
                            const rect = mark.getBoundingClientRect();
                            setPopover({ annId: ann.id, color: color || '#FDE68A', x: rect.left + rect.width / 2, y: rect.top });
                        });
                        target.parentNode.insertBefore(mark, target);
                        mark.appendChild(target);
                    }
                } catch { /* ignore any DOM errors */ }
            }
        });
        return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [annotations, containerRef]);
    const handleRecolor = useCallback((annId, newColor) => {
        const ann = annotations.find(a => a.id === annId);
        if (!ann) return;
        onUpdate?.(annId, { data: { ...ann.data, color: newColor } });
    }, [annotations, onUpdate]);

    // ── Canvas size sync ──────────────────────────────────────────────────────
    useEffect(() => {
        const canvas = canvasRef.current;
        const container = containerRef?.current;
        if (!canvas || !container) return;
        const syncSize = () => {
            canvas.width = container.offsetWidth;
            canvas.height = container.offsetHeight;
            redrawCanvas();
        };
        syncSize();
        const ro = new ResizeObserver(syncSize);
        ro.observe(container);
        return () => ro.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [containerRef]);

    const redrawCanvas = useCallback(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        annotations.filter(a => a.type === 'drawing').forEach(ann => {
            const { paths = [], color = '#7C3AED', width = 2 } = ann.data || {};
            ctx.strokeStyle = color; ctx.lineWidth = width;
            ctx.lineCap = 'round'; ctx.lineJoin = 'round';
            paths.forEach(path => {
                if (path.length < 2) return;
                ctx.beginPath(); ctx.moveTo(path[0].x, path[0].y);
                path.slice(1).forEach(pt => ctx.lineTo(pt.x, pt.y));
                ctx.stroke();
            });
        });
    }, [annotations]);

    useEffect(() => { redrawCanvas(); }, [redrawCanvas]);

    // ── Canvas drawing ────────────────────────────────────────────────────────
    const getCanvasPoint = (e) => {
        const rect = canvasRef.current?.getBoundingClientRect();
        if (!rect) return { x: 0, y: 0 };
        return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };
    const handleCanvasPointerDown = useCallback((e) => {
        if (activeTool !== 'drawing') return;
        isDrawing.current = true; currentPath.current = [];
        const pt = getCanvasPoint(e); lastPoint.current = pt; currentPath.current.push(pt);
        canvasRef.current?.setPointerCapture(e.pointerId);
    }, [activeTool]);
    const handleCanvasPointerMove = useCallback((e) => {
        if (!isDrawing.current || activeTool !== 'drawing') return;
        const canvas = canvasRef.current; if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const pt = getCanvasPoint(e); currentPath.current.push(pt);
        ctx.strokeStyle = drawingColor; ctx.lineWidth = 2; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
        ctx.beginPath(); ctx.moveTo(lastPoint.current.x, lastPoint.current.y); ctx.lineTo(pt.x, pt.y); ctx.stroke();
        lastPoint.current = pt;
    }, [activeTool, drawingColor]);
    const handleCanvasPointerUp = useCallback(() => {
        if (!isDrawing.current) return;
        isDrawing.current = false;
        const path = [...currentPath.current]; currentPath.current = [];
        if (path.length < 2) return;
        onAdd?.({ id: uid(), page_idx: pageIdx, type: 'drawing', data: { paths: [path], color: drawingColor, width: 2 }, created_at: new Date().toISOString() });
    }, [pageIdx, drawingColor, onAdd]);

    // ── Sticky placement ──────────────────────────────────────────────────────
    const handlePageClick = useCallback((e) => {
        if (activeTool !== 'sticky') return;
        const container = containerRef?.current; if (!container) return;
        const rect = container.getBoundingClientRect();
        const x = ((e.clientX - rect.left) / rect.width) * 100;
        const y = ((e.clientY - rect.top) / rect.height) * 100;
        onAdd?.({ id: uid(), page_idx: pageIdx, type: 'sticky', data: { x, y, text: '', color: '#FEF9C3' }, created_at: new Date().toISOString() });
    }, [activeTool, containerRef, pageIdx, onAdd]);

    const handleEraserClick = useCallback(() => {
        const drawings = annotations.filter(a => a.type === 'drawing');
        if (drawings.length) onDelete?.(drawings[drawings.length - 1].id);
    }, [annotations, onDelete]);

    const stickies = annotations.filter(a => a.type === 'sticky');

    return (
        <>
            {activeTool === 'sticky' && (
                <div onClick={handlePageClick} style={{ position: 'absolute', inset: 0, zIndex: 20, cursor: 'cell', pointerEvents: 'all' }} />
            )}
            <canvas ref={canvasRef}
                onPointerDown={handleCanvasPointerDown} onPointerMove={handleCanvasPointerMove} onPointerUp={handleCanvasPointerUp}
                onClick={activeTool === 'eraser' ? handleEraserClick : undefined}
                style={{ position: 'absolute', inset: 0, zIndex: 25, pointerEvents: (activeTool === 'drawing' || activeTool === 'eraser') ? 'all' : 'none', cursor: activeTool === 'drawing' ? 'crosshair' : activeTool === 'eraser' ? 'cell' : 'default', touchAction: 'none', borderRadius: 6 }}
            />
            {stickies.map(ann => (
                <StickyNoteWidget key={ann.id} ann={ann}
                    onUpdate={(patch) => onUpdate?.(ann.id, patch)}
                    onDelete={() => onDelete?.(ann.id)} />
            ))}
            {popover && (
                <HighlightPopover annId={popover.annId} color={popover.color} x={popover.x} y={popover.y}
                    onRecolor={handleRecolor} onDelete={onDelete} onClose={() => setPopover(null)} />
            )}
        </>
    );
}

// ── StickyNoteWidget ──────────────────────────────────────────────────────────
const STICKY_COLORS = ['#FEF9C3', '#DCFCE7', '#DBEAFE', '#FCE7F3', '#EDE9FE'];
function StickyNoteWidget({ ann, onUpdate, onDelete }) {
    const { x = 20, y = 20, text = '', color = '#FEF9C3' } = ann.data || {};
    const [editing, setEditing] = useState(!text);
    const [localText, setLocalText] = useState(text);
    const [showColors, setShowColors] = useState(false);
    const nodeRef = useRef(null);
    const commitText = useCallback(() => { onUpdate({ data: { ...ann.data, text: localText } }); setEditing(false); }, [ann.data, localText, onUpdate]);
    const handleDragStart = (e) => {
        e.stopPropagation(); e.preventDefault();
        const node = nodeRef.current; if (!node) return;
        const parent = node.offsetParent; if (!parent) return;
        const pr = parent.getBoundingClientRect(), nr = node.getBoundingClientRect();
        const offX = e.clientX - nr.left, offY = e.clientY - nr.top;
        const onMove = (ev) => { node.style.left = `${Math.max(0,Math.min(85,((ev.clientX-offX-pr.left)/pr.width)*100))}%`; node.style.top = `${Math.max(0,Math.min(85,((ev.clientY-offY-pr.top)/pr.height)*100))}%`; };
        const onUp = (ev) => { onUpdate({ data: { ...ann.data, x: Math.max(0,Math.min(85,((ev.clientX-offX-pr.left)/pr.width)*100)), y: Math.max(0,Math.min(85,((ev.clientY-offY-pr.top)/pr.height)*100)) } }); window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
        window.addEventListener('mousemove', onMove); window.addEventListener('mouseup', onUp);
    };
    return (
        <div ref={nodeRef} onClick={e => e.stopPropagation()}
            style={{ position: 'absolute', left: `${x}%`, top: `${y}%`, zIndex: 50, width: 200, background: color, border: '1px solid rgba(0,0,0,0.12)', borderRadius: 8, boxShadow: '0 4px 16px rgba(0,0,0,0.18)', display: 'flex', flexDirection: 'column', fontSize: 12, pointerEvents: 'all' }}>
            <div onMouseDown={handleDragStart} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '4px 7px', borderBottom: '1px solid rgba(0,0,0,0.07)', cursor: 'grab', borderRadius: '8px 8px 0 0', background: 'rgba(0,0,0,0.04)', userSelect: 'none' }}>
                <GripHorizontal size={11} color="rgba(0,0,0,0.3)" />
                <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
                    {showColors && STICKY_COLORS.map(c => (
                        <button key={c} onMouseDown={e => { e.stopPropagation(); onUpdate({ data: { ...ann.data, color: c } }); setShowColors(false); }}
                            style={{ width: 13, height: 13, borderRadius: 3, background: c, border: color === c ? '2px solid rgba(0,0,0,0.4)' : '1px solid rgba(0,0,0,0.15)', cursor: 'pointer' }} />
                    ))}
                    <button onMouseDown={e => { e.stopPropagation(); setShowColors(p => !p); }} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 11, padding: '0 2px', color: 'rgba(0,0,0,0.4)', lineHeight: 1 }}>🎨</button>
                </div>
                <button onMouseDown={e => e.stopPropagation()} onClick={e => { e.stopPropagation(); onDelete(); }} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 2, color: 'rgba(0,0,0,0.4)', display: 'flex' }}><X size={11} /></button>
            </div>
            <div style={{ padding: 8 }}>
                {editing ? (
                    <textarea autoFocus value={localText} onChange={e => setLocalText(e.target.value)}
                        onBlur={commitText} onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) commitText(); if (e.key === 'Escape') { setEditing(false); setLocalText(text); } }}
                        placeholder="Type your note…" style={{ width: '100%', minHeight: 70, border: 'none', background: 'transparent', resize: 'none', outline: 'none', fontFamily: 'inherit', fontSize: 12, lineHeight: 1.5, color: '#1C1917' }} />
                ) : (
                    <div onDoubleClick={() => setEditing(true)} style={{ minHeight: 40, cursor: 'text', whiteSpace: 'pre-wrap', lineHeight: 1.5, color: localText ? '#1C1917' : 'rgba(0,0,0,0.35)', fontStyle: localText ? 'normal' : 'italic', fontSize: 12 }}>
                        {localText || 'Double-click to edit…'}
                    </div>
                )}
            </div>
        </div>
    );
}
