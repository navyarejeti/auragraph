import React, { useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { removeToast } from '../store';

// ── Per-kind visual tokens ───────────────────────────────────────────────────
const STYLES = {
    error:   { bg: '#FEF2F2', border: '#FCA5A5', text: '#991B1B', icon: '✕' },
    warning: { bg: '#FFFBEB', border: '#FCD34D', text: '#92400E', icon: '⚠' },
    success: { bg: '#F0FDF4', border: '#86EFAC', text: '#166534', icon: '✓' },
    info:    { bg: '#EFF6FF', border: '#93C5FD', text: '#1E3A8A', icon: 'ℹ' },
};

function ToastItem({ toast }) {
    const dispatch = useDispatch();
    const { bg, border, text, icon } = STYLES[toast.kind] || STYLES.error;

    useEffect(() => {
        const t = setTimeout(() => dispatch(removeToast(toast.id)), toast.duration || 6000);
        return () => clearTimeout(t);
    }, [toast.id, toast.duration, dispatch]);

    return (
        <div
            role="alert"
            style={{
                display: 'flex', alignItems: 'flex-start', gap: 10,
                background: bg, border: `1px solid ${border}`,
                borderRadius: 10, padding: '11px 14px',
                minWidth: 280, maxWidth: 420,
                boxShadow: '0 4px 14px rgba(0,0,0,0.13)',
                animation: 'ag-slide-in 0.18s ease',
            }}
        >
            <span style={{ fontSize: 14, fontWeight: 700, color: text, flexShrink: 0, marginTop: 1 }}>
                {icon}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
                {toast.title && (
                    <div style={{ fontWeight: 700, fontSize: 13, color: text, marginBottom: 3 }}>
                        {toast.title}
                    </div>
                )}
                <div style={{ fontSize: 13, color: text, opacity: 0.88, wordBreak: 'break-word' }}>
                    {toast.message}
                </div>
            </div>
            <button
                onClick={() => dispatch(removeToast(toast.id))}
                aria-label="Dismiss"
                style={{
                    background: 'none', border: 'none', cursor: 'pointer',
                    padding: '0 2px', fontSize: 16, color: text, opacity: 0.5,
                    flexShrink: 0, lineHeight: 1,
                }}
            >×</button>
        </div>
    );
}

export function ToastContainer() {
    const toasts = useSelector(s => s.toasts);
    if (!toasts.length) return null;

    return (
        <>
            <style>{`@keyframes ag-slide-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}`}</style>
            <div
                aria-live="polite"
                style={{
                    position: 'fixed', bottom: 24, right: 24, zIndex: 9999,
                    display: 'flex', flexDirection: 'column', gap: 8,
                    alignItems: 'flex-end', pointerEvents: 'none',
                }}
            >
                {toasts.map(t => (
                    <div key={t.id} style={{ pointerEvents: 'auto' }}>
                        <ToastItem toast={t} />
                    </div>
                ))}
            </div>
        </>
    );
}
