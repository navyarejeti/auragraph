import { useState, useMemo, useRef, useEffect, useCallback } from 'react';

const UNDO_TTL_MS = 5 * 60 * 1000; // 5 minutes

/**
 * Paginates the note markdown into pages, handles current page index,
 * view mode, font size, jump-highlight set, and keyboard navigation.
 *
 * @param {string} note - Raw markdown note text
 * @param {{ mutating: boolean }} opts
 */
export function usePagination(note, { mutating = false, setMutating, setShowSearch, setShowShortcuts } = {}) {
    const [currentPage, setCurrentPage] = useState(0);
    const [viewMode, setViewMode] = useState('single');
    const [fontSize, setFontSize] = useState(() =>
        parseInt(localStorage.getItem('ag_font_size') || '16', 10)
    );
    const [jumpHighlightSet, setJumpHighlightSet] = useState(new Set());
    const noteScrollRef = useRef(null);

    const pages = useMemo(() => {
        if (!note) return [];
        let clean = note.replace(
            /^\s*The notes are factually accurate,? and no corrections are needed\.?\s*(?:Here is (?:the )?content unchanged:?\s*)?(?:\n\s*---\s*\n?)?/i,
            ''
        );
        clean = clean.replace(/^\s*```+\s*(?:markdown|md|latex|text)?\s*\n/gm, '');
        clean = clean.replace(/\n\s*```+\s*$/g, '');
        const byH2 = clean.split(/(?=^## )/m).map(s => s.trim()).filter(Boolean);
        if (byH2.length > 0) {
            // Each ## section is its own page — no merging.
            // Study notes are organised by topic; merging sections across topics
            // causes "4 pages" even when 20+ topics were generated.
            return byH2.filter(Boolean);
        }
        const byH3 = clean.split(/(?=^### )/m).map(s => s.trim()).filter(Boolean);
        if (byH3.length > 1) return byH3;
        const mathAwareSplit = (text) => {
            const segments = []; let inMath = false; let buf = [];
            for (const line of text.split('\n')) {
                if (line.trim() === '$$') inMath = !inMath;
                if (!inMath && line === '' && buf.length > 0) {
                    const seg = buf.join('\n').trim();
                    if (seg.length > 40) segments.push(seg);
                    buf = [];
                } else { buf.push(line); }
            }
            if (buf.length > 0) {
                const seg = buf.join('\n').trim();
                if (seg.length > 40) segments.push(seg);
            }
            return segments;
        };
        const paras = mathAwareSplit(clean);
        const chunks = []; let cur = '';
        for (const p of paras) {
            if (cur.length + p.length > 700 && cur.length > 150) { chunks.push(cur.trim()); cur = p; }
            else { cur += (cur ? '\n\n' : '') + p; }
        }
        if (cur) chunks.push(cur.trim());
        return chunks.length ? chunks : [clean];
    }, [note]);

    // Persist font size preference
    useEffect(() => {
        localStorage.setItem('ag_font_size', String(fontSize));
    }, [fontSize]);

    // Snap to even index when entering two-page mode
    useEffect(() => {
        if (viewMode === 'two' && currentPage % 2 !== 0) {
            setCurrentPage(p => Math.max(0, p - 1));
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [viewMode]);

    // Scroll to top on page change
    useEffect(() => {
        noteScrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
    }, [currentPage]);

    // Keyboard navigation
    useEffect(() => {
        const isTyping = (el) =>
            el.tagName === 'INPUT' ||
            el.tagName === 'TEXTAREA' ||
            el.tagName === 'SELECT' ||
            el.isContentEditable;

        const h = (e) => {
            if (isTyping(e.target)) return;
            if (mutating) return;
            if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                e.preventDefault();
                setCurrentPage(p => Math.min(pages.length - 1, p + 1));
            } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                e.preventDefault();
                setCurrentPage(p => Math.max(0, p - 1));
            } else if (e.key === 'd' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                setMutating?.(true);
            } else if (e.key === 'f' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                setShowSearch?.(true);
            } else if (e.key === '?' || (e.key === '/' && e.shiftKey)) {
                setShowShortcuts?.(true);
            }
        };
        window.addEventListener('keydown', h);
        return () => window.removeEventListener('keydown', h);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pages.length, mutating]);

    const handleJumpToSection = useCallback((label) => {
        if (!label || !pages.length) return;
        const normalise = s => s.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();
        const searchWords = normalise(label).split(' ').filter(w => w.length > 2);
        const ll = normalise(label);
        let idx = pages.findIndex(p => normalise(p).includes(ll));
        if (idx === -1 && ll.startsWith('##')) {
            idx = pages.findIndex(p => normalise(p).includes(ll.replace(/^#+\s*/, '')));
        }
        if (idx === -1 && searchWords.length > 0) {
            let bestScore = 0;
            pages.forEach((p, i) => {
                const headingArea = normalise(p.slice(0, 200));
                const score = searchWords.filter(w => headingArea.includes(w)).length;
                const fraction = score / searchWords.length;
                if (fraction > 0.5 && score > bestScore) { bestScore = score; idx = i; }
            });
        }
        if (idx === -1 && searchWords.length > 0) {
            const significant = searchWords.filter(w => w.length > 4);
            if (significant.length > 0)
                idx = pages.findIndex(p => significant.some(w => normalise(p.slice(0, 300)).includes(w)));
        }
        if (idx !== -1) {
            setCurrentPage(idx);
            setJumpHighlightSet(new Set([idx]));
            setTimeout(() => setJumpHighlightSet(new Set()), 1800);
        }
    }, [pages]);

    return {
        pages,
        currentPage, setCurrentPage,
        viewMode, setViewMode,
        fontSize, setFontSize,
        jumpHighlightSet, setJumpHighlightSet,
        noteScrollRef,
        handleJumpToSection,
    };
}
