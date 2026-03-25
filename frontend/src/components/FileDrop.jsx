import React, { useRef, useState } from 'react';
import { BookOpen } from 'lucide-react';

const IMAGE_EXTS = new Set(['.jpg', '.jpeg', '.png', '.webp', '.bmp', '.heic', '.heif', '.tiff', '.tif']);

function isImage(f) {
    return IMAGE_EXTS.has(f.name.slice(f.name.lastIndexOf('.')).toLowerCase());
}

function fileIcon(f) {
    return isImage(f) ? '🖼️' : f.name.endsWith('.pptx') || f.name.endsWith('.ppt') ? '📊' : '📄';
}

export default function FileDrop({ label, icon, files, onFiles, imageOnly = false }) {
    const ref = useRef();
    const [drag, setDrag] = useState(false);

    const addFiles = (incoming) => {
        const valid = Array.from(incoming).filter(f =>
            imageOnly
                ? isImage(f)
                : (f.type === 'application/pdf' ||
                    f.name.endsWith('.pdf') ||
                    f.name.endsWith('.pptx') ||
                    f.name.endsWith('.ppt') ||
                    isImage(f))
        );
        if (valid.length) onFiles(prev => [...prev, ...valid]);
    };

    const DropIcon = icon || BookOpen;
    const hasFiles = files.length > 0;
    const totalMB = (files.reduce((s, f) => s + f.size, 0) / 1024 / 1024).toFixed(1);

    return (
        <div
            data-testid={`file-drop-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '')}`}
            onDragOver={e => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={e => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}
            style={{ border: `2px dashed ${drag ? 'var(--text)' : hasFiles ? 'var(--ag-emerald)' : 'var(--border2)'}`, borderRadius: 12, padding: 16, background: drag ? 'var(--surface2)' : hasFiles ? 'var(--zone-files-bg)' : 'var(--surface)', transition: 'all 0.15s', minHeight: 140 }}
        >
            <input
                ref={ref}
                type="file"
                accept={imageOnly
                    ? ".jpg,.jpeg,.png,.webp,.heic,.heif,.bmp,.tiff,.tif"
                    : ".pdf,.pptx,.ppt,.jpg,.jpeg,.png,.webp,.heic,.heif,.bmp,.tiff,.tif"}
                multiple
                style={{ display: 'none' }}
                onChange={e => addFiles(e.target.files)}
            />
            {!hasFiles ? (
                <div
                    onClick={() => ref.current?.click()}
                    style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', cursor: 'pointer', gap: 8, minHeight: 108 }}
                >
                    <DropIcon size={28} color="var(--border2)" />
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text2)', textAlign: 'center' }}>{label}</div>
                    <div style={{ fontSize: 11, color: 'var(--text3)' }}>PDF, PPTX{!imageOnly ? ', or image' : ''} · drag or click</div>
                </div>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                        <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--ag-emerald)' }}>{files.length} file{files.length > 1 ? 's' : ''} · {totalMB} MB</span>
                        <button onClick={() => ref.current?.click()} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 11, color: 'var(--text3)', textDecoration: 'underline', padding: 0 }}>+ Add more</button>
                    </div>
                    {files.map((f, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text2)', background: 'var(--surface)', borderRadius: 6, padding: '4px 8px' }}>
                            <span>{fileIcon(f)}</span>
                            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</span>
                            <button onClick={() => onFiles(prev => prev.filter((_, j) => j !== i))} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text3)', padding: 0, fontSize: 13, lineHeight: 1 }}>×</button>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
