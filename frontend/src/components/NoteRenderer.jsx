import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import remarkGfm from 'remark-gfm';
import rehypeKatex from 'rehype-katex';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// NoteRenderer renders markdown + KaTeX.
// Highlights are applied as DOM marks by AnnotationLayer after render —
// this works for both plain text AND rendered LaTeX output.

export default function NoteRenderer({ content, onDoubtLink, fontSize = 16, darkMode = null }) {
    const isDark = darkMode ?? (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark');
    const mk = {
        h1({ children }) {
            return (
                <div style={{ marginBottom: 32, paddingBottom: 20, borderBottom: '2px solid #EDE9FE' }}>
                    <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.16em', color: 'var(--ag-purple)', marginBottom: 8, fontFamily: '"DM Sans",sans-serif', fontWeight: 700 }}>AuraGraph · Study Notes</div>
                    <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--text)', lineHeight: 1.2, fontFamily: '"Sora",sans-serif', letterSpacing: '-0.01em' }}>{children}</div>
                </div>
            );
        },
        h2({ children }) {
            return (
                <div style={{ marginTop: 40, marginBottom: 16 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, borderBottom: '1px solid var(--border)', paddingBottom: 10 }}>
                        <div style={{ width: 3, height: 20, borderRadius: 2, background: 'var(--ag-purple)', flexShrink: 0 }} />
                        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)', fontFamily: '"Sora",sans-serif' }}>{children}</div>
                    </div>
                </div>
            );
        },
        h3({ children }) {
            return (
                <div style={{ marginTop: 24, marginBottom: 12 }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, fontWeight: 600, color: 'var(--ag-purple)', fontFamily: '"DM Sans",sans-serif' }}>
                        <span style={{ width: 3, height: 14, borderRadius: 2, background: 'var(--ag-purple)', display: 'inline-block', flexShrink: 0 }} />
                        {children}
                    </span>
                </div>
            );
        },
        h4({ children }) {
            const text = typeof children === 'string' ? children : '';
            const isExercise = /^(exercise|example|problem|worked)/i.test(text);
            if (isExercise) return (
                <div className="nr-keep-together nr-callout" style={{ background: '#EFF6FF', border: '1px solid #BFDBFE', borderLeft: '3px solid #3B82F6', borderRadius: 8, padding: '10px 14px', margin: '14px 0' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                        <span style={{ fontSize: 13 }}>✏️</span>
                        <span style={{ fontSize: 11, fontWeight: 700, color: '#1D4ED8', letterSpacing: '0.05em', textTransform: 'uppercase', fontFamily: '"DM Sans",sans-serif' }}>Exercise</span>
                    </div>
                    <div style={{ fontSize: 13.5, color: '#1E3A5F', lineHeight: 1.7, fontFamily: '"DM Sans",sans-serif' }}>{children}</div>
                </div>
            );
            return <div style={{ marginTop: 18, marginBottom: 8, fontSize: 13, fontWeight: 600, color: 'var(--text2)', fontFamily: '"DM Sans",sans-serif' }}>{children}</div>;
        },
        code({ className, children }) {
            if (!className) return <code style={{ background: 'var(--ag-purple-bg)', color: 'var(--ag-purple-medium)', borderRadius: 5, padding: '2px 7px', fontSize: 13, fontFamily: '"JetBrains Mono","Courier New",monospace', fontWeight: 600, border: '1px solid #DDD6FE' }}>{children}</code>;
            return (
                <pre className="nr-keep-together" style={{ background: '#1E1B4B', border: '1px solid #312E81', borderRadius: 10, padding: '16px 20px', margin: '16px 0', fontFamily: '"JetBrains Mono","Courier New",monospace', fontSize: 13, lineHeight: 1.8, color: '#E0E7FF', overflowX: 'auto', whiteSpace: 'pre-wrap', boxShadow: '0 4px 16px rgba(79,70,229,0.12)' }}>
                    <code style={{ color: '#E0E7FF' }}>{children}</code>
                </pre>
            );
        },
        pre({ children }) { return <>{children}</>; },
        blockquote({ children }) {
            const extract = n => { if (!n) return ''; if (typeof n === 'string') return n; if (Array.isArray(n)) return n.map(extract).join(''); if (n?.props?.children) return extract(n.props.children); return ''; };
            const flat = extract(children);
            const isExamTip = flat.includes('Exam Tip');
            const isFormula = flat.includes('Formulas for this topic') || flat.includes('Formula');
            const isIntuition = flat.includes('💡') || flat.includes('Intuition') || flat.includes('Think of it');
            const isWarning = flat.includes('⚠️') || flat.includes('⚠') || flat.includes('offline mode') || flat.includes('Offline') || flat.includes('Unresolved Doubt');
            const isMutation = flat.includes('mutation') || flat.includes('Mutated');
            if (isExamTip) return (
                <div className="nr-keep-together nr-callout" style={{ background: isDark ? '#2A220F' : '#FFFBEB', border: `1px solid ${isDark ? '#7C5C16' : '#FDE68A'}`, borderRadius: 8, padding: '12px 14px', margin: '16px 0', display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                    <span style={{ fontSize: 16, flexShrink: 0 }}>🎯</span>
                    <div style={{ fontSize: 13.5, color: isDark ? '#FDE68A' : '#78350F', lineHeight: 1.6, fontFamily: '"DM Sans",sans-serif' }}>{children}</div>
                </div>
            );
            if (isFormula) return (
                <div className="nr-keep-together nr-callout nr-formula-box" style={{ background: isDark ? '#111827' : '#F8FAFC', border: `1px solid ${isDark ? '#334155' : '#E2E8F0'}`, borderLeft: '3px solid var(--ag-purple)', borderRadius: 8, padding: '12px 16px', margin: '16px 0' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}><span style={{ fontSize: 14 }}>🔢</span><span style={{ fontSize: 11, fontWeight: 700, color: isDark ? '#94A3B8' : '#475569', textTransform: 'uppercase' }}>Formula</span></div>
                    <div style={{ fontSize: 13.5, color: isDark ? '#E2E8F0' : '#1E293B', lineHeight: 1.7, fontFamily: '"DM Sans",sans-serif' }}>{children}</div>
                </div>
            );
            if (isIntuition) return (
                <div className="nr-keep-together nr-callout" style={{ background: isDark ? '#1E1B4B' : '#F5F3FF', border: `1px solid ${isDark ? '#4C1D95' : '#EDE9FE'}`, borderLeft: '3px solid var(--ag-purple)', borderRadius: 8, padding: '12px 16px', margin: '16px 0' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}><span style={{ fontSize: 14 }}>💡</span><span style={{ fontSize: 11, fontWeight: 700, color: 'var(--ag-purple)', textTransform: 'uppercase' }}>Intuition</span></div>
                    <div style={{ fontSize: 13.5, color: isDark ? '#DDD6FE' : '#1E0B3D', lineHeight: 1.7, fontFamily: '"DM Sans",sans-serif' }}>{children}</div>
                </div>
            );
            if (isWarning) return (
                <div className="nr-keep-together nr-callout" style={{ background: '#FEF2F2', border: '1px solid #FEE2E2', borderRadius: 8, padding: '12px 14px', margin: '12px 0', display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                    <span style={{ fontSize: 16, flexShrink: 0 }}>⚠️</span>
                    <div style={{ fontSize: 13, color: '#991B1B', lineHeight: 1.6, fontFamily: '"DM Sans",sans-serif' }}>{children}</div>
                </div>
            );
            if (isMutation) return (
                <div className="nr-keep-together nr-callout" style={{ background: '#F0FDF4', border: '1px solid #DCFCE7', borderRadius: 8, padding: '12px 14px', margin: '12px 0', display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                    <span style={{ fontSize: 16, flexShrink: 0 }}>✨</span>
                    <div style={{ fontSize: 13.5, color: '#166534', lineHeight: 1.6, fontFamily: '"DM Sans",sans-serif' }}>{children}</div>
                </div>
            );
            return (
                <div style={{ borderLeft: '3px solid var(--border)', paddingLeft: 16, margin: '14px 0', fontSize: 13.5, color: 'var(--text2)', lineHeight: 1.7, fontStyle: 'italic' }}>{children}</div>
            );
        },
        strong({ children }) { return <strong style={{ fontWeight: 700, color: 'inherit' }}>{children}</strong>; },
        em({ children }) { return <span style={{ fontStyle: 'italic', color: 'inherit' }}>{children}</span>; },
        hr() { return <div style={{ border: 'none', height: 1, background: 'linear-gradient(90deg,transparent,#DDD6FE 30%,#DDD6FE 70%,transparent)', margin: '32px 0' }} />; },
        p({ children }) { return <p style={{ marginBottom: 14, lineHeight: 'inherit', color: 'inherit', fontFamily: 'inherit', fontSize, letterSpacing: '0.005em' }}>{children}</p>; },
        ul({ children }) { return <ul style={{ paddingLeft: 0, margin: '12px 0 18px', lineHeight: 1.95, fontFamily: '"Source Serif 4",Georgia,serif', fontSize, color: 'inherit', listStyle: 'none' }}>{children}</ul>; },
        ol({ children }) { return <ol style={{ paddingLeft: 22, margin: '12px 0 18px', lineHeight: 1.95, fontFamily: '"Source Serif 4",Georgia,serif', fontSize, color: 'inherit' }}>{children}</ol>; },
        li({ children }) {
            return (
                <li style={{ marginBottom: 9, display: 'flex', gap: 11, alignItems: 'flex-start' }}>
                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--ag-purple)', flexShrink: 0, marginTop: '0.55em', display: 'inline-block' }} />
                    <span style={{ flex: 1 }}>{children}</span>
                </li>
            );
        },
        img({ src, alt }) {
            const isApiImage = src && (src.startsWith('/api/images/') || src.startsWith('http'));
            const fullSrc = src && src.startsWith('/api/') ? `${API}${src}` : src;
            if (isApiImage) {
                return (
                    <figure className="nr-keep-together" style={{ margin: '20px 0', textAlign: 'center' }}>
                        <img src={fullSrc} alt={alt || 'Figure'}
                            style={{ maxWidth: '100%', maxHeight: 420, borderRadius: 8, border: '1px solid #E4E4E7', boxShadow: '0 2px 8px rgba(0,0,0,0.08)', display: 'inline-block' }}
                            onError={e => { e.currentTarget.style.display = 'none'; e.currentTarget.nextSibling.style.display = 'flex'; }}
                        />
                        <div style={{ display: 'none', alignItems: 'center', gap: 10, background: '#F4F4F5', border: '1px solid #E4E4E7', borderRadius: 8, padding: '12px 16px', margin: '14px 0', color: '#71717A', fontSize: 13, fontStyle: 'italic', fontFamily: '"DM Sans",sans-serif' }}>
                            <span style={{ fontSize: 18 }}>🖼</span>
                            <span>{alt ? `Figure: ${alt}` : 'Figure'}</span>
                        </div>
                    </figure>
                );
            }
            return (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, background: '#F4F4F5', border: '1px solid #E4E4E7', borderRadius: 8, padding: '12px 16px', margin: '14px 0', color: '#71717A', fontSize: 13, fontStyle: 'italic', fontFamily: '"DM Sans",sans-serif' }}>
                    <span style={{ fontSize: 18 }}>🖼</span>
                    <span>{alt ? `Figure: ${alt}` : 'Figure'}</span>
                </div>
            );
        },
        a({ href, children }) {
            if (href?.startsWith('#doubt-')) {
                return (
                    <span onClick={() => onDoubtLink?.(href.slice(1))}
                        style={{ color: 'var(--ag-purple)', cursor: 'pointer', textDecoration: 'underline', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                        {children}
                    </span>
                );
            }
            return <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: '#2563EB', textDecoration: 'underline' }}>{children}</a>;
        },
        table({ children }) {
            return (
                <div className="nr-keep-together" style={{ overflowX: 'auto', margin: '18px 0', borderRadius: 10, border: isDark ? '1px solid #475569' : '1px solid #DDD6FE', boxShadow: isDark ? '0 4px 16px rgba(2,6,23,0.45)' : '0 2px 8px rgba(124,58,237,0.06)' }}>
                    <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 13.5, fontFamily: '"DM Sans",sans-serif' }}>{children}</table>
                </div>
            );
        },
        thead({ children }) { return <thead style={{ background: isDark ? 'linear-gradient(135deg,#1e293b,#0f172a)' : 'linear-gradient(135deg,#EDE9FE,#F5F3FF)' }}>{children}</thead>; },
        tbody({ children }) { return <tbody>{children}</tbody>; },
        tr({ children, node }) {
            const idx = node?.position?.start?.line ?? 0;
            return <tr style={{ borderBottom: isDark ? '1px solid #334155' : '1px solid #EDE9FE', background: isDark ? (idx % 2 === 0 ? '#0f172a' : '#111827') : (idx % 2 === 0 ? '#FAFAFA' : '#FFFFFF') }}>{children}</tr>;
        },
        th({ children }) { return <th style={{ padding: '10px 16px', textAlign: 'left', fontWeight: 700, color: isDark ? '#C4B5FD' : 'var(--ag-purple-deep)', borderBottom: isDark ? '2px solid #6366F1' : '2px solid #C4B5FD', whiteSpace: 'nowrap', fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{children}</th>; },
        td({ children }) { return <td style={{ padding: '9px 16px', color: isDark ? '#E5E7EB' : '#374151', verticalAlign: 'top', lineHeight: 1.6 }}>{children}</td>; },
    };

    const safeMath = (src) => src.replace(/\$([^$\n]+?)\$/g, (m, inner) =>
        inner.includes('|') ? '$' + inner.replace(/\|/g, '\\vert ') + '$' : m
    );

    const normalizeFigureMarkdown = (src) => {
        const normalizeLatexDelimiters = (text) =>
            String(text || '')
                .replace(/\\\(([\s\S]*?)\\\)/g, (_m, inner) => `$${inner}$`)
                .replace(/\\\[([\s\S]*?)\\\]/g, (_m, inner) => `$$\n${inner}\n$$`);

        const sanitizeAlt = (rawAlt) => {
            let alt = String(rawAlt || 'Figure').replace(/\s+/g, ' ').trim();
            alt = alt.replace(/\[/g, '(').replace(/\]/g, ')');
            alt = normalizeLatexDelimiters(alt);
            return alt || 'Figure';
        };

        // Legacy malformed notes may have [alt](/api/images/...) without leading '!'.
        let normalized = (src || '').replace(
            /(^|[^!])\[([\s\S]*?)\]\((\/api\/images\/[^)\s]+)\)/g,
            (_m, prefix, rawAlt, url) => `${prefix}![${sanitizeAlt(rawAlt)}](${url})`
        );

        // Canonicalize existing image markdown alts.
        normalized = normalized.replace(
            /!\[([\s\S]*?)\]\((\/api\/images\/[^)\s]+)\)/g,
            (_m, rawAlt, url) => `![${sanitizeAlt(rawAlt)}](${url})`
        );

        // Remove legacy duplicate image labels: ![alt](url) followed by *alt*.
        normalized = normalized.replace(
            /!\[([^\]]+)\]\((\/api\/images\/[^)\s]+)\)\s*\n\s*\*\s*\1\s*\*/g,
            (_m, rawAlt, url) => `![${rawAlt}](${url})`
        );

        const normalizeForCompare = (text) =>
            normalizeLatexDelimiters(String(text || ''))
                .replace(/\*+/g, '')
                .replace(/\s+/g, ' ')
                .trim()
                .toLowerCase();

        const lines = normalized.split('\n');
        const out = [];
        for (let i = 0; i < lines.length; i += 1) {
            const line = lines[i];
            const m = line.trim().match(/^!\[([\s\S]*?)\]\((\/api\/images\/[^)\s]+)\)$/);
            if (!m) {
                out.push(line);
                continue;
            }

            const alt = sanitizeAlt(m[1]);
            const url = m[2];
            const normAlt = normalizeForCompare(alt);
            const isAltLine = (ln) => {
                const t = (ln || '').trim();
                const plain = t.replace(/^\*+|\*+$/g, '').trim();
                return normalizeForCompare(plain) === normAlt;
            };

            out.push(`![${alt}](${url})`);

            // Find the next non-empty line after the image.
            let j = i + 1;
            while (j < lines.length && !lines[j].trim()) j += 1;

            // Always keep exactly one plain description line.
            out.push('');
            out.push(alt);

            if (j < lines.length && isAltLine(lines[j])) {
                // Skip all immediate duplicate copies (plain or italic),
                // including duplicates separated only by blank lines.
                let k = j + 1;
                while (k < lines.length) {
                    if (!lines[k].trim()) {
                        let t = k + 1;
                        while (t < lines.length && !lines[t].trim()) t += 1;
                        if (t < lines.length && isAltLine(lines[t])) {
                            k = t + 1;
                            continue;
                        }
                        break;
                    }
                    if (isAltLine(lines[k])) {
                        k += 1;
                        continue;
                    }
                    break;
                }
                i = k - 1;
            }
        }

        normalized = out.join('\n');

        return normalized;
    };

    return (
        <div className="note-render-root" style={{ color: 'var(--text)', fontFamily: '"Source Serif 4",Georgia,serif', lineHeight: 2.05 }}>
            <ReactMarkdown
                remarkPlugins={[remarkMath, remarkGfm]}
                rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false, errorColor: '#cc0000' }]]}
                components={mk}
            >
                {safeMath(normalizeFigureMarkdown(content || ''))}
            </ReactMarkdown>
        </div>
    );
}
