import { useState, useEffect, useCallback, useRef } from 'react';
import { API, authHeaders } from '../components/utils';

const LS_KEY = (nbId) => `ag_annotations_${nbId}`;
const AUTOSAVE_KEY = 'ag_annotations_autosave';

// ── localStorage helpers ──────────────────────────────────────────────────────

function lsLoad(nbId) {
    try { return JSON.parse(localStorage.getItem(LS_KEY(nbId)) || '[]'); }
    catch { return []; }
}

function lsSave(nbId, annotations) {
    try { localStorage.setItem(LS_KEY(nbId), JSON.stringify(annotations)); }
    catch { }
}

// ── findTextInContainer ───────────────────────────────────────────────────────
// Finds selectedText inside the rendered DOM and returns a Range.
// Works for plain text AND KaTeX-rendered math.
//
// Key correctness properties:
// 1. Skips .katex-mathml (hidden MathML screen-reader copy) — only walks
//    .katex-html (what is actually visible on screen).
// 2. Operates entirely on RAW text content (no whitespace normalisation that
//    would create offset mismatches between the search and the actual nodes).
// 3. Uses contextBefore as a disambiguation prefix so repeated phrases
//    highlight the correct occurrence.

export function findTextInContainer(container, selectedText, contextBefore = '', _contextAfter = '') {
    if (!container || !selectedText) return null;

    // NodeFilter: only accept text nodes in VISIBLE parts of the DOM.
    // KaTeX renders: .katex-html (visible) + .katex-mathml (hidden).
    // Walking mathml first means we'd match there — it's invisible so the
    // mark would be on nothing. Skip it.
    const visibleFilter = {
        acceptNode(node) {
            const el = node.parentElement;
            if (!el) return NodeFilter.FILTER_REJECT;
            // Skip KaTeX MathML (screen-reader only, invisible)
            if (el.closest('.katex-mathml, math')) return NodeFilter.FILTER_REJECT;
            // Skip aria-hidden subtrees
            if (el.closest('[aria-hidden="true"]')) return NodeFilter.FILTER_REJECT;
            return NodeFilter.FILTER_ACCEPT;
        }
    };

    // Collect all visible text nodes
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, visibleFilter);
    const nodes = [];
    let n;
    while ((n = walker.nextNode())) nodes.push(n);

    if (!nodes.length) return null;

    // Build the raw concatenated text (NO normalisation — keeps offsets valid)
    const rawParts = nodes.map(nd => nd.textContent);
    const rawFull  = rawParts.join('');

    // Search with context prefix first (handles repeated phrases)
    const needle = contextBefore + selectedText;
    let matchStart = rawFull.indexOf(needle);
    let textStart;
    if (matchStart !== -1) {
        textStart = matchStart + contextBefore.length;
    } else {
        // Fallback: find selectedText directly
        textStart = rawFull.indexOf(selectedText);
        if (textStart === -1) {
            // Last resort: case-insensitive + whitespace-collapsed match
            const collapse = s => s.replace(/\s+/g, ' ').trim();
            const collFull = collapse(rawFull);
            const collSel  = collapse(selectedText);
            const collIdx  = collFull.indexOf(collSel);
            if (collIdx === -1) return null;
            // Map collapsed index back to raw index (approximate)
            textStart = mapCollapsedToRaw(rawFull, collIdx);
            if (textStart === -1) return null;
        }
    }

    const textEnd = textStart + selectedText.length;
    return buildRange(nodes, rawParts, textStart, textEnd);
}

// Map an index in whitespace-collapsed string back to an index in the raw string
function mapCollapsedToRaw(raw, collapsedIdx) {
    let rawIdx = 0, collIdx = 0;
    let inSpace = false;
    for (let i = 0; i < raw.length; i++) {
        if (/\s/.test(raw[i])) {
            if (!inSpace) { collIdx++; inSpace = true; }
        } else {
            collIdx++;
            inSpace = false;
        }
        if (collIdx > collapsedIdx) return i;
        rawIdx = i;
    }
    return rawIdx;
}

// Given text nodes, their raw parts, and start/end offsets into the
// concatenated raw string, build a DOM Range.
function buildRange(nodes, rawParts, startOff, endOff) {
    let cumulative = 0;
    let startNode = null, startOff_ = 0, endNode = null, endOff_ = 0;

    for (let i = 0; i < nodes.length; i++) {
        const len = rawParts[i].length;
        const nodeStart = cumulative;
        const nodeEnd   = cumulative + len;

        if (startNode === null && nodeEnd > startOff) {
            startNode = nodes[i];
            startOff_ = startOff - nodeStart;
        }
        if (endNode === null && nodeEnd >= endOff) {
            endNode = nodes[i];
            endOff_ = endOff - nodeStart;
            break;
        }
        cumulative += len;
    }

    if (!startNode || !endNode) return null;

    try {
        const range = document.createRange();
        range.setStart(startNode, Math.min(startOff_, startNode.textContent.length));
        range.setEnd(endNode,   Math.min(endOff_,   endNode.textContent.length));
        return range;
    } catch {
        return null;
    }
}

// ── Main hook ─────────────────────────────────────────────────────────────────

export function useAnnotations(notebookId) {
    const [annotations, setAnnotationsRaw] = useState([]);
    const [activeTool, setActiveTool] = useState(null); // 'highlight' | 'sticky' | 'drawing' | 'eraser' | null
    const [highlightColor, setHighlightColor] = useState('#FDE68A');
    const [drawingColor, setDrawingColor] = useState('#7C3AED');
    const [autoSave, setAutoSave] = useState(
        () => localStorage.getItem(AUTOSAVE_KEY) !== 'false'
    );
    const synced = useRef(false);
    const debounceTimer = useRef(null);

    // ── Load on mount ───────────────────────────────────────────────────────
    useEffect(() => {
        if (!notebookId || synced.current) return;
        synced.current = true;
        setAnnotationsRaw(lsLoad(notebookId));
        fetch(`${API}/api/notebooks/${notebookId}/annotations`, { headers: authHeaders() })
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                if (data?.annotations?.length) {
                    setAnnotationsRaw(data.annotations);
                    lsSave(notebookId, data.annotations);
                }
            })
            .catch(() => { });
    }, [notebookId]);

    useEffect(() => {
        localStorage.setItem(AUTOSAVE_KEY, String(autoSave));
    }, [autoSave]);

    const setAnnotations = useCallback((updater) => {
        setAnnotationsRaw(prev => {
            const next = typeof updater === 'function' ? updater(prev) : updater;
            lsSave(notebookId, next);
            return next;
        });
    }, [notebookId]);

    const syncToBackend = useCallback((ann) => {
        if (!autoSave) return;
        if (debounceTimer.current) clearTimeout(debounceTimer.current);
        debounceTimer.current = setTimeout(() => {
            fetch(`${API}/api/notebooks/${notebookId}/annotations`, {
                method: 'POST',
                headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify(ann),
            }).catch(() => { });
        }, 600);
    }, [autoSave, notebookId]);

    const addAnnotation = useCallback((ann) => {
        setAnnotations(prev => [...prev.filter(a => a.id !== ann.id), ann]);
        syncToBackend(ann);
    }, [setAnnotations, syncToBackend]);

    const updateAnnotation = useCallback((id, patch) => {
        setAnnotations(prev => {
            const next = prev.map(a => a.id === id ? { ...a, ...patch, data: { ...a.data, ...patch.data } } : a);
            const updated = next.find(a => a.id === id);
            if (updated) syncToBackend(updated);
            return next;
        });
    }, [setAnnotations, syncToBackend]);

    const deleteAnnotation = useCallback((id) => {
        setAnnotations(prev => prev.filter(a => a.id !== id));
        if (autoSave) {
            fetch(`${API}/api/notebooks/${notebookId}/annotations/${id}`, {
                method: 'DELETE', headers: authHeaders(),
            }).catch(() => { });
        }
    }, [setAnnotations, autoSave, notebookId]);

    const clearAllAnnotations = useCallback(() => {
        setAnnotations([]);
        if (autoSave) {
            fetch(`${API}/api/notebooks/${notebookId}/annotations`, {
                method: 'DELETE', headers: authHeaders(),
            }).catch(() => { });
        }
    }, [setAnnotations, autoSave, notebookId]);

    const saveAllToBackend = useCallback(async () => {
        const current = lsLoad(notebookId);
        for (const ann of current) {
            await fetch(`${API}/api/notebooks/${notebookId}/annotations`, {
                method: 'POST',
                headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify(ann),
            }).catch(() => { });
        }
    }, [notebookId]);

    const getPageAnnotations = useCallback((pageIdx) =>
        annotations.filter(a => a.page_idx === pageIdx),
    [annotations]);

    return {
        annotations,
        activeTool, setActiveTool,
        highlightColor, setHighlightColor,
        drawingColor, setDrawingColor,
        autoSave, setAutoSave,
        addAnnotation,
        updateAnnotation,
        deleteAnnotation,
        clearAllAnnotations,
        saveAllToBackend,
        getPageAnnotations,
    };
}
