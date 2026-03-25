/**
 * SourceInputPanel — Beautiful multi-source input for lecture materials.
 * 
 * Four source tabs:
 *   📄 Files      — PDF / PPTX / images (existing FileDrop behaviour)
 *   🎬 Video      — YouTube / Google Meet / Zoom / any URL
 *   🎤 Audio      — MP3 / M4A / WAV file upload
 *   📝 Transcript — Paste or upload .txt transcript
 * 
 * All non-file sources call /api/media-ingest first, then the result
 * is passed into the main fuse pipeline via mediaChunks state.
 */
import React, { useState, useRef, useCallback } from 'react';
import { FileText, BookOpen, PenLine, Link2, Mic, AlignLeft,
         Loader2, CheckCircle2, AlertCircle, X, Plus, Upload } from 'lucide-react';
import { API, authHeaders } from './utils';

const MAX_VIDEO_URLS = 8;
const MAX_AUDIO_FILES = 8;
const MAX_TRANSCRIPT_FILES = 8;

// ── Source tab definitions ────────────────────────────────────────────────────
const SOURCES = [
    { id: 'files',      icon: FileText,   label: 'Files',      color: '#7C3AED', bg: '#F5F3FF', border: '#DDD6FE', desc: 'PDF, PPTX, or images' },
    { id: 'video',      icon: Link2,      label: 'Video / URL',color: '#2563EB', bg: '#EFF6FF', border: '#BFDBFE', desc: 'YouTube, Meet, Zoom…' },
    { id: 'audio',      icon: Mic,        label: 'Audio',      color: '#0F766E', bg: '#F0FDF4', border: '#BBF7D0', desc: 'MP3, M4A, WAV…' },
    { id: 'transcript', icon: AlignLeft,  label: 'Transcript', color: '#D97706', bg: '#FFFBEB', border: '#FDE68A', desc: 'Paste or upload .txt' },
];

// ── Pill showing an ingested media source ─────────────────────────────────────
function SourcePill({ desc, onRemove, color, border, bg }) {
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', borderRadius: 20, background: bg, border: `1px solid ${border}`, fontSize: 11, fontWeight: 600, color }}>
            <CheckCircle2 size={11} />
            <span style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{desc}</span>
            <button onClick={onRemove} style={{ background: 'none', border: 'none', cursor: 'pointer', color, padding: 0, display: 'flex', lineHeight: 1, opacity: 0.7 }}>
                <X size={11} />
            </button>
        </div>
    );
}

// ── File section (existing 3-column layout) ───────────────────────────────────
function FileSection({ slidesFiles, setSlidesFiles, notesFiles, setNotesFiles, textbookFiles, setTextbookFiles }) {
    return (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
            <MiniFileDrop label="Professor's Slides" icon={BookOpen} color="#7C3AED"
                accept=".pdf,.pptx,.ppt,.jpg,.jpeg,.png,.webp"
                files={slidesFiles} onFiles={setSlidesFiles} />
            <MiniFileDrop label="Handwritten Notes" icon={PenLine} color="#2563EB"
                accept=".pdf,.jpg,.jpeg,.png,.webp"
                files={notesFiles} onFiles={setNotesFiles} />
            <MiniFileDrop label="Textbook / Reference" icon={FileText} color="#0F766E"
                accept=".pdf,.pptx,.ppt,.jpg,.jpeg,.png,.webp"
                files={textbookFiles} onFiles={setTextbookFiles} />
        </div>
    );
}

function MiniFileDrop({ label, icon: Icon, color, accept, files, onFiles }) {
    const ref = useRef();
    const [drag, setDrag] = useState(false);
    const hasFiles = files.length > 0;

    const addFiles = (incoming) => {
        const valid = Array.from(incoming);
        if (valid.length) onFiles(prev => [...prev, ...valid]);
    };

    return (
        <div
            onDragOver={e => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={e => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}
            style={{
                border: `2px dashed ${drag ? color : hasFiles ? color + '80' : 'var(--border2)'}`,
                borderRadius: 10, padding: '12px 14px',
                background: drag ? 'var(--surface2)' : hasFiles ? color + '08' : 'var(--surface)',
                transition: 'all 0.15s', cursor: 'pointer', minHeight: 110,
            }}
            onClick={() => !hasFiles && ref.current?.click()}
        >
            <input ref={ref} type="file" accept={accept} multiple
                style={{ display: 'none' }} onChange={e => addFiles(e.target.files)} />
            {!hasFiles ? (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', gap: 7, minHeight: 86 }}>
                    <div style={{ width: 36, height: 36, borderRadius: 10, background: color + '15', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <Icon size={18} color={color} />
                    </div>
                    <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)', textAlign: 'center' }}>{label}</div>
                    <div style={{ fontSize: 10, color: 'var(--text3)' }}>drag & drop or click</div>
                </div>
            ) : (
                <div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                        <span style={{ fontSize: 10, fontWeight: 700, color }}>
                            {files.length} file{files.length > 1 ? 's' : ''}
                        </span>
                        <button onClick={e => { e.stopPropagation(); ref.current?.click(); }}
                            style={{ fontSize: 10, color: 'var(--text3)', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', padding: 0 }}>
                            + Add
                        </button>
                    </div>
                    {files.slice(0, 3).map((f, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10, color: 'var(--text2)', marginBottom: 3 }}>
                            <span style={{ flexShrink: 0 }}>📄</span>
                            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</span>
                            <button onClick={e => { e.stopPropagation(); onFiles(prev => prev.filter((_, j) => j !== i)); }}
                                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', padding: 0, lineHeight: 1 }}>×</button>
                        </div>
                    ))}
                    {files.length > 3 && <div style={{ fontSize: 10, color: 'var(--text3)' }}>+{files.length - 3} more</div>}
                </div>
            )}
        </div>
    );
}

// ── Video URL section ─────────────────────────────────────────────────────────
function VideoSection({ onIngest, notebookId }) {
    const [url, setUrl] = useState('');
    const [urls, setUrls] = useState([]);
    const [status, setStatus] = useState('idle'); // idle | loading | ok | error
    const [message, setMessage] = useState('');
    const queuedCount = urls.length + (url.trim() ? 1 : 0);

    const addUrl = () => {
        const u = url.trim();
        if (!u) return;
        if (urls.length >= MAX_VIDEO_URLS) {
            setStatus('error');
            setMessage(`Max ${MAX_VIDEO_URLS} video links per batch.`);
            return;
        }
        if (urls.includes(u)) {
            setUrl('');
            return;
        }
        setUrls(prev => [...prev, u]);
        setUrl('');
        setStatus('idle');
    };

    const handleIngest = async () => {
        if (url.trim()) addUrl();
        const rawBatch = (url.trim() ? [...urls, url.trim()] : urls);
        const batch = Array.from(new Set(rawBatch)).slice(0, MAX_VIDEO_URLS);
        if (!batch.length) return;
        setStatus('loading');
        setMessage('Extracting transcripts from links…');
        try {
            const form = new FormData();
            batch.forEach(u => form.append('urls', u));
            if (notebookId) form.append('notebook_id', notebookId);
            const res = await fetch(`${API}/api/media-ingest`, {
                method: 'POST',
                headers: authHeaders(),
                body: form,
            });
            const data = await res.json();
            if (data.ok && data.chunks?.length > 0) {
                setStatus('ok');
                setMessage(`✓ ${data.chunks.length} segments extracted`);
                onIngest(data.chunks, `Video: ${batch.length} link(s)`);
                setUrls([]);
                setUrl('');
            } else {
                setStatus('error');
                setMessage(data.message || 'Could not extract transcript. Try pasting it manually.');
            }
        } catch {
            setStatus('error');
            setMessage('Network error. Check your connection.');
        }
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ fontSize: 12, color: 'var(--text3)', lineHeight: 1.6 }}>
                Paste a link to your class recording. AuraGraph will extract the transcript automatically.
            </div>
            <div style={{ display: 'flex', gap: 0, borderRadius: 10, overflow: 'hidden', border: '1.5px solid var(--border)', background: 'var(--bg)', transition: 'border-color 0.15s' }}
                onFocus={() => {}} >
                <div style={{ padding: '0 12px', display: 'flex', alignItems: 'center', borderRight: '1px solid var(--border)', background: 'var(--surface)' }}>
                    <Link2 size={14} color="var(--text3)" />
                </div>
                <input
                    value={url}
                    onChange={e => { setUrl(e.target.value); setStatus('idle'); }}
                    onKeyDown={e => e.key === 'Enter' && addUrl()}
                    placeholder="https://youtu.be/…  or  Google Meet / Zoom recording URL"
                    style={{ flex: 1, padding: '10px 12px', border: 'none', outline: 'none', fontSize: 13, background: 'transparent', color: 'var(--text)', fontFamily: 'inherit' }}
                />
                <button onClick={addUrl} disabled={!url.trim() || status === 'loading'}
                    style={{ padding: '0 14px', background: '#1D4ED8', color: '#fff', border: 'none', cursor: url.trim() && status !== 'loading' ? 'pointer' : 'not-allowed', fontSize: 12, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6, opacity: !url.trim() ? 0.5 : 1, transition: 'opacity 0.15s' }}>
                    <Plus size={13} /> Add
                </button>
            </div>

            {urls.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    <div style={{ fontSize: 11, color: 'var(--text3)' }}>{urls.length}/{MAX_VIDEO_URLS} link(s) queued</div>
                    <div style={{ maxHeight: 110, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--surface)', padding: 8 }}>
                        {urls.map((u, i) => (
                            <div key={`${u}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                                <span style={{ flex: 1, fontSize: 11, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{u}</span>
                                <button onClick={() => setUrls(prev => prev.filter((_, idx) => idx !== i))}
                                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', padding: 0 }}>×</button>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 10,
                padding: '10px 12px',
                borderRadius: 10,
                border: '1px solid var(--border)',
                background: 'var(--surface)',
            }}>
                <div style={{ fontSize: 11, color: 'var(--text3)', fontWeight: 600 }}>
                    {queuedCount > 0 ? `${queuedCount} link(s) ready for extraction` : 'Add one or more links to extract transcript'}
                </div>
                <button onClick={handleIngest} disabled={status === 'loading' || queuedCount === 0}
                    style={{
                        height: 32,
                        minWidth: 122,
                        padding: '0 12px',
                        borderRadius: 8,
                        background: 'linear-gradient(135deg,#2563EB,#1D4ED8)',
                        color: '#fff',
                        border: '1px solid #1D4ED8',
                        cursor: status === 'loading' || queuedCount === 0 ? 'not-allowed' : 'pointer',
                        fontSize: 12,
                        fontWeight: 700,
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: 6,
                        opacity: status === 'loading' || queuedCount === 0 ? 0.5 : 1,
                        transition: 'opacity 0.15s, transform 0.12s',
                    }}>
                    {status === 'loading' ? <Loader2 size={13} className="spin" /> : <Upload size={13} />}
                    {status === 'loading' ? 'Extracting…' : 'Extract All'}
                </button>
            </div>
            

            {status === 'ok' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 8, background: '#F0FDF4', border: '1px solid #BBF7D0', fontSize: 12, color: '#065F46', fontWeight: 600 }}>
                    <CheckCircle2 size={14} color="#10B981" /> {message}
                </div>
            )}
            {status === 'error' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '10px 12px', borderRadius: 8, background: '#FEF2F2', border: '1px solid #FECACA', fontSize: 12, color: '#991B1B' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 700 }}>
                        <AlertCircle size={13} /> {message}
                    </div>
                    <div style={{ fontSize: 11, opacity: 0.8 }}>
                        Tip: Switch to the Transcript tab and paste the transcript directly.
                    </div>
                </div>
            )}

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                {[
                    { label: 'YouTube', icon: '▶' },
                    { label: 'Google Meet', icon: '🎥' },
                    { label: 'Zoom Cloud', icon: '📹' },
                    { label: 'MS Teams', icon: '💼' },
                    { label: 'Loom', icon: '🔴' },
                ].map(p => (
                    <div key={p.label} style={{ fontSize: 10, padding: '3px 8px', borderRadius: 12, background: 'var(--surface)', border: '1px solid var(--border)', color: 'var(--text3)', fontWeight: 600 }}>
                        {p.icon} {p.label}
                    </div>
                ))}
            </div>
        </div>
    );
}

// ── Audio section ─────────────────────────────────────────────────────────────
function AudioSection({ onIngest, notebookId }) {
    const ref = useRef();
    const [files, setFiles] = useState([]);
    const [status, setStatus] = useState('idle');
    const [message, setMessage] = useState('');
    const [drag, setDrag] = useState(false);

    const addFiles = (incoming) => {
        const toAdd = Array.from(incoming || []);
        if (!toAdd.length) return;
        setFiles(prev => {
            const room = Math.max(0, MAX_AUDIO_FILES - prev.length);
            return [...prev, ...toAdd.slice(0, room)];
        });
        setStatus('idle');
    };

    const handleTranscribe = async () => {
        if (!files.length) return;
        setStatus('loading');
        setMessage('Transcribing audio files with Whisper…');
        try {
            const form = new FormData();
            files.forEach(f => form.append('audio_files', f));
            if (notebookId) form.append('notebook_id', notebookId);
            const res = await fetch(`${API}/api/media-ingest`, {
                method: 'POST',
                headers: authHeaders(),
                body: form,
            });
            const data = await res.json();
            if (data.ok && data.chunks?.length > 0) {
                setStatus('ok');
                setMessage(`✓ ${data.chunks.length} segments transcribed`);
                onIngest(data.chunks, `Audio: ${files.length} file(s)`);
                setFiles([]);
            } else {
                setStatus('error');
                setMessage(data.message || 'Transcription failed. Paste the transcript manually.');
            }
        } catch {
            setStatus('error');
            setMessage('Network error.');
        }
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ fontSize: 12, color: 'var(--text3)', lineHeight: 1.6 }}>
                Upload a recorded lecture audio file. AuraGraph will transcribe it using AI.
            </div>
            <div
                onDragOver={e => { e.preventDefault(); setDrag(true); }}
                onDragLeave={() => setDrag(false)}
                onDrop={e => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}
                onClick={() => ref.current?.click()}
                style={{
                    border: `2px dashed ${drag ? '#0F766E' : files.length ? '#10B981' : 'var(--border2)'}`,
                    borderRadius: 12, padding: '24px 20px',
                    background: drag ? '#F0FDF4' : files.length ? '#F0FDF4' : 'var(--surface)',
                    cursor: 'pointer', textAlign: 'center', transition: 'all 0.15s',
                }}
            >
                <input ref={ref} type="file" accept=".mp3,.m4a,.mp4,.wav,.ogg,.webm,.opus,.aac,.flac" multiple
                    style={{ display: 'none' }} onChange={e => addFiles(e.target.files)} />
                {files.length ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: '#0F766E' }}>{files.length}/{MAX_AUDIO_FILES} audio file(s) selected</div>
                        <div style={{ maxHeight: 90, overflowY: 'auto' }}>
                            {files.map((f, i) => (
                                <div key={`${f.name}-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                                    <span style={{ flex: 1, fontSize: 11, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</span>
                                    <button onClick={e => { e.stopPropagation(); setFiles(prev => prev.filter((_, idx) => idx !== i)); setStatus('idle'); }}
                                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', padding: 0 }}>
                                        <X size={12} />
                                    </button>
                                </div>
                            ))}
                        </div>
                    </div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
                        <div style={{ width: 44, height: 44, borderRadius: 12, background: '#0F766E15', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <Mic size={22} color="#0F766E" />
                        </div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text2)' }}>Drop audio file here</div>
                        <div style={{ fontSize: 11, color: 'var(--text3)' }}>MP3, M4A, WAV, MP4, OGG · max 25 MB</div>
                    </div>
                )}
            </div>

            {files.length > 0 && status !== 'ok' && (
                <button onClick={handleTranscribe} disabled={status === 'loading'}
                    style={{ padding: '10px 0', borderRadius: 8, background: '#0F766E', color: '#fff', border: 'none', cursor: status === 'loading' ? 'not-allowed' : 'pointer', fontSize: 13, fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
                    {status === 'loading' ? <><Loader2 size={14} className="spin" /> Transcribing…</> : <><Mic size={14} /> Transcribe All</>}
                </button>
            )}

            {status === 'ok' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 8, background: '#F0FDF4', border: '1px solid #BBF7D0', fontSize: 12, color: '#065F46', fontWeight: 600 }}>
                    <CheckCircle2 size={14} color="#10B981" /> {message}
                </div>
            )}
            {status === 'error' && (
                <div style={{ padding: '8px 12px', borderRadius: 8, background: '#FEF2F2', border: '1px solid #FECACA', fontSize: 12, color: '#991B1B', fontWeight: 600 }}>
                    <AlertCircle size={13} style={{ marginRight: 6 }} />{message}
                </div>
            )}
        </div>
    );
}

// ── Transcript section ────────────────────────────────────────────────────────
function TranscriptSection({ onIngest, notebookId }) {
    const [text, setText] = useState('');
    const [files, setFiles] = useState([]);
    const [drag, setDrag] = useState(false);
    const ref = useRef();

    const [loading, setLoading] = React.useState(false);

    const addFiles = (incoming) => {
        const toAdd = Array.from(incoming || []);
        if (!toAdd.length) return;
        setFiles(prev => {
            const room = Math.max(0, MAX_TRANSCRIPT_FILES - prev.length);
            return [...prev, ...toAdd.slice(0, room)];
        });
    };

    const handleIngest = async () => {
        if (!text.trim() && !files.length) return;
        setLoading(true);
        try {
            const form = new FormData();
            if (text.trim()) form.append('transcript', text.trim());
            files.forEach(f => form.append('transcript_files', f));
            if (notebookId) form.append('notebook_id', notebookId);
            const res = await fetch(`${API}/api/media-ingest`, {
                method: 'POST', headers: authHeaders(), body: form,
            });
            const data = await res.json();
            if (data.ok && data.chunks?.length > 0) {
                onIngest(data.chunks, `Transcript: ${files.length} file(s)${text.trim() ? ' + pasted text' : ''}`);
                setText('');
                setFiles([]);
            } else {
                // Fallback: pass raw text as single chunk
                if (text.trim()) {
                    const wc = text.trim().split(/\s+/).length;
                    onIngest([text.trim()], `Transcript (${wc.toLocaleString()} words)`);
                    setText('');
                }
            }
        } catch {
            // Offline fallback
            if (text.trim()) {
                const wc = text.trim().split(/\s+/).length;
                onIngest([text.trim()], `Transcript (${wc.toLocaleString()} words)`);
                setText('');
            }
        } finally {
            setLoading(false);
        }
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ fontSize: 12, color: 'var(--text3)', lineHeight: 1.6 }}>
                Paste the class transcript directly, or upload a <code style={{ fontSize: 11, background: 'var(--surface)', padding: '1px 5px', borderRadius: 4 }}>.txt</code> file.
            </div>

            <div style={{ position: 'relative' }}
                onDragOver={e => { e.preventDefault(); setDrag(true); }}
                onDragLeave={() => setDrag(false)}
                onDrop={e => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}>
                <textarea
                    value={text}
                    onChange={e => setText(e.target.value)}
                    placeholder="Paste transcript here…&#10;&#10;e.g. Professor: Today we'll cover Fourier transforms. As you can see from the slide, the formula for the Fourier transform is…"
                    style={{
                        width: '100%', minHeight: 180, borderRadius: 10, resize: 'vertical', outline: 'none',
                        border: `1.5px solid ${drag ? '#D97706' : text ? '#D97706' : 'var(--border)'}`,
                        padding: '12px 14px', fontSize: 13, lineHeight: 1.7, fontFamily: 'inherit',
                        background: drag ? '#FFFBEB' : 'var(--bg)', color: 'var(--text)',
                        transition: 'border-color 0.15s', boxSizing: 'border-box',
                    }}
                />
                {!text && (
                    <button onClick={() => ref.current?.click()}
                        style={{ position: 'absolute', bottom: 12, right: 12, padding: '5px 10px', borderRadius: 6, background: 'var(--surface)', border: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, color: 'var(--text3)', display: 'flex', alignItems: 'center', gap: 5, fontWeight: 600 }}>
                        <Plus size={11} /> Upload .txt
                    </button>
                )}
                <input ref={ref} type="file" accept=".txt,.vtt,.srt" style={{ display: 'none' }}
                    multiple
                    onChange={e => addFiles(e.target.files)} />
            </div>

            {files.length > 0 && (
                <div style={{ fontSize: 11, color: 'var(--text3)' }}>
                    {files.length}/{MAX_TRANSCRIPT_FILES} transcript file(s) queued
                </div>
            )}

            {(text || files.length > 0) && (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: 11, color: 'var(--text3)' }}>
                        {text ? `${text.trim().split(/\s+/).length.toLocaleString()} pasted words` : 'No pasted text'}
                    </span>
                    <div style={{ display: 'flex', gap: 8 }}>
                        <button onClick={() => { setText(''); setFiles([]); }}
                            style={{ padding: '6px 12px', borderRadius: 7, background: 'transparent', border: '1px solid var(--border)', cursor: 'pointer', fontSize: 12, color: 'var(--text3)' }}>
                            Clear
                        </button>
                        <button onClick={handleIngest} disabled={loading}
                            style={{ padding: '6px 14px', borderRadius: 7, background: '#D97706', color: '#fff', border: 'none', cursor: loading ? 'not-allowed' : 'pointer', fontSize: 12, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 6 }}>
                            {loading ? <><Loader2 size={12} className="spin" /> Processing…</> : <><AlignLeft size={12} /> Use Transcript</>}
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}

// ── Main SourceInputPanel ─────────────────────────────────────────────────────
export default function SourceInputPanel({
    slidesFiles, setSlidesFiles,
    notesFiles, setNotesFiles,
    textbookFiles, setTextbookFiles,
    mediaChunks, setMediaChunks,
    mediaSourceDesc, setMediaSourceDesc,
    notebookId,
}) {
    const [activeTab, setActiveTab] = useState('files');

    const handleMediaIngest = useCallback((chunks, desc) => {
        setMediaChunks(prev => [...prev, ...chunks]);
        setMediaSourceDesc(prev => prev ? `${prev} | ${desc}` : desc);
    }, [setMediaChunks, setMediaSourceDesc]);

    const hasAnyInput = slidesFiles.length > 0 || notesFiles.length > 0 ||
                        textbookFiles.length > 0 || mediaChunks.length > 0;

    return (
        <div>
            {/* Tab bar */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 16, background: 'var(--surface)', padding: 4, borderRadius: 12, border: '1px solid var(--border)' }}>
                {SOURCES.map(s => {
                    const Icon = s.icon;
                    const active = activeTab === s.id;
                    const mediaDesc = (mediaSourceDesc || '').toLowerCase();
                    const hasBadge = (s.id === 'files' && (slidesFiles.length + notesFiles.length + textbookFiles.length) > 0) ||
                                     ((s.id === 'video' || s.id === 'audio' || s.id === 'transcript') && mediaChunks.length > 0 && mediaDesc.includes(s.id === 'video' ? 'video' : s.id === 'audio' ? 'audio' : 'transcript'));
                    return (
                        <button key={s.id} onClick={() => setActiveTab(s.id)}
                            style={{
                                flex: 1, padding: '8px 6px', borderRadius: 8, border: 'none', cursor: 'pointer',
                                background: active ? s.bg : 'transparent',
                                boxShadow: active ? `0 0 0 1.5px ${s.border}` : 'none',
                                transition: 'all 0.15s',
                                display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, position: 'relative',
                            }}>
                            <Icon size={16} color={active ? s.color : 'var(--text3)'} />
                            <span style={{ fontSize: 10, fontWeight: 700, color: active ? s.color : 'var(--text3)', whiteSpace: 'nowrap' }}>
                                {s.label}
                            </span>
                            {hasBadge && (
                                <div style={{ position: 'absolute', top: 4, right: 4, width: 7, height: 7, borderRadius: '50%', background: s.color }} />
                            )}
                        </button>
                    );
                })}
            </div>

            {/* Tab label + description */}
            {(() => {
                const src = SOURCES.find(s => s.id === activeTab);
                const Icon = src.icon;
                return (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
                        <div style={{ width: 28, height: 28, borderRadius: 8, background: src.bg, border: `1px solid ${src.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                            <Icon size={14} color={src.color} />
                        </div>
                        <div>
                            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>{src.label}</div>
                            <div style={{ fontSize: 11, color: 'var(--text3)' }}>{src.desc}</div>
                        </div>
                    </div>
                );
            })()}

            {/* Tab content */}
            <div style={{ minHeight: 160 }}>
                {activeTab === 'files' && (
                    <FileSection slidesFiles={slidesFiles} setSlidesFiles={setSlidesFiles}
                        notesFiles={notesFiles} setNotesFiles={setNotesFiles}
                        textbookFiles={textbookFiles} setTextbookFiles={setTextbookFiles} />
                )}
                {activeTab === 'video' && (
                    <VideoSection onIngest={handleMediaIngest} notebookId={notebookId} />
                )}
                {activeTab === 'audio' && (
                    <AudioSection onIngest={handleMediaIngest} notebookId={notebookId} />
                )}
                {activeTab === 'transcript' && (
                    <TranscriptSection onIngest={handleMediaIngest} notebookId={notebookId} />
                )}
            </div>

            {/* Active sources summary */}
            {hasAnyInput && (
                <div style={{ marginTop: 16, padding: '10px 12px', borderRadius: 10, background: 'var(--surface)', border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
                        Sources ready for generation
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                        {slidesFiles.length > 0 && (
                            <SourcePill desc={`${slidesFiles.length} slide file${slidesFiles.length > 1 ? 's' : ''}`}
                                onRemove={() => setSlidesFiles([])} color="#7C3AED" border="#DDD6FE" bg="#F5F3FF" />
                        )}
                        {notesFiles.length > 0 && (
                            <SourcePill desc={`${notesFiles.length} handwritten note${notesFiles.length > 1 ? 's' : ''}`}
                                onRemove={() => setNotesFiles([])} color="#2563EB" border="#BFDBFE" bg="#EFF6FF" />
                        )}
                        {textbookFiles.length > 0 && (
                            <SourcePill desc={`${textbookFiles.length} textbook file${textbookFiles.length > 1 ? 's' : ''}`}
                                onRemove={() => setTextbookFiles([])} color="#0F766E" border="#BBF7D0" bg="#F0FDF4" />
                        )}
                        {mediaChunks.length > 0 && (
                            <SourcePill desc={mediaSourceDesc ? `${mediaChunks.length} recording segments` : `${mediaChunks.length} recording segments`}
                                onRemove={() => { setMediaChunks([]); setMediaSourceDesc(''); }}
                                color="#D97706" border="#FDE68A" bg="#FFFBEB" />
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
