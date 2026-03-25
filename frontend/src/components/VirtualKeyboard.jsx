/**
 * VirtualKeyboard — accessible floating on-screen keyboard.
 * Useful for tablet users, stylus input, and accessibility.
 * Dispatches real KeyboardEvents + inserts text via execCommand fallback.
 */
import React, { useState, useRef, useCallback, useEffect } from 'react';
import { X, Delete, ChevronUp, CornerDownLeft, Space } from 'lucide-react';

const ROWS_LOWER = [
    ['1','2','3','4','5','6','7','8','9','0'],
    ['q','w','e','r','t','y','u','i','o','p'],
    ['a','s','d','f','g','h','j','k','l'],
    ['z','x','c','v','b','n','m'],
];
const ROWS_UPPER = ROWS_LOWER.map(r => r.map(k => /[a-z]/.test(k) ? k.toUpperCase() : k));
const ROWS_SYM = [
    ['!','@','#','$','%','^','&','*','(',')'],
    ['-','_','=','+','[',']','{','}','\\','|'],
    [';',':','\'','"',',','.','<','>','/','?'],
    ['~','`'],
];

function Key({ label, onPress, wide, extraWide, icon, style }) {
    const base = {
        padding: wide ? '10px 14px' : extraWide ? '10px 28px' : '10px',
        minWidth: wide ? 56 : extraWide ? 80 : 38,
        height: 42,
        borderRadius: 8,
        border: '1px solid var(--border)',
        background: 'var(--surface)',
        color: 'var(--text)',
        cursor: 'pointer',
        fontSize: 14,
        fontWeight: 600,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        userSelect: 'none',
        transition: 'all 0.08s',
        fontFamily: 'inherit',
        flexShrink: 0,
        ...style,
    };
    return (
        <button
            style={base}
            onMouseDown={e => { e.preventDefault(); onPress(); }}
            onTouchStart={e => { e.preventDefault(); onPress(); }}
            onMouseEnter={e => { e.currentTarget.style.background = 'var(--ag-purple-bg)'; e.currentTarget.style.borderColor = 'var(--ag-purple)'; e.currentTarget.style.color = 'var(--ag-purple)'; }}
            onMouseLeave={e => { e.currentTarget.style.background = base.background; e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.color = 'var(--text)'; }}
        >
            {icon || label}
        </button>
    );
}

function insertText(text) {
    const el = document.activeElement;
    if (!el) return;
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        const start = el.selectionStart ?? el.value.length;
        const end   = el.selectionEnd   ?? el.value.length;
        const before = el.value.slice(0, start);
        const after  = el.value.slice(end);
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
            el.tagName === 'INPUT' ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype,
            'value'
        )?.set;
        if (nativeInputValueSetter) {
            nativeInputValueSetter.call(el, before + text + after);
            el.dispatchEvent(new Event('input', { bubbles: true }));
        }
        const newPos = start + text.length;
        el.setSelectionRange(newPos, newPos);
    } else if (el.isContentEditable) {
        document.execCommand('insertText', false, text);
    }
}

function deleteChar() {
    const el = document.activeElement;
    if (!el) return;
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        const start = el.selectionStart ?? el.value.length;
        const end   = el.selectionEnd   ?? el.value.length;
        if (start === end && start > 0) {
            const before = el.value.slice(0, start - 1);
            const after  = el.value.slice(end);
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                el.tagName === 'INPUT' ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype,
                'value'
            )?.set;
            if (nativeInputValueSetter) {
                nativeInputValueSetter.call(el, before + after);
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }
            el.setSelectionRange(start - 1, start - 1);
        } else if (start !== end) {
            const before = el.value.slice(0, start);
            const after  = el.value.slice(end);
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                el.tagName === 'INPUT' ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype,
                'value'
            )?.set;
            if (nativeInputValueSetter) {
                nativeInputValueSetter.call(el, before + after);
                el.dispatchEvent(new Event('input', { bubbles: true }));
            }
            el.setSelectionRange(start, start);
        }
    } else if (el.isContentEditable) {
        document.execCommand('delete');
    }
}

export default function VirtualKeyboard({ onClose }) {
    const [mode, setMode] = useState('lower'); // 'lower' | 'upper' | 'sym'
    const [capsLock, setCapsLock] = useState(false);
    const [pos, setPos] = useState({ x: null, y: null });
    const dragRef = useRef({ dragging: false, ox: 0, oy: 0 });
    const kbRef = useRef(null);

    // Default position: bottom-center
    useEffect(() => {
        if (kbRef.current) {
            const w = kbRef.current.offsetWidth || 460;
            setPos({ x: Math.max(8, (window.innerWidth - w) / 2), y: window.innerHeight - 260 });
        }
    }, []);

    const rows = mode === 'sym' ? ROWS_SYM : (mode === 'upper' || capsLock) ? ROWS_UPPER : ROWS_LOWER;

    const pressKey = useCallback((k) => {
        insertText(k);
        if (mode === 'upper' && !capsLock) setMode('lower');
    }, [mode, capsLock]);

    const onDragStart = (e) => {
        dragRef.current = { dragging: true, ox: e.clientX - pos.x, oy: e.clientY - pos.y };
        document.addEventListener('mousemove', onDragMove);
        document.addEventListener('mouseup', onDragEnd);
    };
    const onDragMove = (e) => {
        if (!dragRef.current.dragging) return;
        setPos({ x: Math.max(0, e.clientX - dragRef.current.ox), y: Math.max(0, e.clientY - dragRef.current.oy) });
    };
    const onDragEnd = () => {
        dragRef.current.dragging = false;
        document.removeEventListener('mousemove', onDragMove);
        document.removeEventListener('mouseup', onDragEnd);
    };

    return (
        <div
            ref={kbRef}
            style={{
                position: 'fixed',
                left: pos.x ?? '50%',
                top: pos.y ?? 'auto',
                bottom: pos.y === null ? 12 : 'auto',
                transform: pos.x === null ? 'translateX(-50%)' : 'none',
                zIndex: 9999,
                background: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 16,
                boxShadow: '0 8px 40px rgba(0,0,0,0.22)',
                padding: '10px 12px 14px',
                userSelect: 'none',
                minWidth: 380,
            }}
        >
            {/* Drag handle + header */}
            <div
                onMouseDown={onDragStart}
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10, cursor: 'grab', padding: '0 2px' }}
            >
                <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text3)', letterSpacing: '0.08em', textTransform: 'uppercase' }}>⌨ On-screen Keyboard</span>
                <button onMouseDown={e => { e.stopPropagation(); onClose(); }} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', padding: 4, borderRadius: 6, display: 'flex' }}>
                    <X size={14} />
                </button>
            </div>

            {/* Key rows */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                {rows.map((row, ri) => (
                    <div key={ri} style={{ display: 'flex', gap: 4, justifyContent: 'center' }}>
                        {row.map(k => <Key key={k} label={k} onPress={() => pressKey(k)} />)}
                    </div>
                ))}

                {/* Bottom control row */}
                <div style={{ display: 'flex', gap: 4, justifyContent: 'center', marginTop: 2 }}>
                    <Key
                        label={capsLock ? 'CAPS' : '⇧'}
                        wide
                        onPress={() => {
                            if (mode === 'lower') { setMode('upper'); setCapsLock(false); }
                            else if (mode === 'upper' && !capsLock) { setCapsLock(true); }
                            else { setMode('lower'); setCapsLock(false); }
                        }}
                        style={{ background: (mode === 'upper') ? 'var(--ag-purple-bg)' : undefined, borderColor: (mode === 'upper') ? 'var(--ag-purple)' : undefined, color: (mode === 'upper') ? 'var(--ag-purple)' : undefined }}
                    />
                    <Key label="123" wide onPress={() => setMode(m => m === 'sym' ? 'lower' : 'sym')}
                        style={{ background: mode === 'sym' ? 'var(--ag-purple-bg)' : undefined }} />
                    <Key label=" " extraWide onPress={() => insertText(' ')} style={{ flex: 1, minWidth: 120 }} />
                    <Key label="←" wide onPress={deleteChar} style={{ background: '#FEF2F2', borderColor: '#FECACA', color: 'var(--ag-red)' }} />
                    <Key label="↵" wide onPress={() => insertText('\n')}
                        style={{ background: 'var(--ag-purple-bg)', borderColor: 'var(--ag-purple)', color: 'var(--ag-purple)' }} />
                </div>
            </div>
        </div>
    );
}
