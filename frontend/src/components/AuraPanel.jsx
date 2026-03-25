/**
 * AuraPanel — full gamification hub shown as a modal.
 * Sections: badge progress, stats, theme picker, all badges.
 */
import React, { useState } from 'react';
import { X } from 'lucide-react';
import { BADGES, NOTE_THEMES, getUnlockedThemes } from '../hooks/useAura';

export default function AuraPanel({ aura, onClose, darkMode = null }) {
    const { data, badge, nextBadge, progressToNext, unlockedThemes, activeTheme, setTheme } = aura;
    const isDark = darkMode ?? (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark');
    const [tab, setTab] = useState('progress'); // 'progress' | 'badges' | 'themes'

    return (
        <div className="modal-backdrop" onClick={onClose}>
            <div className="modal fade-in-scale" onClick={e => e.stopPropagation()}
                style={{ maxWidth: 520, width: '96vw', padding: 0, overflow: 'hidden', borderRadius: 16 }}>

                {/* Header */}
                <div style={{
                    background: isDark
                        ? `linear-gradient(135deg, #0f172a 0%, #111827 48%, #1f2937 100%)`
                        : `linear-gradient(135deg, ${badge.bg}, white)`,
                    borderBottom: isDark ? '1px solid #334155' : `1px solid ${badge.border}`,
                    padding: '20px 24px 16px',
                }}>
                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                            <div style={{ fontSize: 44, lineHeight: 1 }}>{badge.emoji}</div>
                            <div>
                                <div style={{ fontSize: 11, fontWeight: 700, color: badge.color, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 2 }}>
                                    Aura Rank
                                </div>
                                <div style={{ fontSize: 22, fontWeight: 800, color: badge.color }}>{badge.name}</div>
                                <div style={{ fontSize: 12, color: isDark ? '#94A3B8' : '#6B7280', marginTop: 2 }}>{badge.desc}</div>
                            </div>
                        </div>
                        <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: isDark ? '#94A3B8' : '#9CA3AF', padding: 4 }}>
                            <X size={18} />
                        </button>
                    </div>

                    {/* XP bar */}
                    <div style={{ marginTop: 16 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, fontWeight: 600, color: isDark ? '#94A3B8' : '#6B7280', marginBottom: 6 }}>
                            <span style={{ color: badge.color, fontSize: 13, fontWeight: 800 }}>⚡ {data.xp.toLocaleString()} XP</span>
                            {nextBadge && <span>{nextBadge.minXp.toLocaleString()} XP — {nextBadge.name} {nextBadge.emoji}</span>}
                        </div>
                        <div style={{ height: 8, background: isDark ? 'rgba(148,163,184,0.28)' : 'rgba(0,0,0,0.08)', borderRadius: 4, overflow: 'hidden' }}>
                            <div style={{
                                height: '100%', borderRadius: 4,
                                background: `linear-gradient(90deg, ${badge.color}, ${badge.color}99)`,
                                width: `${progressToNext}%`,
                                transition: 'width 0.6s cubic-bezier(0.34,1.56,0.64,1)',
                            }} />
                        </div>
                        {nextBadge && (
                            <div style={{ fontSize: 10, color: isDark ? '#94A3B8' : '#9CA3AF', marginTop: 5 }}>
                                {nextBadge.minXp - data.xp} XP to {nextBadge.name}
                            </div>
                        )}
                    </div>
                </div>

                {/* Tabs */}
                <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
                    {[['progress', '📊 Stats'], ['badges', '🏅 Badges'], ['themes', '🎨 Themes']].map(([key, label]) => (
                        <button key={key} onClick={() => setTab(key)}
                            style={{ flex: 1, padding: '10px 4px', border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 12, fontWeight: 600, color: tab === key ? badge.color : 'var(--text3)', borderBottom: tab === key ? `2px solid ${badge.color}` : '2px solid transparent', transition: 'all 0.15s' }}>
                            {label}
                        </button>
                    ))}
                </div>

                {/* Body */}
                <div style={{ padding: '20px 24px', background: 'var(--bg)', maxHeight: 360, overflowY: 'auto' }}>
                    {tab === 'progress' && <StatsTab data={data} badge={badge} darkMode={isDark} />}
                    {tab === 'badges' && <BadgesTab data={data} badge={badge} darkMode={isDark} />}
                    {tab === 'themes' && <ThemesTab data={data} activeTheme={activeTheme} unlockedThemes={unlockedThemes} setTheme={setTheme} />}
                </div>
            </div>
        </div>
    );
}

function StatsTab({ data, badge, darkMode = null }) {
    const isDark = darkMode ?? (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark');
    const [profile, setProfile] = React.useState(null);
    React.useEffect(() => {
        fetch('/api/behaviour/profile', {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('ag_token') || ''}` }
        }).then(r => r.ok ? r.json() : null).then(d => d?.profile && setProfile(d.profile)).catch(() => {});
    }, []);

    const stats = [
        { label: 'Total Aura XP', value: data.xp.toLocaleString(), icon: '⚡', color: badge.color },
        { label: 'Quizzes Completed', value: data.quizzesCompleted || 0, icon: '🎯', color: '#2563EB' },
        { label: 'Correct Answers', value: data.correctAnswers || 0, icon: '✅', color: '#10B981' },
        { label: 'Accuracy', value: data.totalAnswers > 0 ? `${Math.round((data.correctAnswers / data.totalAnswers) * 100)}%` : '—', icon: '🎪', color: '#F59E0B' },
        { label: 'Doubts Resolved', value: data.doubtsAsked || 0, icon: '💡', color: '#7C3AED' },
        { label: 'Highlights Made', value: data.highlightsAdded || 0, icon: '🖍', color: '#EC4899' },
    ];
    return (
        <>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {stats.map(s => (
                <div key={s.label} style={{ background: 'var(--surface)', borderRadius: 10, padding: '12px 14px', border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: 18, marginBottom: 4 }}>{s.icon}</div>
                    <div style={{ fontSize: 20, fontWeight: 800, color: s.color }}>{s.value}</div>
                    <div style={{ fontSize: 10, color: 'var(--text3)', fontWeight: 600, marginTop: 2 }}>{s.label}</div>
                </div>
            ))}
        </div>

        {/* Learning profile derived from behaviour */}
        {profile && (profile.total_questions > 0 || profile.total_doubts > 0) && (
            <div style={{ marginTop: 16, padding: '12px 14px', background: 'var(--surface)', borderRadius: 10, border: '1px solid var(--border)' }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
                    Learning Profile
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, background: badge.bg, color: badge.color, border: `1px solid ${badge.border}`, borderRadius: 12, padding: '2px 10px' }}>
                        {profile.learning_style === 'conceptual' ? '🧠 Conceptual learner' :
                         profile.learning_style === 'visual'     ? '👁 Visual learner' :
                         profile.learning_style === 'practice'   ? '🎯 Practice-focused' :
                                                                    '⚖ Balanced learner'}
                    </span>
                    <span style={{ fontSize: 11, color: 'var(--text3)', borderRadius: 12, padding: '2px 10px', background: 'var(--bg)', border: '1px solid var(--border)' }}>
                        Preferred: {profile.preferred_proficiency}
                    </span>
                </div>
                {profile.weak_concepts?.length > 0 && (
                    <div style={{ marginBottom: 6 }}>
                        <div style={{ fontSize: 10, fontWeight: 700, color: isDark ? '#F87171' : '#EF4444', marginBottom: 4 }}>⚠ Needs work</div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                            {profile.weak_concepts.slice(0, 6).map(c => (
                                <span key={c} style={{ fontSize: 10, background: isDark ? '#3F1D1D' : '#FEF2F2', color: isDark ? '#FCA5A5' : '#991B1B', border: isDark ? '1px solid #7F1D1D' : '1px solid #FECACA', borderRadius: 8, padding: '1px 7px' }}>{c}</span>
                            ))}
                        </div>
                    </div>
                )}
                {profile.strong_concepts?.length > 0 && (
                    <div>
                        <div style={{ fontSize: 10, fontWeight: 700, color: isDark ? '#86EFAC' : '#10B981', marginBottom: 4 }}>✓ Strong areas</div>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                            {profile.strong_concepts.slice(0, 4).map(c => (
                                <span key={c} style={{ fontSize: 10, background: isDark ? '#052E16' : '#F0FDF4', color: isDark ? '#86EFAC' : '#065F46', border: isDark ? '1px solid #166534' : '1px solid #BBF7D0', borderRadius: 8, padding: '1px 7px' }}>{c}</span>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        )}
        </>
    );
}

function BadgesTab({ data, badge: currentBadge, darkMode = null }) {
    const isDark = darkMode ?? (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark');
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {BADGES.map(b => {
                const earned = data.xp >= b.minXp;
                return (
                    <div key={b.id} style={{
                        display: 'flex', alignItems: 'center', gap: 14, padding: '12px 14px',
                        borderRadius: 10, border: `1px solid ${earned ? b.border : 'var(--border)'}`,
                        background: earned ? b.bg : 'var(--surface)',
                        opacity: earned ? 1 : 0.5,
                        transition: 'all 0.2s',
                    }}>
                        <div style={{ fontSize: 28, filter: earned ? 'none' : 'grayscale(1)' }}>{b.emoji}</div>
                        <div style={{ flex: 1 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                <span style={{ fontSize: 14, fontWeight: 700, color: earned ? b.color : 'var(--text3)' }}>{b.name}</span>
                                {b.id === currentBadge.id && <span style={{ fontSize: 9, fontWeight: 700, background: b.color, color: '#fff', borderRadius: 6, padding: '1px 6px' }}>CURRENT</span>}
                                {earned && b.id !== currentBadge.id && <span style={{ fontSize: 9, fontWeight: 700, color: b.color }}>✓ EARNED</span>}
                            </div>
                            <div style={{ fontSize: 11, color: earned ? (isDark ? '#94A3B8' : '#6B7280') : 'var(--text3)', marginTop: 1 }}>{b.perk}</div>
                        </div>
                        <div style={{ fontSize: 11, fontWeight: 700, color: earned ? b.color : 'var(--text3)', whiteSpace: 'nowrap' }}>
                            {b.minXp === 0 ? 'Start' : `${b.minXp.toLocaleString()} XP`}
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

function ThemesTab({ data, activeTheme, unlockedThemes, setTheme }) {
    return (
        <div>
            <p style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 14 }}>
                Earn Aura XP to unlock new note themes. Your notes, your style.
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                {Object.entries(NOTE_THEMES).map(([id, theme]) => {
                    const unlocked = unlockedThemes.includes(id);
                    const active = activeTheme === id;
                    // Find which badge unlocks it
                    const unlockBadge = BADGES.find(b => b.theme === id);
                    return (
                        <button key={id} onClick={() => unlocked && setTheme(id)} disabled={!unlocked}
                            style={{
                                position: 'relative', padding: '12px', borderRadius: 10, cursor: unlocked ? 'pointer' : 'not-allowed',
                                border: active ? '2px solid #7C3AED' : '1px solid var(--border)',
                                background: unlocked ? theme.cardBg : 'var(--surface)',
                                opacity: unlocked ? 1 : 0.5,
                                textAlign: 'left', transition: 'all 0.15s',
                                boxShadow: active ? '0 0 0 3px rgba(124,58,237,0.2)' : 'none',
                            }}>
                            {/* Theme preview */}
                            <div style={{ height: 32, borderRadius: 6, marginBottom: 8, background: theme.scrollBg, border: `1px solid ${theme.cardBorder}`, overflow: 'hidden', display: 'flex' }}>
                                <div style={{ width: 16, background: theme.rings, borderRight: `2px solid ${theme.ringBorder}` }} />
                                <div style={{ flex: 1, background: theme.cardBg }} />
                            </div>
                            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>{theme.name}</div>
                            {!unlocked && unlockBadge && (
                                <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>
                                    🔒 Unlock at {unlockBadge.name}
                                </div>
                            )}
                            {active && (
                                <div style={{ position: 'absolute', top: 8, right: 8, fontSize: 10, fontWeight: 700, background: '#7C3AED', color: '#fff', borderRadius: 6, padding: '1px 6px' }}>
                                    ACTIVE
                                </div>
                            )}
                        </button>
                    );
                })}
            </div>
        </div>
    );
}
