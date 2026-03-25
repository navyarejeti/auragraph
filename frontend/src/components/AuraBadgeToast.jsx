/**
 * AuraBadgeToast — shown when user earns XP or levels up badge.
 * Two modes:
 *   xpMode: small pill "+25 Aura XP" with slide-up animation
 *   badgeMode: full celebration card with badge details
 */
import React, { useEffect, useState } from 'react';

export function XPToast({ gained, onDone }) {
    useEffect(() => {
        const t = setTimeout(onDone, 2200);
        return () => clearTimeout(t);
    }, [onDone]);

    return (
        <div style={{
            position: 'fixed', bottom: 80, right: 24, zIndex: 99999,
            background: 'linear-gradient(135deg,#7C3AED,#2563EB)',
            color: '#fff', borderRadius: 24, padding: '8px 16px',
            display: 'flex', alignItems: 'center', gap: 8,
            boxShadow: '0 4px 20px rgba(124,58,237,0.4)',
            fontSize: 13, fontWeight: 700, letterSpacing: '0.01em',
            animation: 'xpPop 0.3s cubic-bezier(0.34,1.56,0.64,1)',
            pointerEvents: 'none',
        }}>
            <span style={{ fontSize: 16 }}>⚡</span>
            +{gained} Aura XP
        </div>
    );
}

export function BadgeLevelUpToast({ badge, onDone }) {
    const [leaving, setLeaving] = useState(false);

    useEffect(() => {
        const t1 = setTimeout(() => setLeaving(true), 4000);
        const t2 = setTimeout(onDone, 4500);
        return () => { clearTimeout(t1); clearTimeout(t2); };
    }, [onDone]);

    return (
        <div style={{
            position: 'fixed', bottom: 80, right: 24, zIndex: 99999,
            background: badge.bg,
            border: `2px solid ${badge.border}`,
            borderRadius: 16, padding: '16px 20px',
            width: 280,
            boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
            animation: leaving ? 'slideDownFade 0.4s ease forwards' : 'slideUpFade 0.4s cubic-bezier(0.34,1.56,0.64,1)',
        }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: badge.color, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 8 }}>
                Badge Unlocked!
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                <div style={{ fontSize: 36, lineHeight: 1 }}>{badge.emoji}</div>
                <div>
                    <div style={{ fontSize: 18, fontWeight: 800, color: badge.color }}>{badge.name}</div>
                    <div style={{ fontSize: 11, color: '#6B7280', marginTop: 2 }}>{badge.desc}</div>
                </div>
            </div>
            <div style={{ fontSize: 11, color: badge.color, fontWeight: 600, background: 'rgba(255,255,255,0.6)', borderRadius: 8, padding: '6px 10px' }}>
                🎁 {badge.perk}
            </div>
        </div>
    );
}
