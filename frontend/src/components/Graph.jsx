import React from 'react';
import { Brain } from 'lucide-react';

/** Status → { fill, ring } colour map — used by KnowledgeGraph and KnowledgePanel */
export const SC = {
    mastered:  { fill: 'var(--ag-emerald)', ring: '#6EE7B7' },
    partial:   { fill: 'var(--ag-gold)', ring: '#FCD34D' },
    struggling:{ fill: 'var(--ag-red)', ring: '#FCA5A5' },
};

// ── GalaxyGraph (animated canvas) ─────────────────────────────────────────────
export function GalaxyGraph({ nodes, edges, onNodeClick, selectedNodeId }) {
    const canvasRef = React.useRef();
    const animRef   = React.useRef();
    const starsRef  = React.useRef([]);
    const W = 280, H = 360;

    React.useEffect(() => {
        starsRef.current = Array.from({ length: 28 }, () => ({
            x: Math.random() * W, y: Math.random() * H,
            r: Math.random() * 1.2 + 0.3,
            alpha: Math.random() * 0.7 + 0.3,
            speed: Math.random() * 0.008 + 0.003,
            phase: Math.random() * Math.PI * 2,
        }));
    }, []);

    React.useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        let t = 0;
        const getPos = n => ({ x: (n.x / 100) * (W - 60) + 30, y: (n.y / 100) * (H - 60) + 30 });
        const statusColor = { mastered: 'var(--ag-emerald)', partial: 'var(--ag-gold)', struggling: 'var(--ag-red)' };
        const nodeById = Object.fromEntries((nodes || []).map(n => [n.id, n]));

        const draw = () => {
            t += 0.016;
            ctx.clearRect(0, 0, W, H);
            const bg = ctx.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, Math.max(W, H) / 1.2);
            bg.addColorStop(0, isDark ? '#08081A' : '#0a0a1e');
            bg.addColorStop(1, isDark ? '#020208' : '#050510');
            ctx.fillStyle = bg;
            ctx.fillRect(0, 0, W, H);

            for (const s of starsRef.current) {
                const a = s.alpha * (0.5 + 0.5 * Math.sin(t * s.speed * 60 + s.phase));
                ctx.beginPath();
                ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
                ctx.fillStyle = `rgba(255,255,255,${a})`;
                ctx.fill();
            }

            for (const e of (edges || [])) {
                const s = nodeById[e[0]], d = nodeById[e[1]];
                if (!s || !d) continue;
                const sp = getPos(s), dp = getPos(d);
                ctx.beginPath();
                ctx.moveTo(sp.x, sp.y);
                ctx.lineTo(dp.x, dp.y);
                const grad = ctx.createLinearGradient(sp.x, sp.y, dp.x, dp.y);
                grad.addColorStop(0, statusColor[s.status] + (isDark ? 'AA' : '66'));
                grad.addColorStop(1, statusColor[d.status] + (isDark ? 'AA' : '66'));
                ctx.strokeStyle = grad;
                ctx.lineWidth = isDark ? 1.6 : 1.2;
                ctx.setLineDash([4, 4]);
                ctx.stroke();
                ctx.setLineDash([]);
            }

            for (const n of (nodes || [])) {
                const { x, y } = getPos(n);
                const c = statusColor[n.status] || 'var(--ag-gold)';
                const isSel = n.id === selectedNodeId;
                const pulse = 1 + 0.12 * Math.sin(t * 2 + (n.x + n.y) / 40);
                const glowR = (isSel ? 22 : 16) * pulse;
                const glowGrad = ctx.createRadialGradient(x, y, 0, x, y, glowR);
                glowGrad.addColorStop(0, c + '44');
                glowGrad.addColorStop(1, c + '00');
                ctx.beginPath();
                ctx.arc(x, y, glowR, 0, Math.PI * 2);
                ctx.fillStyle = glowGrad;
                ctx.fill();
                if (isSel) {
                    ctx.beginPath();
                    ctx.arc(x, y, 18, 0, Math.PI * 2);
                    ctx.strokeStyle = c + 'CC';
                    ctx.lineWidth = 2;
                    ctx.setLineDash([3, 3]);
                    ctx.stroke();
                    ctx.setLineDash([]);
                }
                const orbGrad = ctx.createRadialGradient(x - 3, y - 3, 1, x, y, 10);
                orbGrad.addColorStop(0, c + 'FF');
                orbGrad.addColorStop(0.6, c + 'CC');
                orbGrad.addColorStop(1, c + '88');
                ctx.beginPath();
                ctx.arc(x, y, 10, 0, Math.PI * 2);
                ctx.fillStyle = orbGrad;
                ctx.fill();
                if ((n.mutation_count || 0) > 0) {
                    ctx.beginPath();
                    ctx.arc(x + 8, y - 8, 5, 0, Math.PI * 2);
                    ctx.fillStyle = 'var(--ag-purple)';
                    ctx.fill();
                    ctx.fillStyle = '#fff';
                    ctx.font = 'bold 7px Space Grotesk, sans-serif';
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'middle';
                    ctx.fillText(n.mutation_count, x + 8, y - 8);
                }
                const lbl = n.label.length > 14 ? n.label.slice(0, 12) + '…' : n.label;
                ctx.font = `${isSel ? 'bold ' : ''}9px Space Grotesk, sans-serif`;
                ctx.textAlign = 'center';
                ctx.textBaseline = 'top';
                ctx.fillStyle = isSel ? '#fff' : 'rgba(255,255,255,0.8)';
                ctx.fillText(lbl, x, y + 13);
            }
            animRef.current = requestAnimationFrame(draw);
        };
        draw();
        return () => cancelAnimationFrame(animRef.current);
    }, [nodes, edges, selectedNodeId]);

    const handleClick = (e) => {
        if (!nodes?.length) return;
        const rect = canvasRef.current.getBoundingClientRect();
        const scaleX = W / rect.width, scaleY = H / rect.height;
        const mx = (e.clientX - rect.left) * scaleX;
        const my = (e.clientY - rect.top) * scaleY;
        const getPos = n => ({ x: (n.x / 100) * (W - 60) + 30, y: (n.y / 100) * (H - 60) + 30 });
        const hit = nodes.find(n => { const p = getPos(n); return Math.hypot(p.x - mx, p.y - my) < 14; });
        if (hit) onNodeClick?.(hit);
    };

    if (!nodes?.length) return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 200, color: 'var(--text3)', fontSize: 12, textAlign: 'center', padding: '0 16px' }}>
            <Brain size={28} color="var(--border2)" style={{ marginBottom: 10 }} />
            <p>Concept graph appears after generating notes.</p>
        </div>
    );

    return (
        <canvas ref={canvasRef} width={W} height={H}
            className="galaxy-canvas"
            style={{ display: 'block', width: '100%', cursor: 'pointer', borderRadius: 12 }}
            onClick={handleClick}
        />
    );
}

// ── KnowledgeGraph (SVG fallback) ─────────────────────────────────────────────
export function KnowledgeGraph({ nodes, edges, onNodeClick, selectedNodeId, highlightNodeIds = [] }) {
    const W = 280, H = 400;
    const isDark = typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'dark';
    const highlightSet = new Set(highlightNodeIds);
    if (!nodes?.length) return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 200, color: 'var(--text3)', fontSize: 12, textAlign: 'center', padding: '0 16px' }}>
            <Brain size={28} color="var(--border2)" style={{ marginBottom: 10 }} />
            <p>Concept graph appears after generating notes.</p>
        </div>
    );
    const getPos = n => ({ cx: (n.x / 100) * (W - 60) + 30, cy: (n.y / 100) * (H - 60) + 30 });
    const nodeById = Object.fromEntries(nodes.map(n => [n.id, n]));
    return (
        <svg width={W} height={H} style={{ display: 'block', width: '100%', height: '100%' }} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet">
            <defs>
                {nodes.map(n => {
                    const c = SC[n.status] || SC.partial;
                    return (
                        <radialGradient key={n.id} id={`g-${n.id}`} cx="50%" cy="50%" r="50%">
                            <stop offset="0%" stopColor={c.ring} stopOpacity="0.6" />
                            <stop offset="100%" stopColor={c.fill} stopOpacity="1" />
                        </radialGradient>
                    );
                })}
            </defs>
            {edges.map((e, i) => {
                const s = nodeById[e[0]], d = nodeById[e[1]];
                if (!s || !d) return null;
                const sp = getPos(s), dp = getPos(d);
                return <line key={i} x1={sp.cx} y1={sp.cy} x2={dp.cx} y2={dp.cy} stroke={isDark ? '#64748B' : 'var(--border2)'} strokeWidth={isDark ? 1.8 : 1.5} strokeDasharray="4,3" opacity={isDark ? 0.9 : 0.7} />;
            })}
            {nodes.map(n => {
                const c = SC[n.status] || SC.partial;
                const { cx, cy } = getPos(n);
                const sel = n.id === selectedNodeId;
                const isOnPage = highlightSet.has(n.id);
                // Show short label on node, full label on hover via title on the <g>
                const displayLabel = n.label.length > 18 ? n.label.slice(0, 16) + '…' : n.label;
                return (
                    <g key={n.id} style={{ cursor: 'pointer' }} onClick={() => onNodeClick(n)}>
                        <title>{n.full_label || n.label}</title>
                        {/* Page-topic highlight ring */}
                        {isOnPage && !sel && (
                            <circle cx={cx} cy={cy} r={22} fill="none" stroke="#3B82F6" strokeWidth={1.5} opacity={0.6} strokeDasharray="3,2" />
                        )}
                        {sel && <circle cx={cx} cy={cy} r={20} fill="none" stroke={c.fill} strokeWidth={2} opacity={0.5} strokeDasharray="3,2" />}
                        <circle cx={cx} cy={cy} r={17} fill={isOnPage ? '#3B82F620' : c.ring} opacity={sel ? 0.4 : isOnPage ? 0.9 : 0.2} />
                        <circle cx={cx} cy={cy} r={12} fill={`url(#g-${n.id})`} stroke={sel ? c.fill : isOnPage ? '#3B82F6' : 'transparent'} strokeWidth={isOnPage ? 1.5 : 2} />
                        <text x={cx} y={cy + 24} textAnchor="middle" fontSize={9} fill={isOnPage ? '#2563EB' : 'var(--text2)'} fontWeight={sel || isOnPage ? 700 : 500} style={{ pointerEvents: 'none', userSelect: 'none' }}>{displayLabel}</text>
                        {(n.mutation_count || 0) > 0 && (
                            <g>
                                <circle cx={cx + 9} cy={cy - 9} r={5.5} fill="var(--ag-purple)" />
                                <text x={cx + 9} y={cy - 9 + 4} textAnchor="middle" fontSize={7} fill="#fff" fontWeight={700} style={{ pointerEvents: 'none', userSelect: 'none' }}>{n.mutation_count}</text>
                            </g>
                        )}
                    </g>
                );
            })}
        </svg>
    );
}
