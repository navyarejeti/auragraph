/**
 * AudioPlayer — floating Spotify-style mini-player for note TTS.
 *
 * Appears when a page is being spoken/loading.
 * Anchored bottom-centre of the note scroll area.
 * Collapses to a tiny pill when idle and the user has interacted before.
 *
 * Props:
 *   tts        — return value of useTextToSpeech()
 *   pageLabel  — e.g. "Page 3"
 *   onClose    — called when user explicitly dismisses
 */
import React, { useState } from 'react';
import {
    Play, Pause, Square, ChevronUp, ChevronDown, Volume2, Loader2
} from 'lucide-react';

const SPEED_OPTIONS = [
    { value: 0.75, label: '0.75×' },
    { value: 1,    label: '1×'    },
    { value: 1.25, label: '1.25×' },
    { value: 1.5,  label: '1.5×'  },
];

export default function AudioPlayer({ tts, pageLabel, onClose }) {
    const { isPlaying, isLoading, voice, setVoice, speed, changeSpeed, voices, stop, pause, resume, error } = tts;
    const [expanded, setExpanded] = useState(true);

    const active = isPlaying || isLoading;

    return (
        <div style={{
            position: 'fixed',
            bottom: 28,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 7000,
            background: 'var(--bg)',
            border: '1px solid var(--ag-purple-border)',
            borderRadius: expanded ? 16 : 40,
            boxShadow: '0 8px 40px rgba(124,58,237,0.25)',
            overflow: 'hidden',
            transition: 'all 0.22s ease',
            minWidth: expanded ? 340 : 'unset',
        }}>
            {/* Collapsed pill */}
            {!expanded && (
                <button
                    onClick={() => setExpanded(true)}
                    style={{
                        background: 'linear-gradient(135deg, var(--ag-purple), #2563EB)',
                        border: 'none', borderRadius: 40, cursor: 'pointer',
                        padding: '8px 18px', display: 'flex', alignItems: 'center', gap: 8,
                        color: '#fff', fontSize: 13, fontWeight: 700,
                    }}
                >
                    {isLoading
                        ? <Loader2 className="spin" size={14} />
                        : isPlaying ? <Volume2 size={14} style={{ animation: 'ttsWave 1s ease-in-out infinite' }} />
                        : <Play size={14} />}
                    {pageLabel}
                    <ChevronUp size={12} style={{ opacity: 0.7 }} />
                </button>
            )}

            {/* Expanded player */}
            {expanded && (
                <div style={{ padding: '14px 18px 16px' }}>
                    {/* Header row */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                            {/* Waveform animation when playing */}
                            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: 18 }}>
                                {[1,2,3,4].map(i => (
                                    <div key={i} style={{
                                        width: 3, borderRadius: 2,
                                        background: active ? 'var(--ag-purple)' : 'var(--border2)',
                                        height: active ? `${8 + i * 3}px` : '6px',
                                        animation: active && isPlaying ? `ttsBar${i} 0.6s ${i * 0.1}s ease-in-out infinite alternate` : 'none',
                                        transition: 'height 0.3s',
                                    }} />
                                ))}
                            </div>
                            <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>
                                {isLoading ? 'Loading audio…' : isPlaying ? `Reading ${pageLabel}` : `${pageLabel} — paused`}
                            </span>
                        </div>
                        <button onClick={() => setExpanded(false)}
                            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', padding: 2, display: 'flex' }}>
                            <ChevronDown size={14} />
                        </button>
                    </div>

                    {/* Error message */}
                    {error && (
                        <div style={{ background: '#FEF2F2', border: '1px solid #FECACA', borderRadius: 8, padding: '6px 10px', fontSize: 11, color: '#DC2626', marginBottom: 10 }}>
                            ⚠ {error}
                        </div>
                    )}

                    {/* Controls row */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                        {/* Play/Pause */}
                        <button
                            onClick={isPlaying ? pause : resume}
                            disabled={isLoading}
                            style={{
                                width: 40, height: 40, borderRadius: '50%',
                                background: 'linear-gradient(135deg, var(--ag-purple), #2563EB)',
                                border: 'none', cursor: isLoading ? 'not-allowed' : 'pointer',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                color: '#fff', flexShrink: 0, opacity: isLoading ? 0.6 : 1,
                            }}>
                            {isLoading
                                ? <Loader2 className="spin" size={16} />
                                : isPlaying ? <Pause size={16} fill="#fff" />
                                : <Play size={16} fill="#fff" />}
                        </button>

                        {/* Stop */}
                        <button onClick={() => { stop(); onClose?.(); }}
                            style={{ width: 34, height: 34, borderRadius: '50%', background: 'var(--surface)', border: '1px solid var(--border)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text2)' }}>
                            <Square size={13} />
                        </button>

                        {/* Speed selector */}
                        <div style={{ display: 'flex', gap: 3, marginLeft: 4 }}>
                            {SPEED_OPTIONS.map(opt => (
                                <button key={opt.value} onClick={() => changeSpeed(opt.value)}
                                    style={{
                                        padding: '4px 8px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 11, fontWeight: 700,
                                        background: speed === opt.value ? 'var(--ag-purple)' : 'var(--surface)',
                                        color: speed === opt.value ? '#fff' : 'var(--text3)',
                                        transition: 'all 0.12s',
                                    }}>
                                    {opt.label}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Voice selector */}
                    <div>
                        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 6 }}>Voice</div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                            {voices.map(v => (
                                <button key={v.key} onClick={() => setVoice(v.key)}
                                    title={v.label}
                                    style={{
                                        padding: '5px 9px', borderRadius: 20, cursor: 'pointer', fontSize: 11, fontWeight: 600,
                                        border: `1px solid ${voice === v.key ? 'var(--ag-purple)' : 'var(--border)'}`,
                                        background: voice === v.key ? 'var(--ag-purple-bg)' : 'var(--surface)',
                                        color: voice === v.key ? 'var(--ag-purple)' : 'var(--text2)',
                                        transition: 'all 0.12s',
                                        display: 'flex', alignItems: 'center', gap: 4,
                                    }}>
                                    <span>{v.flag}</span>
                                    <span>{v.label.split('(')[0].trim()}</span>
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
