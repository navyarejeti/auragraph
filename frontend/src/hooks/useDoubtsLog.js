import { useState, useEffect, useCallback, useRef } from 'react';
import { API, authHeaders, loadDoubts, saveDoubts } from '../components/utils';

/**
 * Manages the doubts/Q&A log for a notebook.
 *
 * Persistence fix: doubts are now synced to the backend DB, so they survive
 * across devices and browser storage clears. localStorage is kept as an
 * offline cache/fallback.
 *
 * @param {string} id - Notebook ID
 */
export function useDoubtsLog(id) {
    const [doubtsLog, setDoubtsLogRaw] = useState(() => loadDoubts(id));
    const synced = useRef(false);

    // On mount: load from backend (authoritative source), fall back to localStorage
    useEffect(() => {
        if (!id || synced.current) return;
        synced.current = true;
        fetch(`${API}/api/notebooks/${id}/doubts`, { headers: authHeaders() })
            .then(r => r.ok ? r.json() : null)
            .then(data => {
                if (data?.doubts?.length) {
                    setDoubtsLogRaw(data.doubts);
                    saveDoubts(id, data.doubts);
                }
            })
            .catch(() => {/* offline — localStorage already loaded */});
    }, [id]);

    /** Persist one entry to backend + local cache. */
    const addDoubt = useCallback((entry) => {
        setDoubtsLogRaw(prev => {
            const updated = [entry, ...prev.filter(d => d.id !== entry.id)];
            saveDoubts(id, updated);
            return updated;
        });
        fetch(`${API}/api/notebooks/${id}/doubts`, {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: JSON.stringify(entry),
        }).catch(() => {});
    }, [id]);

    /**
     * Drop-in replacement for plain setDoubtsLog.
     * Syncs any newly-added entries to the backend.
     */
    const setDoubtsLog = useCallback((updater) => {
        setDoubtsLogRaw(prev => {
            const next = typeof updater === 'function' ? updater(prev) : updater;
            saveDoubts(id, next);
            const prevIds = new Set(prev.map(d => d.id));
            next.filter(d => !prevIds.has(d.id)).forEach(entry => {
                fetch(`${API}/api/notebooks/${id}/doubts`, {
                    method: 'POST',
                    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
                    body: JSON.stringify(entry),
                }).catch(() => {});
            });
            return next;
        });
    }, [id]);

    return { doubtsLog, setDoubtsLog, addDoubt };
}
