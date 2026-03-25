/**
 * useTextToSpeech — manages TTS state for the note workspace.
 *
 * Features:
 * - Per-page audio caching (blob URLs, freed on unmount)
 * - Sentence-level chunking so first audio arrives fast
 * - Play / pause / stop / speed / voice controls
 * - Azure Neural TTS via backend proxy (keeps API key server-side)
 */
import { useState, useRef, useCallback, useEffect } from 'react';
import { API, authHeaders } from '../components/utils';

export const DEFAULT_VOICE = 'en-IN-F';

export function useTextToSpeech() {
    const [isPlaying,    setIsPlaying]    = useState(false);
    const [isLoading,    setIsLoading]    = useState(false);
    const [activePageIdx,setActivePageIdx]= useState(null);
    const [voice,        setVoice]        = useState(() => localStorage.getItem('ag_tts_voice') || DEFAULT_VOICE);
    const [speed,        setSpeed]        = useState(() => parseFloat(localStorage.getItem('ag_tts_speed') || '1'));
    const [voices,       setVoices]       = useState([]);
    const [azureReady,   setAzureReady]   = useState(false);
    const [error,        setError]        = useState('');

    const audioRef  = useRef(null);          // current HTMLAudioElement
    const cacheRef  = useRef({});            // pageIdx → blob URL
    const abortRef  = useRef(null);          // AbortController

    // Load available voices on mount
    useEffect(() => {
        fetch(`${API}/api/tts/voices`, { headers: authHeaders() })
            .then(r => r.json())
            .then(d => {
                setVoices(d.voices || []);
                setAzureReady(d.azure_configured || false);
            })
            .catch(() => {});
    }, []);

    // Persist preferences
    useEffect(() => { localStorage.setItem('ag_tts_voice', voice); }, [voice]);
    useEffect(() => { localStorage.setItem('ag_tts_speed', String(speed)); }, [speed]);

    // Cleanup blob URLs on unmount
    useEffect(() => {
        return () => {
            Object.values(cacheRef.current).forEach(URL.revokeObjectURL);
            if (audioRef.current) { audioRef.current.pause(); audioRef.current = null; }
            abortRef.current?.abort();
        };
    }, []);

    const stop = useCallback(() => {
        abortRef.current?.abort();
        if (audioRef.current) { audioRef.current.pause(); audioRef.current.src = ''; audioRef.current = null; }
        setIsPlaying(false);
        setIsLoading(false);
        setActivePageIdx(null);
        setError('');
    }, []);

    const pause = useCallback(() => {
        if (audioRef.current) { audioRef.current.pause(); }
        setIsPlaying(false);
    }, []);

    const resume = useCallback(() => {
        if (audioRef.current) {
            audioRef.current.playbackRate = speed;
            audioRef.current.play().then(() => setIsPlaying(true)).catch(() => {});
        }
    }, [speed]);

    const rateToPercent = (s) => {
        // Convert 0.75→"-25%", 1→"0%", 1.25→"+25%", 1.5→"+50%", 2→"+100%"
        const pct = Math.round((s - 1) * 100);
        return `${pct >= 0 ? '+' : ''}${pct}%`;
    };

    const speak = useCallback(async (text, pageIdx) => {
        if (!text?.trim()) return;
        if (!azureReady) { setError('Azure Speech Service not configured — add AZURE_SPEECH_KEY to .env'); return; }

        // If same page is already playing, toggle pause/resume
        if (activePageIdx === pageIdx && audioRef.current) {
            if (isPlaying) { pause(); return; }
            else { resume(); return; }
        }

        stop();
        setActivePageIdx(pageIdx);
        setIsLoading(true);
        setError('');

        abortRef.current = new AbortController();

        try {
            // Check cache first
            const cacheKey = `${pageIdx}_${voice}_${speed}`;
            if (cacheRef.current[cacheKey]) {
                _playBlob(cacheRef.current[cacheKey], pageIdx, speed);
                setIsLoading(false);
                return;
            }

            const res = await fetch(`${API}/api/tts`, {
                method: 'POST',
                headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ text, voice, rate: rateToPercent(speed) }),
                signal: abortRef.current.signal,
            });

            if (!res.ok) {
                const j = await res.json().catch(() => ({}));
                throw new Error(j.detail || `TTS error ${res.status}`);
            }

            const blob   = await res.blob();
            const blobUrl = URL.createObjectURL(blob);
            cacheRef.current[cacheKey] = blobUrl;
            _playBlob(blobUrl, pageIdx, speed);
        } catch (e) {
            if (e.name === 'AbortError') return;
            setError(e.message || 'TTS failed');
            setIsLoading(false);
            setActivePageIdx(null);
        }
    }, [azureReady, voice, speed, activePageIdx, isPlaying, stop, pause, resume]);

    const _playBlob = (blobUrl, pageIdx, spd) => {
        const audio = new Audio(blobUrl);
        audio.playbackRate = spd;
        audioRef.current   = audio;
        audio.onplay     = () => { setIsPlaying(true);  setIsLoading(false); };
        audio.onpause    = () => setIsPlaying(false);
        audio.onended    = () => { setIsPlaying(false); setActivePageIdx(null); };
        audio.onerror    = () => { setError('Audio playback failed'); setIsPlaying(false); setIsLoading(false); };
        audio.play().catch(() => {});
    };

    const changeSpeed = useCallback((s) => {
        setSpeed(s);
        if (audioRef.current) audioRef.current.playbackRate = s;
    }, []);

    return {
        speak, stop, pause, resume, changeSpeed,
        isPlaying, isLoading, activePageIdx,
        voice, setVoice, speed, changeSpeed,
        voices, azureReady, error, setError,
    };
}
