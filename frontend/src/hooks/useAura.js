/**
 * useAura — AuraGraph gamification engine
 *
 * XP earned:
 *   +10  per correct quiz answer  (×multiplier)
 *   +50  completing a quiz        (flat, no count multiplier)
 *   +25  bonus for ≥80% score     (flat)
 *   +5   per text highlight added (×multiplier)
 *   +15  per doubt asked          (×multiplier)
 *
 * Badges (6 tiers) unlock note themes and XP multipliers.
 */

import { useState, useCallback, useEffect } from 'react';
import { API, authHeaders } from '../components/utils';

const LEGACY_STORAGE_KEY = 'ag_aura_v2';

// ── Badge definitions ─────────────────────────────────────────────────────────

export const BADGES = [
    {
        id: 'seeker',
        name: 'Seeker',
        emoji: '✨',
        minXp: 0,
        color: '#6B7280',
        bg: '#F3F4F6',
        border: '#E5E7EB',
        desc: 'Your journey begins.',
        perk: 'Default note theme',
        theme: null,
    },
    {
        id: 'scholar',
        name: 'Scholar',
        emoji: '📚',
        minXp: 1500,
        color: '#2563EB',
        bg: '#EFF6FF',
        border: '#BFDBFE',
        desc: 'Knowledge is taking root.',
        perk: 'Unlocks Parchment note theme',
        theme: 'parchment',
    },
    {
        id: 'voyager',
        name: 'Voyager',
        emoji: '🧭',
        minXp: 5000,
        color: '#7C3AED',
        bg: '#F5F3FF',
        border: '#DDD6FE',
        desc: 'Charting unknown territory.',
        perk: 'Unlocks Midnight note theme',
        theme: 'midnight',
    },
    {
        id: 'luminary',
        name: 'Luminary',
        emoji: '✨',
        minXp: 12000,
        color: '#D97706',
        bg: '#FFFBEB',
        border: '#FDE68A',
        desc: 'Your understanding shines.',
        perk: 'Unlocks Aurora note theme',
        theme: 'aurora',
    },
    {
        id: 'oracle',
        name: 'Oracle',
        emoji: '🔮',
        minXp: 25000,
        color: '#0F766E',
        bg: '#F0FDF4',
        border: '#BBF7D0',
        desc: 'You see what others miss.',
        perk: 'Unlocks Forest theme + XP ×1.5',
        theme: 'forest',
        multiplier: 1.5,
    },
    {
        id: 'sage',
        name: 'Sage',
        emoji: '🌟',
        minXp: 50000,
        color: '#9D174D',
        bg: '#FDF2F8',
        border: '#FBCFE8',
        desc: 'Mastery beyond measure.',
        perk: 'All themes + XP ×2 + Gold border',
        theme: 'sage',
        multiplier: 2,
    },
];

// ── Note theme definitions ────────────────────────────────────────────────────

export const NOTE_THEMES = {
    default: {
        name: 'Default',
        cardBg: '#FEFDF9',
        cardBorder: '#E8E0F0',
        rings: 'linear-gradient(180deg,#F5F0FF,#EDE9FE)',
        ringBorder: '#DDD6FE',
        ringDot: '#C4B5FD',
        marginLine: 'linear-gradient(180deg,#C4B5FD 0%,#A78BFA 50%,#C4B5FD 100%)',
        scrollBg: 'linear-gradient(160deg,#EEE8F8 0%,#F0EDF8 40%,#EBE5F5 100%)',
    },
    parchment: {
        name: 'Parchment',
        cardBg: '#FEFBF0',
        cardBorder: '#D4C9A8',
        rings: 'linear-gradient(180deg,#F5EFD0,#EDE4B8)',
        ringBorder: '#C9B87A',
        ringDot: '#B8A060',
        marginLine: 'linear-gradient(180deg,#C9B87A 0%,#A89050 50%,#C9B87A 100%)',
        scrollBg: 'linear-gradient(160deg,#F5F0DC 0%,#EDE8D0 40%,#E8E0C4 100%)',
    },
    midnight: {
        name: 'Midnight',
        cardBg: '#0F172A',
        cardBorder: '#334155',
        rings: 'linear-gradient(180deg,#1E293B,#1A2744)',
        ringBorder: '#3B4F7A',
        ringDot: '#4B6FA5',
        marginLine: 'linear-gradient(180deg,#3B4F7A 0%,#4B6FA5 50%,#3B4F7A 100%)',
        scrollBg: 'linear-gradient(160deg,#0B1120 0%,#0F1A30 40%,#0A1525 100%)',
        textColor: '#E2E8F0',
    },
    aurora: {
        name: 'Aurora',
        cardBg: '#FEFFFE',
        cardBorder: '#A7F3D0',
        rings: 'linear-gradient(180deg,#D1FAE5,#A7F3D0)',
        ringBorder: '#6EE7B7',
        ringDot: '#34D399',
        marginLine: 'linear-gradient(180deg,#6EE7B7 0%,#34D399 50%,#6EE7B7 100%)',
        scrollBg: 'linear-gradient(160deg,#ECFDF5 0%,#D1FAE5 40%,#A7F3D0 100%)',
    },
    forest: {
        name: 'Forest',
        cardBg: '#FAFEF7',
        cardBorder: '#BBF7D0',
        rings: 'linear-gradient(180deg,#DCFCE7,#BBF7D0)',
        ringBorder: '#86EFAC',
        ringDot: '#4ADE80',
        marginLine: 'linear-gradient(180deg,#86EFAC 0%,#4ADE80 50%,#86EFAC 100%)',
        scrollBg: 'linear-gradient(160deg,#F0FDF4 0%,#DCFCE7 40%,#BBF7D0 100%)',
    },
    sage: {
        name: 'Sage Gold',
        cardBg: '#FFFDF7',
        cardBorder: '#FDE68A',
        rings: 'linear-gradient(180deg,#FEF9C3,#FEF3A0)',
        ringBorder: '#FDE047',
        ringDot: '#EAB308',
        marginLine: 'linear-gradient(180deg,#FDE047 0%,#EAB308 50%,#FDE047 100%)',
        scrollBg: 'linear-gradient(160deg,#FFFBEB 0%,#FEF9C3 40%,#FEF3A0 100%)',
    },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function load() {
    const key = _storageKey();
    try {
        const current = JSON.parse(localStorage.getItem(key) || 'null');
        if (current) return { ...defaultData(), ...current };

        const legacy = JSON.parse(localStorage.getItem(LEGACY_STORAGE_KEY) || 'null');
        if (legacy) {
            const merged = { ...defaultData(), ...legacy };
            localStorage.setItem(key, JSON.stringify(merged));
            return merged;
        }
        return defaultData();
    } catch { return defaultData(); }
}

function defaultData() {
    return { xp: 0, quizzesCompleted: 0, correctAnswers: 0, totalAnswers: 0, doubtsAsked: 0, highlightsAdded: 0, activeTheme: 'default' };
}

function save(data) {
    try { localStorage.setItem(_storageKey(), JSON.stringify(data)); } catch { }
}

function _storageKey() {
    try {
        const raw = localStorage.getItem('ag_user');
        const user = raw ? JSON.parse(raw) : null;
        if (user?.id) return `${LEGACY_STORAGE_KEY}_${user.id}`;
    } catch { }
    return LEGACY_STORAGE_KEY;
}

function _hasMeaningfulProgress(d) {
    if (!d) return false;
    return (
        (Number(d.xp) || 0) > 0 ||
        (Number(d.quizzesCompleted) || 0) > 0 ||
        (Number(d.correctAnswers) || 0) > 0 ||
        (Number(d.totalAnswers) || 0) > 0 ||
        (Number(d.doubtsAsked) || 0) > 0 ||
        (Number(d.highlightsAdded) || 0) > 0 ||
        (d.activeTheme && d.activeTheme !== 'default')
    );
}

async function _fetchServerAura() {
    try {
        const res = await fetch(`${API}/api/aura`, { headers: authHeaders() });
        if (!res.ok) return null;
        const data = await res.json();
        return data?.aura || null;
    } catch {
        return null;
    }
}

async function _pushServerAura(auraData) {
    try {
        await fetch(`${API}/api/aura`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify(auraData),
        });
    } catch {
        // offline-safe: local persistence remains source-of-truth fallback
    }
}

export function getAuraData() { return load(); }

export function getBadge(xp) {
    // BADGES are in ascending order — walk until we find the highest earned
    let badge = BADGES[0];
    for (const b of BADGES) {
        if (xp >= b.minXp) badge = b;
        else break;
    }
    return badge;
}

export function getNextBadge(xp) {
    return BADGES.find(b => b.minXp > xp) || null;
}

export function getMultiplier(xp) {
    return getBadge(xp).multiplier || 1;
}

export function getUnlockedThemes(xp) {
    const themes = ['default'];
    for (const b of BADGES) {
        if (xp >= b.minXp && b.theme) themes.push(b.theme);
    }
    return themes;
}

export function getActiveTheme() {
    const data = load();
    const unlocked = getUnlockedThemes(data.xp);
    const theme = data.activeTheme || 'default';
    return unlocked.includes(theme) ? theme : 'default';
}

export function setActiveTheme(themeId) {
    const data = load();
    save({ ...data, activeTheme: themeId });
}

/**
 * Award XP for a given action.
 * 
 * IMPORTANT: For quiz_complete and high_score_bonus, `count` is ignored —
 * these are flat bonuses regardless of quiz length. For correct_answer,
 * count = number of correct answers to batch.
 */
export function awardXP(reason, count = 1) {
    const data = load();
    const multiplier = getMultiplier(data.xp);

    // Flat bonuses: never multiply by count
    const flatReasons = ['quiz_complete', 'high_score_bonus'];
    const baseXp = {
        correct_answer: 10,
        quiz_complete: 50,
        high_score_bonus: 25,
        highlight: 5,
        doubt: 15,
    }[reason] || 0;

    const effectiveCount = flatReasons.includes(reason) ? 1 : count;
    const gained = Math.round(baseXp * effectiveCount * multiplier);

    if (gained === 0) return { newXp: data.xp, gained: 0, badgeUp: null };

    const oldBadge = getBadge(data.xp);
    const newXp = data.xp + gained;
    const newBadge = getBadge(newXp);

    const updates = { xp: newXp };
    if (reason === 'correct_answer') {
        updates.correctAnswers = (data.correctAnswers || 0) + count;
        updates.totalAnswers = (data.totalAnswers || 0) + count;
    }
    if (reason === 'quiz_complete') updates.quizzesCompleted = (data.quizzesCompleted || 0) + 1;
    if (reason === 'highlight')     updates.highlightsAdded  = (data.highlightsAdded  || 0) + 1;
    if (reason === 'doubt')         updates.doubtsAsked      = (data.doubtsAsked      || 0) + 1;

    save({ ...data, ...updates });

    const badgeUp = newBadge.id !== oldBadge.id ? newBadge : null;
    return { newXp, gained, badgeUp };
}

// ── React hook ────────────────────────────────────────────────────────────────

export function useAura() {
    const [data, setData] = useState(load);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            const local = load();
            const remote = await _fetchServerAura();
            if (!remote) return;

            const remoteData = { ...defaultData(), ...remote };
            const remoteHas = _hasMeaningfulProgress(remoteData);
            const localHas = _hasMeaningfulProgress(local);

            if (!remoteHas && localHas) {
                await _pushServerAura(local);
                if (!cancelled) setData(local);
                return;
            }

            save(remoteData);
            if (!cancelled) setData(remoteData);
        })();
        return () => { cancelled = true; };
    }, []);

    const refresh = useCallback(() => setData(load()), []);

    const award = useCallback((reason, count = 1) => {
        const result = awardXP(reason, count);
        const latest = load();
        setData(latest);
        _pushServerAura(latest);
        return result;
    }, []);

    const badge         = getBadge(data.xp);
    const nextBadge     = getNextBadge(data.xp);
    const unlockedThemes = getUnlockedThemes(data.xp);
    const progressToNext = nextBadge
        ? Math.min(100, Math.round(((data.xp - badge.minXp) / (nextBadge.minXp - badge.minXp)) * 100))
        : 100;

    return {
        data,
        badge,
        nextBadge,
        unlockedThemes,
        progressToNext,
        award,
        refresh,
        setTheme: (t) => {
            setActiveTheme(t);
            const latest = load();
            setData(latest);
            _pushServerAura(latest);
        },
        activeTheme: getActiveTheme(),
    };
}
