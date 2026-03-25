import React, { useState, useEffect, useRef } from 'react';

const FUSE_STEPS = [
    { label: 'Uploading files', icon: '📤' },
    { label: 'Extracting slides & notes', icon: '📄' },
    { label: 'Extracting textbook content', icon: '📚' },
    { label: 'Running Fusion Agent', icon: '🧠' },
    { label: 'Calibrating to your level', icon: '🎯' },
    { label: 'Verifying accuracy', icon: '🔍' },
    { label: 'Building concept map', icon: '🕸️' },
    { label: 'Finalising notes', icon: '✨' },
];

// Study-science facts — short, punchy, performance-relevant
// Stored as a plain array so zero network cost; cached by the JS bundle
const FACTS = [
    { emoji: '🧠', fact: 'Spaced repetition improves recall by up to 200% compared to cramming.' },
    { emoji: '💤', fact: 'Sleep consolidates memory. Studying before bed and reviewing the next morning is scientifically optimal.' },
    { emoji: '✍️', fact: 'The act of writing by hand activates more of the brain than typing — even when studying digital notes.' },
    { emoji: '🔁', fact: 'The "Forgetting Curve" shows 70% of new info is lost within 24 hours without review.' },
    { emoji: '🎯', fact: 'Retrieval practice (testing yourself) is 2× more effective than re-reading your notes.' },
    { emoji: '⏱️', fact: 'The Pomodoro technique (25 min focus + 5 min break) is backed by research to prevent cognitive fatigue.' },
    { emoji: '🌊', fact: 'Interleaving topics — switching between subjects — builds stronger long-term memory than blocked study.' },
    { emoji: '🗺️', fact: 'Concept mapping (like AuraGraph does!) increases understanding by making hidden connections visible.' },
    { emoji: '🧘', fact: 'Even 10 minutes of mindfulness before studying can boost focus and working memory.' },
    { emoji: '💧', fact: 'Mild dehydration (as little as 1–2%) measurably reduces cognitive performance.' },
    { emoji: '📊', fact: 'Students who set specific goals before each study session perform 20% better on assessments.' },
    { emoji: '🤔', fact: 'Elaborative interrogation — asking "why?" — doubles retention compared to passive reading.' },
    { emoji: '🎵', fact: 'Instrumental music at ~60 BPM (like lo-fi) is associated with improved concentration and mood.' },
    { emoji: '🌅', fact: 'Alertness peaks at roughly 10 AM and 3 PM for most people — ideal windows for hard study sessions.' },
    { emoji: '📝', fact: 'Summarising a concept in your own words (like "Note Mutation") is one of the highest-yield study strategies.' },
    { emoji: '🔗', fact: 'Connecting new knowledge to something you already know reduces the cognitive load needed to store it.' },
    { emoji: '🏃', fact: 'A 20-minute walk before studying increases brain-derived neurotrophic factor (BDNF), boosting learning.' },
    { emoji: '🃏', fact: 'Flashcards work best when you say the answer aloud before flipping — the "generation effect".' },
];

// Fisher-Yates shuffle — runs once per session, negligible cost
function shuffleFacts() {
    const arr = [...FACTS];
    for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
}

// Cache shuffled order per page session so facts don't reset on re-render
let _sessionFacts = null;
function getSessionFacts() {
    if (!_sessionFacts) _sessionFacts = shuffleFacts();
    return _sessionFacts;
}

export default function FuseProgressBar({ active, forceStep = null }) {
    const [step, setStep] = useState(0);
    const [dots, setDots] = useState('');
    const [overdue, setOverdue] = useState(false);
    const [factIdx, setFactIdx] = useState(0);
    const [factVisible, setFactVisible] = useState(true);
    const facts = useRef(getSessionFacts()).current;
    const displayStep = forceStep !== null ? forceStep : step;

    useEffect(() => {
        if (!active) { setStep(0); setDots(''); setOverdue(false); setFactIdx(0); setFactVisible(true); return; }

        const st = setInterval(() => setStep(s => {
            if (s < 4) return s + 1;
            if (s === 4) return 3;
            return s;
        }), 3500);
        const dt = setInterval(() => setDots(d => d.length >= 3 ? '' : d + '.'), 400);
        const ot = setTimeout(() => setOverdue(true), 45_000);

        // Rotate facts every 14 s — enough to read a 25-word sentence comfortably
        const ft = setInterval(() => {
            setFactVisible(false);
            setTimeout(() => {
                setFactIdx(i => (i + 1) % facts.length);
                setFactVisible(true);
            }, 350);
        }, 14000);

        return () => { clearInterval(st); clearInterval(dt); clearTimeout(ot); clearInterval(ft); };
    }, [active, facts.length]);

    if (!active) return null;

    const currentFact = facts[factIdx];

    return (
        <div style={{
            marginBottom: 20,
            background: overdue ? '#FFFBEB' : 'var(--surface)',
            border: `1px solid ${overdue ? '#FDE68A' : 'var(--border)'}`,
            borderRadius: 12,
            padding: '16px 20px',
        }}>
            {/* Step indicator */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                <span style={{ fontSize: 22 }}>{FUSE_STEPS[displayStep].icon}</span>
                <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>
                        {FUSE_STEPS[displayStep].label}{dots}
                    </div>
                    <div style={{ fontSize: 11, color: overdue ? '#92400E' : 'var(--text3)', marginTop: 2, fontWeight: overdue ? 600 : 400 }}>
                        {overdue
                            ? '⚠️ Large upload detected — AI is still working, please keep this tab open'
                            : displayStep === 5
                                ? 'Cross-checking formulas and definitions against source material…'
                                : `Step ${displayStep + 1} of ${FUSE_STEPS.length} — processing your materials${displayStep >= 3 ? ' (large books may take a few minutes)' : ''}`}
                    </div>
                </div>
            </div>

            {/* Progress bar */}
            <div style={{ height: 4, background: 'var(--border)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{
                    height: '100%', borderRadius: 4,
                    background: 'linear-gradient(90deg, #7C3AED, #2563EB)',
                    width: `${((displayStep + 1) / FUSE_STEPS.length) * 100}%`,
                    transition: 'width 0.6s ease',
                }} />
            </div>
            <div style={{ display: 'flex', gap: 5, marginTop: 10 }}>
                {FUSE_STEPS.map((s, i) => (
                    <div key={i} title={s.label} style={{ flex: 1, height: 3, borderRadius: 2, background: i <= displayStep ? 'var(--ag-purple)' : 'var(--border)', transition: 'background 0.4s' }} />
                ))}
            </div>

            {/* Rotating fact card */}
            <div style={{
                marginTop: 14,
                padding: '11px 14px',
                background: 'linear-gradient(135deg, var(--ag-purple-bg) 0%, var(--bg) 100%)',
                border: '1px solid var(--ag-purple-border)',
                borderRadius: 9,
                display: 'flex',
                alignItems: 'flex-start',
                gap: 10,
                opacity: factVisible ? 1 : 0,
                transform: factVisible ? 'translateY(0)' : 'translateY(4px)',
                transition: 'opacity 0.35s ease, transform 0.35s ease',
            }}>
                <span style={{ fontSize: 18, flexShrink: 0, lineHeight: 1.3 }}>{currentFact.emoji}</span>
                <div>
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--ag-purple)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 3 }}>
                        Did you know?
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text2)', lineHeight: 1.6 }}>
                        {currentFact.fact}
                    </div>
                </div>
            </div>
        </div>
    );
}
