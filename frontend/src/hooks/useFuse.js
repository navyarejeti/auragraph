import { useState, useCallback } from 'react';
import { useDispatch } from 'react-redux';
import { addToast } from '../store';
import { API, apiFetch, parseApiError } from '../components/utils';

/**
 * Manages the FUSE (file upload + note generation) workflow.
 * Handles file state, streaming SSE events, and progress feedback.
 *
 * @param {string} id - Notebook ID
 * @param {{ prof, setNote, setCurrentPage, setMutatedPages, saveNote, extractAndSaveGraph }} deps
 */
export function useFuse(id, deps = {}) {
    const { prof, setNote, setCurrentPage, setMutatedPages, saveNote, extractAndSaveGraph } = deps;
    const dispatch = useDispatch();

    const [slidesFiles, setSlidesFiles] = useState([]);
    const [textbookFiles, setTextbookFiles] = useState([]);
    const [notesFiles, setNotesFiles] = useState([]);
    const [mediaChunks, setMediaChunks] = useState([]);   // from media_ingest (transcript/video/audio)
    const [mediaSourceDesc, setMediaSourceDesc] = useState('');
    const [fusing, setFusing] = useState(false);
    const [fuseProgress, setFuseProgress] = useState('');
    const [verifyingStep, setVerifyingStep] = useState(null);
    const [noteSource, setNoteSource] = useState('azure');
    const [fallbackWarning, setFallbackWarning] = useState('');

    const handleFuse = useCallback(async () => {
        if (!slidesFiles.length && !notesFiles.length && !mediaChunks.length) return;
        setFusing(true);
        setFuseProgress('Uploading files…');
        setMutatedPages?.(new Set());
        setNote?.('');
        setCurrentPage?.(0);

        try {
            const form = new FormData();
            slidesFiles.forEach(f => form.append('slides_pdfs', f));
            notesFiles.forEach(f => form.append('slides_pdfs', f));
            textbookFiles.forEach(f => form.append('textbook_pdfs', f));
            form.append('proficiency', prof);
            if (mediaChunks.length > 0) {
                form.append('media_transcript_chunks', JSON.stringify(mediaChunks));
            }
            if (id) form.append('notebook_id', id);
            setFuseProgress('Running Fusion Agent…');

            // Abort the stream if no data arrives within 25 minutes
            const abortCtrl = new AbortController();
            const streamTimeout = setTimeout(() => abortCtrl.abort(), 25 * 60 * 1000);

            const res = await apiFetch(`${API}/api/upload-fuse-stream`, {
                method: 'POST',
                body: form,
                signal: abortCtrl.signal,
            });

            if (!res.ok) {
                clearTimeout(streamTimeout);
                let detail = `Server error (${res.status})`;
                try { const j = await res.json(); detail = parseApiError(j.detail, detail); } catch { }
                throw new Error(detail);
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let streamedNote = '';
            let streamSource = 'azure';
            let lastChunkAt = Date.now();
            let receivedDone = false;
            // Section slots: backend now emits in lecture order, but keep
            // an index-keyed map as a safety net for out-of-order arrivals.
            const sectionSlots = {};  // index → content
            let totalTopics = 0;

            const _rebuildNote = () => {
                // Reconstruct note from slots in index order, skipping gaps
                const filled = Object.entries(sectionSlots)
                    .sort((a, b) => Number(a[0]) - Number(b[0]))
                    .map(([, content]) => content);
                return filled.join('\n\n');
            };
            // Per-chunk stall detection: 4 min with no data → abort
            // (refinement + verification passes can be 2-3 min — heartbeats keep connection alive)
            const stallCheck = setInterval(() => {
                if (Date.now() - lastChunkAt > 240_000) {
                    abortCtrl.abort();
                    clearInterval(stallCheck);
                }
            }, 5_000);

            try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                lastChunkAt = Date.now();
                buffer += decoder.decode(value, { stream: true });
                const parts = buffer.split('\n\n');
                buffer = parts.pop();
                for (const part of parts) {
                    const line = part.trim();
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const event = JSON.parse(line.slice(6));
                        if (event.type === 'start') {
                            totalTopics = event.total;
                            setFuseProgress(`Generating ${event.total} topic sections…`);
                        } else if (event.type === 'status') {
                            setFuseProgress(event.message || 'Processing…');
                            if ((event.message || '').toLowerCase().includes('verif')) setVerifyingStep(5);
                        } else if (event.type === 'section') {
                            // Place section into its correct lecture-order slot
                            const idx = typeof event.index === 'number' ? event.index : Object.keys(sectionSlots).length;
                            sectionSlots[idx] = event.content;
                            // Rebuild note in correct order and show it live
                            streamedNote = _rebuildNote();
                            setNote?.(streamedNote);
                            setFuseProgress(`Building: ${event.topic}…`);
                        } else if (event.type === 'heartbeat') {
                            /* keep-alive ping during refine/verify — no UI change needed */
                        } else if (event.type === 'done') {
                            receivedDone = true;
                            setVerifyingStep(null);
                            streamedNote = event.note || streamedNote;
                            streamSource = event.source || 'azure';
                            setNote?.(streamedNote);
                            // Responsible AI: never surface correction summaries to the student.
                            // The notes are already correct — no need to say they were fixed.
                        }
                    } catch { /* ignore malformed SSE events */ }
                }
            }

            } finally {
                clearTimeout(streamTimeout);
                clearInterval(stallCheck);
            }

            // Safety net: if stream closed without a done event, show whatever was accumulated
            if (!receivedDone && streamedNote) {
                setNote?.(streamedNote);
                setVerifyingStep(null);
            }

            setNoteSource(streamSource);
            setFallbackWarning(streamSource === 'local'
                ? '⚠️ Azure OpenAI was unavailable — notes were generated using the offline summariser.'
                : '');
            await saveNote?.(streamedNote, prof);
            setFuseProgress('Extracting concept map…');
            await extractAndSaveGraph?.(streamedNote);
        } catch (err) {
            const message = err.name === 'AbortError'
                ? 'Generation timed out — the backend took too long to respond. Try again or use a smaller file.'
                : (err.message || '');
            const isNetworkError = !message || message === 'Failed to fetch' || message.includes('NetworkError');
            const isFileTooLarge = message.toLowerCase().includes('too large') || message.toLowerCase().includes('exceeds') || message.includes('413');
            const isAuth = message.includes('401') || message.includes('403') || message.toLowerCase().includes('unauthorized');
            const isTimeout = err.name === 'AbortError';
            const bannerMsg = isTimeout
                ? `⚠️ ${message}`
                : isNetworkError
                ? '⚠️ Backend unreachable — start the server: cd backend && source venv/bin/activate && uvicorn main:app --reload --port 8000'
                : isFileTooLarge
                    ? `⚠️ Upload too large — ${message}. Try splitting files across two notebooks or compressing large PDFs.`
                    : isAuth
                        ? '⚠️ Authentication failed — try logging out and back in.'
                        : `⚠️ Generation failed: ${message}`;
            setFallbackWarning(bannerMsg);
            // Also surface as a dismissible toast
            dispatch(addToast({
                kind: isAuth ? 'error' : isNetworkError ? 'warning' : 'error',
                title: isTimeout ? 'Request timed out' : isAuth ? 'Authentication error' : isNetworkError ? 'Backend unreachable' : 'Generation failed',
                message: isTimeout
                    ? message
                    : isNetworkError
                        ? 'Start the backend server and try again.'
                        : isAuth
                            ? 'Log out and log back in.'
                            : message || 'Unknown error',
                duration: isNetworkError ? 10000 : 7000,
            }));
        }
        setFusing(false);
        setFuseProgress('');
        setVerifyingStep(null);
    }, [id, prof, slidesFiles, textbookFiles, notesFiles, setNote, setCurrentPage, setMutatedPages, saveNote, extractAndSaveGraph]);

    return {
        slidesFiles, setSlidesFiles,
        textbookFiles, setTextbookFiles,
        notesFiles, setNotesFiles,
        mediaChunks, setMediaChunks,
        mediaSourceDesc, setMediaSourceDesc,
        fusing, setFusing,
        fuseProgress, setFuseProgress,
        verifyingStep, setVerifyingStep,
        noteSource, setNoteSource,
        fallbackWarning, setFallbackWarning,
        handleFuse,
    };
}
