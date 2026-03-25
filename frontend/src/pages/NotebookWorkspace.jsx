import React, { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useDispatch } from 'react-redux';
import { addToast } from '../store';
import { ls_getNotebook, ls_saveNote } from '../localNotebooks';
import {
    Sparkles, Loader2, ChevronLeft, ChevronRight, Upload, FileText,
    BookOpen, MessageSquare, ArrowLeft, Brain, CheckCircle2,
    AlertCircle, MinusCircle, RefreshCw, X, ChevronDown, ChevronUp,
    MessageCircle, GitBranch, Copy, Check, Download, PenLine, Columns2, ScrollText, Moon, Sun, Search,
    Keyboard, Printer, Undo2, PanelRight, GraduationCap, Network, Zap, Maximize2, Minimize2, Volume2, Languages
} from 'lucide-react';
import { API, authHeaders, apiFetch, loadDoubts, saveDoubts, parseApiError } from '../components/utils';
import { useDarkMode } from '../hooks/useDarkMode';
import FuseProgressBar from '../components/FuseProgressBar';
import SourceInputPanel from '../components/SourceInputPanel';
import MutateModal from '../components/MutateModal';
import { ExaminerModal } from '../components/ExaminerModals';
import { GalaxyGraph } from '../components/Graph';
import SniperExamModal from '../components/SniperExamModal';
import { StudyTimer, NoteSearch, ShortcutsModal } from '../components/StudyTools';
import KnowledgePanel from '../components/KnowledgePanel';
import NoteRenderer from '../components/NoteRenderer';
import DoubtsPanel from '../components/DoubtsPanel';
import { CopyNoteButton, DownloadNoteButton, PrintNoteButton, UndoToast } from '../components/NoteToolbar';
import AnnotationToolbar from '../components/AnnotationToolbar';
import AnnotationLayer from '../components/AnnotationLayer';
import { useAnnotations } from '../hooks/useAnnotations';
import { useAura, NOTE_THEMES } from '../hooks/useAura';
import AuraPanel from '../components/AuraPanel';
import { XPToast, BadgeLevelUpToast } from '../components/AuraBadgeToast';
import { useNotebookData } from '../hooks/useNotebookData';
import { useDoubtsLog } from '../hooks/useDoubtsLog';
import { useKnowledgeGraph } from '../hooks/useKnowledgeGraph';
import { usePagination } from '../hooks/usePagination';
import { useUndoStack } from '../hooks/useUndoStack';
import { useFuse } from '../hooks/useFuse';
import { useSidebar } from '../hooks/useSidebar';
import FeedbackWidget from '../components/FeedbackWidget';
import VirtualKeyboard from '../components/VirtualKeyboard';
import ShortNotesModal from '../components/ShortNotesModal';
import { useFullscreen } from '../hooks/useFullscreen';
import { useTextToSpeech } from '../hooks/useTextToSpeech';
import AudioPlayer from '../components/AudioPlayer';
import TranslateModal from '../components/TranslateModal';

export default function NotebookWorkspace() {
    const { id } = useParams();
    const navigate = useNavigate();

    // ── UI state (not owned by any single hook) ─────────────────────────────
    const [darkMode, setDarkMode] = useDarkMode();
    const [mutating, setMutating] = useState(false);
    const [gapText, setGapText] = useState('');
    const [mutatedPages, setMutatedPages] = useState(new Set());
    const [rightTab, setRightTab] = useState(null); // null=hidden, 'map', 'doubts'
    const [studyHubSeen, setStudyHubSeen] = useState(() => !!localStorage.getItem('ag_studyhub_seen'));
    const [textSelection, setTextSelection] = useState(null);
    const [pendingSelectionText, setPendingSelectionText] = useState('');
    const [showSearch, setShowSearch] = useState(false);
    const [showShortcuts, setShowShortcuts] = useState(false);
    const [showTopToolbar, setShowTopToolbar] = useState(true);
    const [searchHighlight, setSearchHighlight] = useState('');
    const [editingPage, setEditingPage] = useState(false);
    const [pageInputVal, setPageInputVal] = useState('');
    const [regenLoadingPages, setRegenLoadingPages] = useState(new Set());
    const [pendingNavSection, setPendingNavSection] = useState(null); // section title → navigate after note reload
    const [regenPromptState, setRegenPromptState] = useState({ open: false, pageIdx: null, prompt: '' });

    // ── Custom hooks ─────────────────────────────────────────────────────────
    const { graphNodes, setGraphNodes, graphEdges, setGraphEdges, handleNodeStatusChange } = useKnowledgeGraph(id);
    const {
        notebook, setNotebook, note, setNote, prof, setProf,
        saveNote, extractAndSaveGraph, loadNotebook, reloadNote, autoExtractRef,
    } = useNotebookData(id, { setGraphNodes, setGraphEdges });
    const { doubtsLog, setDoubtsLog } = useDoubtsLog(id);
    const {
        pages, currentPage, setCurrentPage, viewMode, setViewMode,
        fontSize, setFontSize, jumpHighlightSet, noteScrollRef, handleJumpToSection,
    } = usePagination(note, { mutating, setMutating, setShowSearch, setShowShortcuts });
    const { undoToast, pushUndo, handleUndoCommit, dismissUndo } = useUndoStack({ saveNote, setNote, setProf });
    const {
        slidesFiles, setSlidesFiles, textbookFiles, setTextbookFiles,
        notesFiles, setNotesFiles, fusing, fuseProgress, verifyingStep,
        noteSource, fallbackWarning, setFallbackWarning, handleFuse,
        mediaChunks, setMediaChunks, mediaSourceDesc, setMediaSourceDesc,
    } = useFuse(id, { prof, setNote, setCurrentPage, setMutatedPages, saveNote, extractAndSaveGraph });
    const { sidebarWidth, startResizeSidebar } = useSidebar();
    const dispatch = useDispatch();

    // ── Annotations ──────────────────────────────────────────────────────────
    const {
        annotations,
        activeTool, setActiveTool,
        highlightColor, setHighlightColor,
        drawingColor, setDrawingColor,
        autoSave, setAutoSave,
        addAnnotation, updateAnnotation, deleteAnnotation,
        clearAllAnnotations, saveAllToBackend,
        getPageAnnotations,
    } = useAnnotations(id);

    // ── Aura gamification ────────────────────────────────────────────────────
    const aura = useAura();
    const [showAuraPanel, setShowAuraPanel] = useState(false);
    const [showVirtualKeyboard, setShowVirtualKeyboard] = useState(false);
    const [showShortNotes, setShowShortNotes] = useState(false);
    const { isFullscreen, toggle: toggleFullscreen } = useFullscreen();
    const tts = useTextToSpeech();
    const [showTranslate, setShowTranslate] = useState(false);
    const [translatePageIdx, setTranslatePageIdx] = useState(null);
    const [xpToast, setXpToast] = useState(null);
    const [badgeToast, setBadgeToast] = useState(null);
    const awardAura = useCallback((reason, count = 1) => {
        const result = aura.award(reason, count);
        if (result.gained > 0) setXpToast({ gained: result.gained });
        if (result.badgeUp) setBadgeToast(result.badgeUp);
    }, [aura]);

    const awardQuizCompletion = useCallback((correct, total) => {
        const safeTotal = Number(total) || 0;
        const safeCorrect = Math.max(0, Number(correct) || 0);
        if (safeTotal <= 0) return;

        const rCorrect = aura.award('correct_answer', safeCorrect);
        const rComplete = aura.award('quiz_complete');
        const pct = Math.round((safeCorrect / safeTotal) * 100);
        const rBonus = pct >= 80 ? aura.award('high_score_bonus') : { gained: 0, badgeUp: null };

        const gained = (rCorrect.gained || 0) + (rComplete.gained || 0) + (rBonus.gained || 0);
        if (gained > 0) setXpToast({ gained });

        const badgeUp = rBonus.badgeUp || rComplete.badgeUp || rCorrect.badgeUp;
        if (badgeUp) setBadgeToast(badgeUp);
        return gained;   // DoneScreen displays this
    }, [aura]);

    // ── On mount ─────────────────────────────────────────────────────────────
    useEffect(() => {
        autoExtractRef.current = false;
        loadNotebook();
    }, [loadNotebook]);
    // ── Content fingerprint helpers — keyed by content, not index, so badges survive page shifts ──
    const getFingerprint = useCallback((content) => (content || '').trim().replace(/\s+/g, ' ').slice(0, 100), []);
    const isPageMutated  = useCallback((idx) => mutatedPages.has(getFingerprint(pages[idx] || '')), [mutatedPages, pages, getFingerprint]);

    // ── Navigate to a pending section after note reload (from ⚡ generate or regen) ──
    useEffect(() => {
        if (!pendingNavSection || !pages.length) return;
        const heading = `## ${pendingNavSection}`;
        const idx = pages.findIndex(p => p.trim().startsWith(heading) || p.includes(heading));
        if (idx !== -1) {
            setCurrentPage(idx);
            setMutatedPages(prev => new Set([...prev, getFingerprint(pages[idx])]));
            setPendingNavSection(null);
        }
    }, [pages, pendingNavSection, getFingerprint]);

    // ── Scroll to & highlight search match after page jump ──────────────────
    useEffect(() => {
        if (!searchHighlight) return;
        const timer = setTimeout(() => {
            const container = noteScrollRef.current;
            if (!container) return;
            // Walk all text nodes inside the note body to find the match
            const query = searchHighlight.toLowerCase();
            const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, null);
            let node;
            while ((node = walker.nextNode())) {
                const idx = node.textContent.toLowerCase().indexOf(query);
                if (idx === -1) continue;
                // Found the match — wrap it in a <mark> and scroll to it
                const range = document.createRange();
                range.setStart(node, idx);
                range.setEnd(node, idx + searchHighlight.length);
                const mark = document.createElement('mark');
                mark.className = 'search-highlight-match';
                mark.style.background = 'rgba(250,204,21,0.6)';
                mark.style.borderRadius = '2px';
                mark.style.padding = '1px 2px';
                mark.style.scrollMarginTop = '120px';
                range.surroundContents(mark);
                mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
                // Remove highlight after 3s
                setTimeout(() => {
                    mark.style.transition = 'background 0.8s';
                    mark.style.background = 'transparent';
                    setTimeout(() => {
                        const parent = mark.parentNode;
                        if (parent) { parent.replaceChild(document.createTextNode(mark.textContent), mark); parent.normalize(); }
                    }, 900);
                }, 3000);
                break;
            }
            setSearchHighlight('');
        }, 200); // wait for page render
        return () => clearTimeout(timer);
    }, [searchHighlight, currentPage]);

    const handlePrint = useCallback(() => { window.print(); }, []);

    const printablePages = useMemo(
        () => pages.filter((p) => typeof p === 'string' && p.replace(/\s+/g, '').length > 0),
        [pages]
    );




    const handleMutate = useCallback(async (page, doubt) => {
        const ts = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const lid = String(Date.now());
        try {
            // New API: send notebook_id + page_idx so backend can retrieve full context
            const res = await apiFetch(`${API}/api/mutate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    notebook_id: id,
                    doubt,
                    page_idx: currentPage,
                    original_paragraph: page,  // kept as fallback
                })
            });
            const data = await res.json();

            if (data.can_mutate === false) {
                // LLM unavailable — don't clobber the original notes with a local fallback.
                // Instead, inject a visible unresolved-doubt anchor into the current page.
                const anchorMd = `\n\n> ⚠ **Unresolved Doubt** *(AI unavailable — will resolve automatically when online)*: "${doubt}" — [→ View in Doubts panel](#doubt-${lid})\n`;
                const trimmedPage = (pages[currentPage] || page).trim();
                const noteIdx = note.indexOf(trimmedPage);
                const newNote = noteIdx !== -1
                    ? note.slice(0, noteIdx) + trimmedPage + anchorMd + note.slice(noteIdx + trimmedPage.length)
                    : note + anchorMd;
                setNote(newNote);
                await saveNote(newNote, prof);
                const entry = { id: lid, pageIdx: currentPage, doubt, insight: 'AI unavailable — doubt saved. Your note has a reminder link. Retry when back online.', gap: data.concept_gap || '', source: 'local', time: ts, success: false, unresolved: true };
                setDoubtsLog(prev => [entry, ...prev]);
                awardAura('doubt');
                setRightTab('doubts');
            } else {
                // LLM succeeded — replace the page with the rewritten version
                const mutatedParagraph = data.mutated_paragraph || '';
                // Safety: never write undefined/empty into the note — keep the original
                if (!mutatedParagraph.trim()) {
                    dispatch(addToast({ kind: 'warning', title: 'Rewrite returned empty', message: 'The AI rewrite was empty — your original note is unchanged.' }));
                    return;
                }
                const trimmedPage = (pages[currentPage] || page).trim();
                const noteIdx = note.indexOf(trimmedPage);
                let newNote;
                if (noteIdx !== -1) {
                    newNote = note.slice(0, noteIdx) + mutatedParagraph + note.slice(noteIdx + trimmedPage.length);
                } else {
                    newNote = note + '\n\n---\n\n**Amendment (page ' + (currentPage + 1) + '):**\n\n' + mutatedParagraph;
                }
                pushUndo(note, prof, `Page ${currentPage + 1} mutated`);
                setNote(newNote); setGapText(data.concept_gap);
                setMutatedPages(prev => new Set([...prev, getFingerprint(mutatedParagraph || pages[currentPage] || '')]));
                await saveNote(newNote, prof);
                extractAndSaveGraph(newNote).catch(() => { });
                const insight = data.answer || data.concept_gap || 'Your note was rewritten to address this doubt.';
                setDoubtsLog(prev => {
                    if (prev.some(d => d.doubt === doubt && d.kind === 'answered')) return prev;
                    return [{ id: lid, pageIdx: currentPage, doubt, insight, gap: data.concept_gap, source: data.source || 'azure', time: ts, success: true, kind: 'mutated' }, ...prev];
                });
                awardAura('doubt');
                setRightTab('doubts');
            }
        } catch (err) {
            dispatch(addToast({
                kind: 'error',
                title: 'Mutation failed',
                message: err?.message?.includes('401') || err?.message?.includes('403')
                    ? 'Session expired — please log in again.'
                    : err?.message || 'Could not reach the backend.',
            }));
            const entry = { id: lid, pageIdx: currentPage, doubt, insight: 'Could not reach backend. Your doubt has been recorded.', gap: 'Backend unreachable', time: ts, success: false };
            setDoubtsLog(prev => [entry, ...prev]);
            setRightTab('doubts');
        }
    }, [note, prof, id, currentPage, pages]);

    const handleRegenSection = useCallback(async (pageIdx, customPrompt = '') => {
        setRegenLoadingPages(prev => new Set([...prev, pageIdx]));
        try {
            const res = await apiFetch(`${API}/api/regenerate-section`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    notebook_id: id,
                    page_idx: pageIdx,
                    proficiency: prof,
                    ...(customPrompt.trim() ? { custom_prompt: customPrompt.trim() } : {}),
                }),
            });
            if (!res.ok) {
                let detail = `Server error (${res.status})`;
                try { const j = await res.json(); detail = parseApiError(j.detail, detail); } catch { }
                throw new Error(detail);
            }
            const data = await res.json();
            if (!data.new_section?.trim()) throw new Error('Empty response from server');

            // Push undo before clobbering the note
            pushUndo(note, prof, `Page ${pageIdx + 1} regenerated`);
            // Re-fetch the full note — backend already persisted the updated version
            const nbRes = await apiFetch(`${API}/notebooks/${id}`);
            if (nbRes.ok) {
                const nb = await nbRes.json();
                const freshNote = nb.note || '';
                setNote(freshNote);
                await saveNote(freshNote, prof);
            }
            // Navigate to the regenerated page by its heading (not a stale numeric index)
            // so the badge always lands on the correct page even if earlier ⚡ generates shifted pages.
            const rawHeading = data.new_section.trim().split('\n')[0].replace(/^#+\s*/, '').trim();
            setPendingNavSection(rawHeading);
        } catch (err) {
            dispatch(addToast({
                kind: 'error',
                title: 'Regeneration failed',
                message: err?.message || 'Could not regenerate this section. Is the backend running?',
            }));
            console.error('Re-generate section failed:', err);
        }
        setRegenLoadingPages(prev => { const s = new Set(prev); s.delete(pageIdx); return s; });
    }, [note, prof, id]);

    const handleNoteMouseUp = useCallback(() => {
        const sel = window.getSelection();
        const selText = sel?.toString().trim();
        if (!selText || selText.length <= 4) {
            setTextSelection(null);
            return;
        }

        // Capture range info for both highlight and ask-doubt
        let rangeInfo = null;
        try {
            const range = sel.getRangeAt(0);
            const rect = range.getBoundingClientRect();
            const contextLen = 20;
            const preRange = document.createRange();
            preRange.setStart(range.startContainer, Math.max(0, range.startOffset - contextLen));
            preRange.setEnd(range.startContainer, range.startOffset);
            rangeInfo = {
                contextBefore: preRange.toString(),
                x: rect.left + rect.width / 2,
                y: rect.top,
            };
        } catch { return; }

        if (activeTool === 'highlight') {
            // Show a popup with two choices: Highlight OR Ask about this
            // Never silently highlight — user must confirm
            setTextSelection({
                text: selText,
                x: rangeInfo.x,
                y: rangeInfo.y,
                pendingHighlight: {
                    selectedText: selText,
                    contextBefore: rangeInfo.contextBefore,
                },
            });
            return;
        }

        // Normal mode — show "Ask about this" popup
        setTextSelection({ text: selText, x: rangeInfo.x, y: rangeInfo.y });
    }, [activeTool]);

    // ── Per-page card refs for AnnotationLayer ───────────────────────────────
    const pageCardRefs = useRef({});
    const getPageCardRef = (idx) => {
        if (!pageCardRefs.current[idx]) {
            pageCardRefs.current[idx] = React.createRef();
        }
        return pageCardRefs.current[idx];
    };

    // Escape key exits annotation mode
    useEffect(() => {
        const h = (e) => { if (e.key === 'Escape' && activeTool) setActiveTool(null); };
        window.addEventListener('keydown', h);
        return () => window.removeEventListener('keydown', h);
    }, [activeTool, setActiveTool]);

    if (!notebook) return <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--surface)' }}><Loader2 className="spin" size={28} color="var(--text3)" /></div>;

    const hasNote = note.trim().length > 0;
    const activeTheme = aura.activeTheme;
    const noteTheme = NOTE_THEMES[activeTheme] || NOTE_THEMES.default;
    const viewerTheme = darkMode
        ? {
            ...noteTheme,
            scrollBg: 'linear-gradient(160deg,#0b1020 0%,#0f1428 45%,#0a1222 100%)',
            cardBg: '#12182c',
            cardBorder: '#2b3652',
            rings: 'linear-gradient(180deg,#18223b,#141e34)',
            ringBorder: '#334155',
            ringDot: '#64748b',
            marginLine: 'linear-gradient(180deg,#334155 0%,#475569 50%,#334155 100%)',
        }
        : noteTheme;

    return (
        <div className="notebook-workspace-root" style={{ height: '100vh', background: 'var(--bg)', display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
            {/* ── Row 1: Identity + primary nav ───────────────────────────── */}
            <header style={{ background: 'var(--bg)', borderBottom: '1px solid var(--border)', padding: '0 16px 0 20px', height: 56, display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0, minWidth: 0, gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0, flexShrink: 1 }}>
                    <button className="btn btn-ghost btn-sm" onClick={() => navigate('/dashboard')} style={{ gap: 4, flexShrink: 0 }}><ArrowLeft size={14} /> Notebooks</button>
                    <div style={{ width: 1, height: 20, background: 'var(--border)', flexShrink: 0 }} />
                    <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 700, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {notebook.name}
                            {localStorage.getItem('ag_token') === 'demo-token' && (
                                <span style={{ marginLeft: 8, fontSize: 10, fontWeight: 600, background: '#FEF3C7', color: '#92400E', border: '1px solid #FDE68A', borderRadius: 10, padding: '1px 7px', verticalAlign: 'middle' }}>DEMO</span>
                            )}
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{notebook.course}</div>
                    </div>
                    {hasNote && (<>
                        <div style={{ width: 1, height: 20, background: 'var(--border)', flexShrink: 0 }} />
                        <div style={{ display: 'flex', gap: 2, background: 'var(--surface)', padding: 2, borderRadius: 8, border: '1px solid var(--border)', flexShrink: 0 }}>
                            {['Foundations', 'Practitioner', 'Expert'].map(p => (
                                <button key={p} onClick={() => {
                                    if (p === prof) return;
                                    if (window.confirm(`Switch to ${p} level?\n\nThis will take you back to the upload screen. Re-upload your materials to regenerate notes at the new level.`)) {
                                        setProf(p); setNote('');
                                    }
                                }} title={p === prof ? `Current: ${p}` : `Re-generate at ${p} level`} style={{ padding: '3px 8px', borderRadius: 5, border: 'none', cursor: p === prof ? 'default' : 'pointer', background: prof === p ? 'var(--ag-purple)' : 'transparent', color: prof === p ? '#fff' : 'var(--text3)', fontSize: 10, fontWeight: 600, transition: 'all 0.15s', whiteSpace: 'nowrap' }}>{p}</button>
                            ))}
                        </div>
                        <div style={{ width: 1, height: 20, background: 'var(--border)', flexShrink: 0 }} />
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'var(--surface)', padding: '4px 10px', borderRadius: 20, border: '1px solid var(--border)', flexShrink: 0 }}>
                            <button data-testid="prev-page" onClick={() => setCurrentPage(Math.max(0, currentPage - (viewMode === 'two' ? 2 : 1)))} disabled={currentPage === 0} title="Previous (←)" style={{ background: 'none', border: 'none', color: currentPage === 0 ? 'var(--border2)' : 'var(--text2)', cursor: currentPage === 0 ? 'not-allowed' : 'pointer', padding: 0, display: 'flex' }}><ChevronLeft size={14} /></button>
                            {editingPage ? (
                                <input autoFocus type="number" min={1} max={pages.length} value={pageInputVal}
                                    onChange={e => setPageInputVal(e.target.value)}
                                    onKeyDown={e => {
                                        if (e.key === 'Enter') { const n = parseInt(pageInputVal, 10); if (!isNaN(n)) setCurrentPage(Math.max(0, Math.min(pages.length - 1, n - 1))); setEditingPage(false); setPageInputVal(''); }
                                        else if (e.key === 'Escape') { setEditingPage(false); setPageInputVal(''); }
                                    }}
                                    onBlur={() => { setEditingPage(false); setPageInputVal(''); }}
                                    style={{ width: 46, textAlign: 'center', fontSize: 12, border: '1px solid var(--purple)', borderRadius: 4, padding: '1px 4px', background: 'var(--bg)', color: 'var(--text)', outline: 'none' }}
                                />
                            ) : (
                                <span onClick={() => { setEditingPage(true); setPageInputVal(String(currentPage + 1)); }} title="Click to jump to a page"
                                    style={{ fontSize: 12, color: 'var(--text2)', minWidth: 48, textAlign: 'center', cursor: 'pointer', borderRadius: 4, padding: '1px 3px' }}
                                    onMouseEnter={e => e.currentTarget.style.background = 'var(--surface2)'}
                                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                                >{currentPage + 1}{viewMode === 'two' && pages[currentPage + 1] ? `-${currentPage + 2}` : ''} / {pages.length}</span>
                            )}
                            <button data-testid="next-page" onClick={() => setCurrentPage(p => {
                                if (viewMode === 'two') { const maxLeft = Math.floor((pages.length - 1) / 2) * 2; return Math.min(maxLeft, p + 2); }
                                return Math.min(pages.length - 1, p + 1);
                            })} disabled={viewMode === 'two' ? currentPage >= Math.floor((pages.length - 1) / 2) * 2 : currentPage >= pages.length - 1} title="Next (→)" style={{ background: 'none', border: 'none', color: (viewMode === 'two' ? currentPage >= Math.floor((pages.length - 1) / 2) * 2 : currentPage >= pages.length - 1) ? 'var(--border2)' : 'var(--text2)', cursor: (viewMode === 'two' ? currentPage >= Math.floor((pages.length - 1) / 2) * 2 : currentPage >= pages.length - 1) ? 'not-allowed' : 'pointer', padding: 0, display: 'flex' }}><ChevronRight size={14} /></button>
                        </div>
                    </>)}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                    {hasNote && (<>
                        <button data-testid="ask-doubt-btn" className="btn btn-primary btn-sm" style={{ gap: 5 }} onClick={() => setMutating(true)} title="Ask a doubt (Ctrl+D)"><MessageSquare size={13} /> Ask a Doubt</button>
                        <div style={{ width: 1, height: 20, background: 'var(--border)' }} />
                        {/* Aura Score button */}
                        <button onClick={() => setShowAuraPanel(true)} title="Aura Score & Badges"
                            style={{ padding: '4px 10px', height: 32, borderRadius: 7, border: `1px solid ${aura.badge.border}`, background: aura.badge.bg, color: aura.badge.color, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, fontWeight: 700, transition: 'all 0.15s', flexShrink: 0 }}>
                            {aura.badge.emoji} {aura.data.xp.toLocaleString()} XP
                        </button>
                        <div style={{ width: 1, height: 20, background: 'var(--border)' }} />
                        {/* Study Hub toggle — labeled pill so new users know what's inside */}
                        <button
                            onClick={() => {
                                const next = rightTab ? null : 'map';
                                setRightTab(next);
                                if (next && !studyHubSeen) {
                                    setStudyHubSeen(true);
                                    localStorage.setItem('ag_studyhub_seen', '1');
                                }
                            }}
                            title="Study Hub — Knowledge Map, Practice Quizzes & Doubts Log"
                            style={{
                                height: 32,
                                borderRadius: 8,
                                border: rightTab ? '1px solid var(--ag-purple)' : '1px solid var(--border)',
                                background: rightTab ? 'var(--ag-purple)' : 'var(--surface)',
                                color: rightTab ? '#fff' : 'var(--ag-purple)',
                                cursor: 'pointer',
                                display: 'flex',
                                flexDirection: 'column',
                                alignItems: 'center',
                                justifyContent: 'center',
                                padding: '0 11px',
                                transition: 'all 0.15s',
                                flexShrink: 0,
                                position: 'relative',
                                whiteSpace: 'nowrap',
                                animation: (!rightTab && !studyHubSeen) ? 'studyhub-pulse 2s ease-in-out infinite' : 'none',
                            }}
                        >
                            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                                <GraduationCap size={13} />
                                <span style={{ fontSize: 12, fontWeight: 700, lineHeight: 1 }}>
                                    {rightTab ? 'Close Hub' : 'Study Hub'}
                                </span>
                                {doubtsLog.length > 0 && !rightTab && (
                                    <span style={{ background: 'var(--ag-purple)', color: '#fff', borderRadius: 8, padding: '1px 6px', fontSize: 9, fontWeight: 700, lineHeight: 1.4 }}>
                                        {doubtsLog.length}
                                    </span>
                                )}
                            </div>
                            {!rightTab && (
                                <div style={{ fontSize: 8, fontWeight: 500, color: 'var(--text3)', letterSpacing: '0.02em', lineHeight: 1, marginTop: 2 }}>
                                    map · quizzes · doubts
                                </div>
                            )}
                        </button>
                        <button
                            onClick={() => setShowTopToolbar(v => !v)}
                            title={showTopToolbar ? 'Hide toolbar' : 'Show toolbar'}
                            style={{
                                width: 32,
                                height: 32,
                                borderRadius: 7,
                                border: '1px solid var(--border)',
                                background: 'transparent',
                                color: 'var(--text2)',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                transition: 'all 0.15s',
                                flexShrink: 0,
                            }}
                        >
                            {showTopToolbar ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        </button>
                    </>)}
                </div>
            </header>

            {/* ── Row 2: Tools toolbar ─────────────────────────────────────── */}
            {hasNote && (
                <div className="no-print" style={{ background: 'var(--surface)', borderBottom: showTopToolbar ? '1px solid var(--border)' : 'none', height: showTopToolbar ? 40 : 0, display: 'flex', alignItems: 'center', padding: showTopToolbar ? '0 14px' : '0 14px', gap: 6, flexShrink: 0, overflowX: 'auto', overflowY: 'hidden', opacity: showTopToolbar ? 1 : 0, pointerEvents: showTopToolbar ? 'auto' : 'none', transition: 'height 0.18s ease, opacity 0.12s ease, border-color 0.18s ease' }}>

                    {/* View mode */}
                    <div style={{ display: 'flex', gap: 1, background: 'var(--bg)', padding: 2, borderRadius: 6, border: '1px solid var(--border)', flexShrink: 0 }}>
                        {[['single', <BookOpen size={12} />, 'Single page'], ['two', <Columns2 size={12} />, 'Two pages'], ['scroll', <ScrollText size={12} />, 'Scroll']].map(([mode, icon, title]) => (
                            <button key={mode} title={title} onClick={() => setViewMode(mode)}
                                style={{ padding: '3px 7px', borderRadius: 4, border: 'none', cursor: 'pointer', background: viewMode === mode ? 'var(--ag-purple)' : 'transparent', color: viewMode === mode ? '#fff' : 'var(--text3)', display: 'flex', alignItems: 'center', transition: 'all 0.15s', height: 24 }}>{icon}</button>
                        ))}
                    </div>

                    {/* Font size */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 1, background: 'var(--bg)', borderRadius: 6, border: '1px solid var(--border)', flexShrink: 0, height: 26, padding: '0 2px' }}>
                        <button onClick={() => setFontSize(f => Math.max(12, f - 1))} title="Decrease font size"
                            style={{ padding: '0 6px', fontSize: 10, fontWeight: 700, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text2)', height: '100%' }}>A−</button>
                        <span style={{ fontSize: 10, color: 'var(--text3)', minWidth: 24, textAlign: 'center', fontFamily: 'Inter,sans-serif' }}>{fontSize}</span>
                        <button onClick={() => setFontSize(f => Math.min(24, f + 1))} title="Increase font size"
                            style={{ padding: '0 6px', fontSize: 12, fontWeight: 700, background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text2)', height: '100%' }}>A+</button>
                    </div>

                    {/* Search */}
                    <button onClick={() => setShowSearch(true)} title="Search (Ctrl+F)"
                        style={{ padding: '0 8px', height: 26, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text2)', cursor: 'pointer', display: 'flex', alignItems: 'center', flexShrink: 0 }}>
                        <Search size={13} />
                    </button>

                    <div style={{ width: 1, height: 20, background: 'var(--border)', flexShrink: 0 }} />

                    {/* Export */}
                    <CopyNoteButton note={note} />
                    <DownloadNoteButton note={note} name={notebook.name} />
                    <PrintNoteButton onPrint={handlePrint} />

                    <div style={{ width: 1, height: 20, background: 'var(--border)', flexShrink: 0 }} />

                    {/* Annotation toolbar */}
                    <AnnotationToolbar
                        activeTool={activeTool}
                        setActiveTool={setActiveTool}
                        highlightColor={highlightColor}
                        setHighlightColor={setHighlightColor}
                        drawingColor={drawingColor}
                        setDrawingColor={setDrawingColor}
                        autoSave={autoSave}
                        setAutoSave={setAutoSave}
                        onClearAll={clearAllAnnotations}
                        onSaveNow={saveAllToBackend}
                        annotationCount={annotations.length}
                    />

                    {/* Exit pill — only shown when a tool is active */}
                    {activeTool && (
                        <button
                            onClick={() => setActiveTool(null)}
                            title="Exit annotation mode (Esc)"
                            style={{
                                display: 'inline-flex', alignItems: 'center', gap: 4,
                                padding: '0 10px', height: 26, borderRadius: 6,
                                border: '1px solid #C4B5FD',
                                background: 'var(--ag-purple-bg)',
                                color: 'var(--ag-purple)',
                                cursor: 'pointer', fontSize: 11, fontWeight: 700,
                                flexShrink: 0, whiteSpace: 'nowrap',
                                animation: 'slideUpFade 0.15s ease',
                            }}
                        >
                            ✕ Exit {activeTool === 'highlight' ? 'Highlight' : activeTool === 'sticky' ? 'Sticky' : activeTool === 'drawing' ? 'Draw' : 'Eraser'}
                        </button>
                    )}

                    <div style={{ width: 1, height: 20, background: 'var(--border)', flexShrink: 0 }} />

                    {/* Spacer — pushes utility buttons to the right */}
                    <div style={{ flex: 1 }} />

                    {/* Utility — right-aligned */}
                    <StudyTimer />
                    <button onClick={() => setShowShortcuts(true)} title="Keyboard shortcuts (?)"
                        style={{ padding: '0 8px', height: 26, borderRadius: 6, border: '1px solid transparent', background: 'transparent', color: 'var(--text2)', cursor: 'pointer', display: 'flex', alignItems: 'center', flexShrink: 0 }}>
                        <Keyboard size={13} />
                    </button>
                    {hasNote && (
                        <button onClick={() => setShowShortNotes(true)} title="Quick Review Cheatsheet — AI summary of your notes"
                            style={{ padding: '0 8px', height: 26, borderRadius: 6, border: '1px solid var(--ag-purple-border)', background: 'var(--ag-purple-bg)', color: 'var(--ag-purple)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0, fontSize: 11, fontWeight: 700 }}>
                            <Zap size={11} /> Quick Review
                        </button>
                    )}
                    <button onClick={() => setShowVirtualKeyboard(v => !v)} title="Toggle on-screen keyboard"
                        style={{ padding: '0 8px', height: 26, borderRadius: 6, border: showVirtualKeyboard ? '1px solid var(--ag-purple-border)' : '1px solid transparent', background: showVirtualKeyboard ? 'var(--ag-purple-bg)' : 'transparent', color: showVirtualKeyboard ? 'var(--ag-purple)' : 'var(--text2)', cursor: 'pointer', display: 'flex', alignItems: 'center', flexShrink: 0 }}>
                        <Keyboard size={13} />
                    </button>
                    <button onClick={toggleFullscreen} title={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
                        style={{ padding: '0 8px', height: 26, borderRadius: 6, border: '1px solid transparent', background: 'transparent', color: 'var(--text2)', cursor: 'pointer', display: 'flex', alignItems: 'center', flexShrink: 0 }}>
                        {isFullscreen ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
                    </button>
                    <button onClick={() => setDarkMode(d => !d)} title="Toggle dark mode"
                        style={{ padding: '0 8px', height: 26, borderRadius: 6, border: '1px solid transparent', background: 'transparent', color: 'var(--text2)', cursor: 'pointer', display: 'flex', alignItems: 'center', flexShrink: 0 }}>
                        {darkMode ? <Sun size={13} /> : <Moon size={13} />}
                    </button>
                </div>
            )}

            {/* ── Dropdown panels: Concept Map / Doubts ─────────────────── */}
            {hasNote && rightTab && (
                <div style={{
                    position: 'absolute', top: showTopToolbar ? 96 : 56, right: 0, bottom: 0, zIndex: 120,
                    width: sidebarWidth,
                    maxWidth: 'min(440px, calc(100vw - 520px))',
                    background: 'var(--bg)',
                    borderLeft: '1px solid var(--border)',
                    boxShadow: '0 10px 28px rgba(0,0,0,0.12)',
                    display: 'flex', flexDirection: 'column',
                    animation: 'slideUpFade 0.16s ease',
                    overflow: 'hidden',
                }}>
                    <div
                        onMouseDown={startResizeSidebar}
                        title="Drag to resize"
                        style={{
                            position: 'absolute',
                            left: -4,
                            top: 0,
                            bottom: 0,
                            width: 8,
                            cursor: 'col-resize',
                            zIndex: 2,
                        }}
                    />
                    {/* Panel tab bar */}
                    <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', flexShrink: 0, padding: '0 8px', background: 'var(--surface)', gap: 4 }}>
                        {[
                            { key: 'map',    label: 'Knowledge Map', sublabel: 'graph · quizzes', icon: <Network size={13} /> },
                            { key: 'doubts', label: 'Doubts', sublabel: doubtsLog.length ? `${doubtsLog.length} logged` : 'ask anything', icon: <MessageSquare size={13} /> },
                        ].map(tab => (
                            <button key={tab.key} onClick={() => setRightTab(tab.key)}
                                style={{
                                    flex: 1, padding: '10px 8px 9px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                                    gap: 2, cursor: 'pointer', border: 'none', background: 'transparent',
                                    borderBottom: rightTab === tab.key ? '2px solid var(--ag-purple)' : '2px solid transparent',
                                    transition: 'all 0.15s',
                                }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 5, color: rightTab === tab.key ? 'var(--ag-purple)' : 'var(--text3)' }}>
                                    {tab.icon}
                                    <span style={{ fontSize: 12, fontWeight: 700 }}>{tab.label}</span>
                                </div>
                                <span style={{ fontSize: 9, color: rightTab === tab.key ? 'var(--ag-purple)' : 'var(--text3)', opacity: 0.75, fontWeight: 500 }}>{tab.sublabel}</span>
                            </button>
                        ))}
                    </div>
                    {/* Panel content */}
                    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                        {rightTab === 'map'
                            ? <KnowledgePanel nodes={graphNodes} edges={graphEdges} notebookId={id} onNodeStatusChange={handleNodeStatusChange} onJumpToSection={handleJumpToSection} onQuizCompleted={awardQuizCompletion} darkMode={darkMode} currentPageContent={pages[currentPage] || ''} />
                            : <DoubtsPanel doubts={doubtsLog} currentPage={currentPage} darkMode={darkMode} />}
                    </div>
                </div>
            )}

            {/* Body */}
            <div data-print-body style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
                {!hasNote ? (
                    <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-start', padding: '22px 24px 40px', scrollBehavior: 'smooth', WebkitOverflowScrolling: 'touch', overscrollBehavior: 'contain' }}>
                        <div style={{ maxWidth: 760, width: '100%' }}>
                            <div style={{ textAlign: 'center', marginBottom: 36 }}>
                                <div style={{ display: 'inline-block', background: '#fff', borderRadius: 12, padding: '8px 18px', margin: '0 auto 14px', border: '1px solid var(--border)' }}><img src="/logo.jpeg" alt="AuraGraph" style={{ height: 44, width: 'auto', display: 'block' }} /></div>
                                <h2 style={{ fontSize: 22, fontWeight: 800, marginBottom: 6 }}>Generate Fused Notes</h2>
                                <p style={{ fontSize: 14, color: 'var(--text3)', lineHeight: 1.7 }}>Upload your course materials and AuraGraph will generate a personalised digital study note calibrated to your level.</p>
                            </div>
                            <FuseProgressBar active={fusing} forceStep={verifyingStep} />
                            {!fusing && (<>
                                <div style={{ marginBottom: 24 }}>
                                    <SourceInputPanel
                                        slidesFiles={slidesFiles} setSlidesFiles={setSlidesFiles}
                                        notesFiles={notesFiles} setNotesFiles={setNotesFiles}
                                        textbookFiles={textbookFiles} setTextbookFiles={setTextbookFiles}
                                        mediaChunks={mediaChunks} setMediaChunks={setMediaChunks}
                                        mediaSourceDesc={mediaSourceDesc} setMediaSourceDesc={setMediaSourceDesc}
                                        notebookId={id}
                                    />
                                </div>
                                <div style={{ marginBottom: 24 }}>
                                    <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: 'var(--text2)', marginBottom: 10 }}>Proficiency Level</label>
                                    <div style={{ display: 'flex', gap: 10 }}>
                                        {[['Foundations', 'Concepts first — analogies & plain English'], ['Practitioner', 'Balanced depth — formulas with intuition'], ['Expert', 'Full rigour — derivations & edge cases']].map(([p, d]) => (
                                            <button key={p} onClick={() => setProf(p)} style={{ flex: 1, padding: '10px 8px', borderRadius: 8, cursor: 'pointer', border: `1px solid ${prof === p ? 'var(--ag-purple)' : 'var(--border)'}`, background: prof === p ? 'var(--ag-purple)' : 'var(--bg)', color: prof === p ? '#fff' : 'var(--text2)', textAlign: 'center', transition: 'all 0.15s' }}>
                                                <div style={{ fontWeight: 700, fontSize: 13 }}>{p}</div>
                                                <div style={{ fontSize: 11, marginTop: 2, opacity: 0.7 }}>{d}</div>
                                            </button>
                                        ))}
                                    </div>
                                </div>
                                <button data-testid="generate-notes-btn" className="btn btn-primary btn-lg" style={{ width: '100%', gap: 8 }} onClick={handleFuse}
                                    disabled={fusing || (!slidesFiles.length && !notesFiles.length && !mediaChunks.length)}>
                                    <Sparkles size={16} /> Generate Digital Notes
                                </button>
                                {(!slidesFiles.length && !notesFiles.length && !mediaChunks.length) && (
                                    <p style={{ textAlign: 'center', fontSize: 12, color: 'var(--text3)', marginTop: 10 }}>
                                        ↑ Upload at least one file above to enable generation
                                    </p>
                                )}
                            </>)}
                        </div>
                    </div>
                ) : (
                    <div ref={noteScrollRef} onMouseUp={handleNoteMouseUp} data-print-scroll className={activeTheme === 'midnight' ? 'note-theme-midnight' : ''} style={{ flex: 1, overflowY: 'auto', background: viewerTheme.scrollBg, paddingTop: 28, paddingBottom: 28, paddingLeft: viewMode === 'two' ? 16 : 24, paddingRight: rightTab ? `min(${sidebarWidth + 12}px, calc(100vw - 520px))` : (viewMode === 'two' ? 16 : 24), display: 'flex', flexDirection: 'column', alignItems: 'center', cursor: activeTool === 'highlight' ? 'text' : activeTool === 'sticky' ? 'cell' : activeTool === 'drawing' ? 'crosshair' : activeTool === 'eraser' ? 'cell' : 'default', transition: 'padding-right 0.2s ease' }}>
                        {(() => {
                            const onDoubtLink = (doubtId) => { setRightTab('doubts'); setTimeout(() => { document.getElementById(doubtId)?.scrollIntoView({ behavior: 'smooth', block: 'center' }); }, 300); };
                            const renderPage = (idx) => {
                                if (idx < 0 || idx >= pages.length) return <div key={`empty-${idx}`} style={{ flex: 1, minWidth: 0 }} />;
                                const isHighlighted = jumpHighlightSet.has(idx);
                                const cardRef = getPageCardRef(idx);
                                const pageAnns = getPageAnnotations(idx);
                                return (
                                    <div key={idx} className="note-page-card" ref={cardRef} style={{ display: 'flex', background: viewerTheme.cardBg, borderRadius: 6, boxShadow: isHighlighted ? '0 0 0 3px #7C3AED, 0 2px 12px rgba(124,58,237,0.12), 0 16px 48px rgba(0,0,0,0.10)' : '0 2px 8px rgba(0,0,0,0.06), 0 8px 24px rgba(124,58,237,0.06), 0 20px 64px rgba(0,0,0,0.09)', border: isHighlighted ? '1px solid #7C3AED' : `1px solid ${viewerTheme.cardBorder}`, overflow: 'visible', flex: 1, minWidth: 0, transition: 'box-shadow 0.4s, border-color 0.4s', position: 'relative' }}>
                                        <div className="note-binder-rings" style={{ width: 40, background: viewerTheme.rings, borderRight: `2px solid ${viewerTheme.ringBorder}`, flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'space-evenly', padding: '32px 0', alignSelf: 'stretch', minHeight: 560 }}>
                                            {[0, 1, 2, 3, 4, 5].map(i => <div key={i} style={{ width: 16, height: 16, borderRadius: '50%', background: viewerTheme.cardBg, border: `2px solid ${viewerTheme.ringDot}`, boxShadow: 'inset 0 1px 3px rgba(124,58,237,0.18), 0 1px 2px rgba(124,58,237,0.12)' }} />)}
                                        </div>
                                        <div className="note-margin-line" style={{ width: 1.5, background: viewerTheme.marginLine, flexShrink: 0 }} />
                                        <div style={{ flex: 1, padding: '40px 48px 48px 36px', minWidth: 0, overflowX: 'hidden' }}>
                                            <div className="note-header-bar" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 28, paddingBottom: 10, borderBottom: '1px solid #DDD6FE' }}>
                                                <span style={{ fontSize: 11, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'Inter,sans-serif' }}>{notebook?.name || 'Study Notes'}</span>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                                    {isPageMutated(idx) && <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 20, background: 'var(--ag-purple-soft)', color: 'var(--ag-purple)', border: '1px solid #C4B5FD', letterSpacing: '0.05em' }}>⚡ Mutated</span>}
                                                    <span style={{ fontSize: 11, color: '#9CA3AF', fontFamily: 'Inter,sans-serif' }}>Page {idx + 1} of {pages.length}</span>
                                                    <button
                                                        onClick={() => setRegenPromptState({ open: true, pageIdx: idx, prompt: '' })}
                                                        disabled={regenLoadingPages.has(idx)}
                                                        title="Re-generate this section with fresh AI output"
                                                        className="no-print"
                                                        style={{ background: 'none', border: '1px solid #E5E7EB', borderRadius: 6, padding: '3px 8px', cursor: regenLoadingPages.has(idx) ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, fontWeight: 600, color: '#9CA3AF', transition: 'all 0.15s' }}
                                                        onMouseEnter={e => { if (!regenLoadingPages.has(idx)) { e.currentTarget.style.borderColor = 'var(--ag-purple)'; e.currentTarget.style.color = 'var(--ag-purple)'; } }}
                                                        onMouseLeave={e => { e.currentTarget.style.borderColor = '#E5E7EB'; e.currentTarget.style.color = '#9CA3AF'; }}
                                                    >
                                                        {regenLoadingPages.has(idx)
                                                            ? <><Loader2 size={10} className="spin" /> Regenerating…</>
                                                            : <><RefreshCw size={10} /> Regenerate</>}
                                                    </button>
                                                    {/* TTS — Listen button */}
                                                    <button
                                                        className="no-print"
                                                        onClick={() => tts.speak(pages[idx], idx)}
                                                        title={tts.isLoading && tts.activePageIdx === idx ? 'Loading…' : tts.isPlaying && tts.activePageIdx === idx ? 'Pause reading' : 'Read this page aloud'}
                                                        style={{ background: tts.activePageIdx === idx ? 'var(--ag-purple-bg)' : 'none', border: `1px solid ${tts.activePageIdx === idx ? 'var(--ag-purple-border)' : '#E5E7EB'}`, borderRadius: 6, padding: '3px 8px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, fontWeight: 600, color: tts.activePageIdx === idx ? 'var(--ag-purple)' : '#9CA3AF', transition: 'all 0.15s' }}
                                                        onMouseEnter={e => { if (tts.activePageIdx !== idx) { e.currentTarget.style.borderColor = 'var(--ag-purple)'; e.currentTarget.style.color = 'var(--ag-purple)'; } }}
                                                        onMouseLeave={e => { if (tts.activePageIdx !== idx) { e.currentTarget.style.borderColor = '#E5E7EB'; e.currentTarget.style.color = '#9CA3AF'; } }}
                                                    >
                                                        {tts.isLoading && tts.activePageIdx === idx ? <Loader2 size={10} className="spin" /> : <Volume2 size={10} />}
                                                        {tts.isPlaying && tts.activePageIdx === idx ? 'Pause' : tts.isLoading && tts.activePageIdx === idx ? 'Loading…' : 'Listen'}
                                                    </button>
                                                    {/* Translate button */}
                                                    <button
                                                        className="no-print"
                                                        onClick={() => { setTranslatePageIdx(idx); setShowTranslate(true); }}
                                                        title="Translate this page"
                                                        style={{ background: 'none', border: '1px solid #E5E7EB', borderRadius: 6, padding: '3px 8px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, fontWeight: 600, color: '#9CA3AF', transition: 'all 0.15s' }}
                                                        onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--ag-purple)'; e.currentTarget.style.color = 'var(--ag-purple)'; }}
                                                        onMouseLeave={e => { e.currentTarget.style.borderColor = '#E5E7EB'; e.currentTarget.style.color = '#9CA3AF'; }}
                                                    >
                                                        <Languages size={10} /> Translate
                                                    </button>
                                                </div>
                                            </div>
                                            <NoteRenderer content={pages[idx]} onDoubtLink={onDoubtLink} fontSize={fontSize} darkMode={darkMode} />
                                            <div className="note-footer-bar" style={{ marginTop: 36, paddingTop: 10, borderTop: '1px solid #DDD6FE', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                <span style={{ fontSize: 10, color: '#9CA3AF', fontFamily: 'Inter,sans-serif' }}>{notebook?.course || ''}</span>
                                                <span style={{ fontSize: 10, color: '#9CA3AF', fontFamily: 'Inter,sans-serif' }}>AuraGraph · {prof}</span>
                                            </div>
                                        </div>
                                        {/* Annotation overlay — highlights, stickies, drawings */}
                                        <AnnotationLayer
                                            containerRef={cardRef}
                                            annotations={pageAnns}
                                            activeTool={activeTool}
                                            highlightColor={highlightColor}
                                            drawingColor={drawingColor}
                                            pageIdx={idx}
                                            onAdd={addAnnotation}
                                            onUpdate={updateAnnotation}
                                            onDelete={deleteAnnotation}
                                        />
                                    </div>
                                );
                            };
                            const banners = (
                                <>
                                    {fallbackWarning && (
                                        <div style={{ marginBottom: 14, padding: '10px 14px', background: '#FEF3C7', border: '1px solid #FDE68A', borderRadius: 8, fontSize: 12, color: '#92400E', display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                                            <span style={{ flexShrink: 0 }}>⚠️</span>
                                            <div style={{ flex: 1 }}><b>Offline notes:</b> {fallbackWarning.replace(/^⚠️\s*/, '')}</div>
                                            <button onClick={() => setFallbackWarning('')} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#92400E', padding: 0, marginLeft: 'auto', flexShrink: 0 }}><X size={13} /></button>
                                        </div>
                                    )}

                                </>
                            );
                            const bottomBar = (
                                <div style={{ marginTop: 16, display: 'flex', justifyContent: 'center', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                                    <button data-testid="re-upload-btn" className="btn btn-ghost btn-sm" style={{ fontSize: 12 }} onClick={() => setNote('')}><Upload size={12} /> Re-upload materials</button>
                                    <button className="btn btn-ghost btn-sm" style={{ fontSize: 12 }} onClick={() => extractAndSaveGraph(note)}><RefreshCw size={12} /> Refresh Concept Map</button>
                                    <button className="btn btn-ghost btn-sm" style={{ fontSize: 12, borderColor: 'var(--ag-purple-border)', color: 'var(--ag-purple)', background: 'var(--ag-purple-bg)' }} onClick={() => setShowShortNotes(true)}><Zap size={12} /> Quick Review</button>
                                    {viewMode !== 'scroll' && (
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
                                            {pages.slice(0, Math.min(pages.length, 20)).map((_, i) => (
                                                <button key={i} className="page-dot" data-label={`Page ${i + 1}`} onClick={() => setCurrentPage(i)} title={`Page ${i + 1}`} style={{ width: i === currentPage ? 20 : 6, height: 6, borderRadius: 3, border: 'none', cursor: 'pointer', background: i === currentPage ? 'var(--ag-purple)' : isPageMutated(i) ? 'var(--ag-ring-left)' : 'var(--border2)', transition: 'all 0.2s', padding: 0 }} />
                                            ))}
                                            {pages.length > 20 && <span style={{ fontSize: 10, color: 'var(--text3)' }}>+{pages.length - 20}</span>}
                                        </div>
                                    )}
                                </div>
                            );
                            if (viewMode === 'scroll') return (
                                <div style={{ maxWidth: 760, width: '100%' }}>
                                    {banners}
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
                                        {pages.map((_, idx) => renderPage(idx))}
                                    </div>
                                    {bottomBar}
                                </div>
                            );
                            if (viewMode === 'two') {
                                const hasRight = currentPage + 1 < pages.length;
                                return (
                                    <div style={{ maxWidth: 1480, width: '100%' }}>
                                        {banners}
                                        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
                                            {renderPage(currentPage)}
                                            {hasRight ? renderPage(currentPage + 1) : <div style={{ flex: 1, minWidth: 0 }} />}
                                        </div>
                                        {bottomBar}
                                    </div>
                                );
                            }
                            return (
                                <div style={{ maxWidth: 760, width: '100%' }}>
                                    {banners}
                                    {renderPage(currentPage)}
                                    {bottomBar}
                                </div>
                            );
                        })()}
                    </div>
                )}

            </div>

            {textSelection && (
                <div style={{ position: 'fixed', left: textSelection.x, top: textSelection.y - 8, transform: 'translateX(-50%) translateY(-100%)', zIndex: 9999, background: '#1E1B4B', borderRadius: 8, padding: '6px 10px', display: 'flex', gap: 6, boxShadow: '0 4px 24px rgba(0,0,0,0.35)', alignItems: 'center', pointerEvents: 'auto' }}>
                    <span style={{ color: '#A5B4FC', fontSize: 10, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{textSelection.text.length > 35 ? textSelection.text.slice(0, 35) + '…' : textSelection.text}</span>
                    {textSelection.pendingHighlight && (
                        <button onClick={() => {
                            const { selectedText, contextBefore } = textSelection.pendingHighlight;
                            addAnnotation({
                                id: Math.random().toString(36).slice(2) + Date.now().toString(36),
                                page_idx: currentPage,
                                type: 'highlight',
                                data: { selectedText, contextBefore, contextAfter: '', color: highlightColor },
                                created_at: new Date().toISOString(),
                            });
                            awardAura('highlight');
                            // Track highlight behaviour (fire-and-forget)
                            fetch('/api/behaviour/track-highlight', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('ag_token') || ''}` },
                                body: JSON.stringify({ notebook_id: id, text: selectedText, page_idx: currentPage }),
                            }).catch(() => {});
                            setTextSelection(null);
                        }} style={{ background: highlightColor, border: 'none', color: '#1C1917', borderRadius: 6, padding: '4px 10px', fontSize: 11, fontWeight: 700, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4 }}>
                            🖍 Highlight
                        </button>
                    )}
                    <button onClick={() => { setPendingSelectionText(textSelection.text); setTextSelection(null); setMutating(true); }} style={{ background: 'var(--ag-purple)', border: 'none', color: '#fff', borderRadius: 6, padding: '4px 10px', fontSize: 11, fontWeight: 600, cursor: 'pointer' }}>Ask about this</button>
                    <button onClick={() => setTextSelection(null)} style={{ background: 'none', border: '1px solid #4C1D95', color: '#A5B4FC', borderRadius: 5, padding: '3px 7px', fontSize: 11, cursor: 'pointer' }}>✕</button>
                </div>
            )}
            {undoToast && <UndoToast toast={undoToast} onUndo={handleUndoCommit} onDismiss={dismissUndo} />}
            {showAuraPanel && <AuraPanel aura={aura} onClose={() => setShowAuraPanel(false)} darkMode={darkMode} />}
            {xpToast && <XPToast gained={xpToast.gained} onDone={() => setXpToast(null)} />}
            {badgeToast && <BadgeLevelUpToast badge={badgeToast} onDone={() => setBadgeToast(null)} />}

            {/* ── Dedicated print container — hidden on screen, visible in @media print ── */}
            {printablePages.length > 0 && (
                <div id="ag-print-root">
                    {printablePages.map((pageContent, idx) => (
                        <div key={idx} className="ag-print-page">
                            <div style={{ fontSize: 10, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'Inter,sans-serif', marginBottom: 16, paddingBottom: 10, borderBottom: '1px solid #E5E7EB', display: 'flex', justifyContent: 'space-between' }}>
                                <span>{notebook?.name || 'Study Notes'}</span>
                                <span>Page {idx + 1} of {printablePages.length} · AuraGraph · {prof}</span>
                            </div>
                            <NoteRenderer content={pageContent} fontSize={fontSize} darkMode={darkMode} />
                        </div>
                    ))}
                </div>
            )}

            {regenPromptState.open && (
                <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999, padding: 24 }} onClick={() => setRegenPromptState(s => ({ ...s, open: false }))}>
                    <div style={{ background: 'var(--bg)', borderRadius: 14, padding: 24, maxWidth: 480, width: '100%', boxShadow: '0 24px 80px rgba(0,0,0,0.3)', border: '1px solid var(--border)' }} onClick={e => e.stopPropagation()}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
                            <RefreshCw size={16} color="var(--ag-purple)" />
                            <span style={{ fontWeight: 700, fontSize: 15 }}>Regenerate page {regenPromptState.pageIdx != null ? regenPromptState.pageIdx + 1 : ''}</span>
                            <button onClick={() => setRegenPromptState(s => ({ ...s, open: false }))} style={{ marginLeft: 'auto', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', padding: 4 }}><X size={16} /></button>
                        </div>
                        <p style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 12, lineHeight: 1.6 }}>
                            Optionally guide the AI — leave blank for a standard regeneration.
                        </p>
                        <textarea
                            rows={3}
                            placeholder="e.g. Focus more on worked examples, avoid heavy notation…"
                            value={regenPromptState.prompt}
                            onChange={e => setRegenPromptState(s => ({ ...s, prompt: e.target.value }))}
                            style={{ width: '100%', borderRadius: 8, border: '1px solid var(--border)', padding: '9px 12px', fontSize: 13, resize: 'vertical', background: 'var(--surface)', color: 'var(--text)', outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box', marginBottom: 10 }}
                            autoFocus
                            maxLength={400}
                        />
                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 16 }}>
                            {['More examples', 'Simpler language', 'More rigour', 'Focus on formulas', 'Add intuition'].map(chip => (
                                <button key={chip}
                                    onClick={() => setRegenPromptState(s => ({ ...s, prompt: s.prompt ? s.prompt + ', ' + chip.toLowerCase() : chip }))}
                                    style={{ fontSize: 11, padding: '3px 10px', borderRadius: 20, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text2)', cursor: 'pointer', transition: 'all 0.15s' }}
                                    onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--ag-purple)'; e.currentTarget.style.color = 'var(--ag-purple)'; }}
                                    onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text2)'; }}
                                >{chip}</button>
                            ))}
                        </div>
                        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                            <button onClick={() => setRegenPromptState(s => ({ ...s, open: false }))} className="btn btn-ghost btn-sm">Cancel</button>
                            <button
                                onClick={() => {
                                    const { pageIdx, prompt } = regenPromptState;
                                    setRegenPromptState({ open: false, pageIdx: null, prompt: '' });
                                    handleRegenSection(pageIdx, prompt);
                                }}
                                className="btn btn-primary btn-sm"
                                style={{ gap: 5 }}
                            >
                                <RefreshCw size={12} /> Regenerate
                            </button>
                        </div>
                    </div>
                </div>
            )}
            {mutating && pages.length > 0 && <MutateModal page={pages[currentPage]} notebookId={id} pageIdx={currentPage} onClose={() => { setMutating(false); setPendingSelectionText(''); }} onMutate={handleMutate} onDoubtAnswered={({ doubt: q, answer: a, source: s }) => { const entry = { id: Date.now(), pageIdx: currentPage, doubt: q, insight: a, gap: '', source: s || 'azure', time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), success: true, kind: 'answered' }; setDoubtsLog(prev => [entry, ...prev]); awardAura('doubt'); setRightTab('doubts'); }} initialDoubt={pendingSelectionText} darkMode={darkMode} />}
            {showSearch && pages.length > 0 && <NoteSearch pages={pages} onJumpToPage={(idx, query) => { setCurrentPage(idx); setSearchHighlight(query || ''); }} onClose={() => setShowSearch(false)} />}
            {showVirtualKeyboard && <VirtualKeyboard onClose={() => setShowVirtualKeyboard(false)} />}
            {(tts.isPlaying || tts.isLoading) && (
                <AudioPlayer
                    tts={tts}
                    pageLabel={tts.activePageIdx !== null ? `Page ${tts.activePageIdx + 1}` : 'Note'}
                    onClose={tts.stop}
                />
            )}
            {showTranslate && translatePageIdx !== null && (
                <TranslateModal
                    originalText={pages[translatePageIdx] || ''}
                    onClose={() => setShowTranslate(false)}
                    onSpeak={(text, voice) => { tts.setVoice(voice); tts.speak(text, translatePageIdx); setShowTranslate(false); }}
                    ttsVoices={tts.voices}
                />
            )}
            {showShortNotes && <ShortNotesModal notebookId={id} notebookName={notebook?.name} proficiency={prof} onClose={() => setShowShortNotes(false)} darkMode={darkMode} />}
            <FeedbackWidget mode="notebook" notebookId={id} darkMode={darkMode} />
            {showShortcuts && <ShortcutsModal onClose={() => setShowShortcuts(false)} />}
        </div>
    );
}
