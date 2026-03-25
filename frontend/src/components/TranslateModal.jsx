/**
 * TranslateModal — translate a note page into another Indian language.
 * Uses Azure Translator via backend proxy.
 * Rendered as a side panel that replaces the page content temporarily.
 */
import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';
import { X, Languages, Loader2, RotateCcw } from 'lucide-react';
import { API, authHeaders } from './utils';

const LANGUAGES = [
    { code: 'hi', name: 'Hindi',     native: 'हिंदी',     flag: '🇮🇳' },
    { code: 'te', name: 'Telugu',    native: 'తెలుగు',    flag: '🇮🇳' },
    { code: 'ta', name: 'Tamil',     native: 'தமிழ்',     flag: '🇮🇳' },
    { code: 'mr', name: 'Marathi',   native: 'मराठी',     flag: '🇮🇳' },
    { code: 'bn', name: 'Bengali',   native: 'বাংলা',     flag: '🇮🇳' },
    { code: 'kn', name: 'Kannada',   native: 'ಕನ್ನಡ',    flag: '🇮🇳' },
    { code: 'ml', name: 'Malayalam', native: 'മലയാളം',   flag: '🇮🇳' },
];

export default function TranslateModal({ originalText, onClose, onSpeak, ttsVoices = [] }) {
    const [targetLang, setTargetLang] = useState('hi');
    const [translated,  setTranslated] = useState('');
    const [loading,     setLoading]    = useState(false);
    const [llmReady,    setLlmReady]    = useState(true);
    const [error,       setError]      = useState('');

    const translate = async (lang) => {
        setTargetLang(lang);
        setTranslated('');
        setLoading(true);
        setError('');
        try {
            const res = await fetch(`${API}/api/translate`, {
                method: 'POST',
                headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: originalText.slice(0, 5000), target_lang: lang }),
            });
            if (!res.ok) {
                const j = await res.json().catch(() => ({}));
                throw new Error(j.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            setTranslated(data.translated || '');
        } catch (e) {
            setError(e.message || 'Translation failed — check AZURE_OPENAI_API_KEY or GROQ_API_KEY in .env.');
        }
        setLoading(false);
    };

    // Pick best voice for current target language
    const bestVoice = (lang) => {
        const map = { hi: 'hi-IN-F', te: 'te-IN-F', ta: 'ta-IN-F' };
        return map[lang] || 'en-IN-F';
    };

    const currentLang = LANGUAGES.find(l => l.code === targetLang);

    return (
        <div style={{
            position: 'fixed', inset: 0, zIndex: 8500,
            background: 'rgba(0,0,0,0.5)',
            display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
            padding: '24px 16px', overflowY: 'auto',
        }} onClick={onClose}>
            <div onClick={e => e.stopPropagation()} style={{
                width: '100%', maxWidth: 720,
                background: 'var(--bg)', borderRadius: 18,
                boxShadow: '0 20px 80px rgba(0,0,0,0.25)',
                overflow: 'hidden', marginTop: 8,
            }}>
                {/* Header */}
                <div style={{
                    background: 'linear-gradient(135deg, #0f0a1e, #1a0f3d)',
                    padding: '16px 22px',
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <div style={{ width: 38, height: 38, borderRadius: 10, background: 'rgba(124,58,237,0.3)', border: '1px solid rgba(124,58,237,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <Languages size={18} color="#A78BFA" />
                        </div>
                        <div>
                            <div style={{ fontSize: 15, fontWeight: 800, color: '#fff' }}>Translate Page</div>
                            <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.55)' }}>
                                AI translation — natural academic language · read aloud in your language
                            </div>
                        </div>
                    </div>
                    <button onClick={onClose} style={{ background: 'rgba(255,255,255,0.15)', border: 'none', borderRadius: 8, cursor: 'pointer', color: '#fff', padding: 8, display: 'flex' }}>
                        <X size={14} />
                    </button>
                </div>

                {/* Language picker */}
                <div style={{ padding: '16px 22px', borderBottom: '1px solid var(--border)' }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 10 }}>
                        Translate to
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                        {LANGUAGES.map(l => (
                            <button key={l.code}
                                onClick={() => translate(l.code)}
                                style={{
                                    padding: '7px 14px', borderRadius: 20, cursor: 'pointer',
                                    border: `1.5px solid ${targetLang === l.code ? 'var(--ag-purple)' : 'var(--border)'}`,
                                    background: targetLang === l.code ? 'var(--ag-purple-bg)' : 'var(--surface)',
                                    color: targetLang === l.code ? 'var(--ag-purple)' : 'var(--text2)',
                                    fontSize: 12, fontWeight: 600, transition: 'all 0.12s',
                                    display: 'flex', alignItems: 'center', gap: 6,
                                }}>
                                <span>{l.flag}</span>
                                <span>{l.name}</span>
                                <span style={{ fontSize: 11, opacity: 0.7 }}>{l.native}</span>
                            </button>
                        ))}
                    </div>
                </div>

                {/* Content */}
                <div style={{ padding: '20px 22px', minHeight: 200, maxHeight: '55vh', overflowY: 'auto' }}>
                    {loading && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text3)', fontSize: 14 }}>
                            <Loader2 className="spin" size={18} color="var(--ag-purple)" />
                            Translating to {currentLang?.name}…
                        </div>
                    )}
                    {error && (
                        <div style={{ background: '#FEF2F2', border: '1px solid #FECACA', borderRadius: 10, padding: '12px 16px', fontSize: 13, color: '#DC2626' }}>
                            ⚠ {error}
                        </div>
                    )}
                    {!loading && translated && (
                        <>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--ag-purple)', display: 'flex', alignItems: 'center', gap: 5 }}>
                                    <span>{currentLang?.flag}</span>
                                    <span>{currentLang?.name} — {currentLang?.native}</span>
                                </span>
                                <div style={{ display: 'flex', gap: 8 }}>
                                    {onSpeak && (
                                        <button
                                            onClick={() => onSpeak(translated, bestVoice(targetLang))}
                                            style={{ padding: '5px 12px', borderRadius: 8, border: '1px solid var(--ag-purple-border)', background: 'var(--ag-purple-bg)', color: 'var(--ag-purple)', cursor: 'pointer', fontSize: 11, fontWeight: 700, display: 'flex', alignItems: 'center', gap: 5 }}>
                                            🔊 Read Aloud
                                        </button>
                                    )}
                                    <button onClick={() => translate(targetLang)} style={{ padding: '5px 10px', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)', color: 'var(--text3)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
                                        <RotateCcw size={11} /> Retry
                                    </button>
                                </div>
                            </div>
                            <div style={{ fontSize: 14, lineHeight: 1.85, color: 'var(--text)' }}>
                                <ReactMarkdown
                                    remarkPlugins={[remarkMath, remarkGfm]}
                                    rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]}
                                >
                                    {translated}
                                </ReactMarkdown>
                            </div>
                        </>
                    )}
                    {!loading && !translated && !error && (
                        <div style={{ color: 'var(--text3)', fontSize: 13, textAlign: 'center', padding: '40px 0' }}>
                            Select a language above to translate this page.
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
