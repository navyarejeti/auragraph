import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useSidebar } from '../hooks/useSidebar';
import { useUndoStack } from '../hooks/useUndoStack';
import { useDoubtsLog } from '../hooks/useDoubtsLog';

// ─── useSidebar ─────────────────────────────────────────────────────────────
describe('useSidebar', () => {
    it('initialises with sidebar open and width 310', () => {
        const { result } = renderHook(() => useSidebar());
        expect(result.current.sidebarOpen).toBe(true);
        expect(result.current.sidebarWidth).toBe(310);
    });

    it('toggles sidebarOpen via setSidebarOpen', () => {
        const { result } = renderHook(() => useSidebar());
        act(() => result.current.setSidebarOpen(false));
        expect(result.current.sidebarOpen).toBe(false);
    });

    it('exposes startResizeSidebar as a function', () => {
        const { result } = renderHook(() => useSidebar());
        expect(typeof result.current.startResizeSidebar).toBe('function');
    });
});

// ─── useUndoStack ────────────────────────────────────────────────────────────
describe('useUndoStack', () => {
    it('starts with no undo toast', () => {
        const { result } = renderHook(() => useUndoStack({}));
        expect(result.current.undoToast).toBeNull();
    });

    it('pushUndo sets undoToast with correct fields', () => {
        const { result } = renderHook(() => useUndoStack({}));
        act(() => result.current.pushUndo('prev note', 'Practitioner', 'Page 1 mutated'));
        expect(result.current.undoToast).toMatchObject({
            note: 'prev note',
            prof: 'Practitioner',
            label: 'Page 1 mutated',
        });
        expect(result.current.undoToast.expiresAt).toBeGreaterThan(Date.now());
    });

    it('dismissUndo clears undoToast', () => {
        const { result } = renderHook(() => useUndoStack({}));
        act(() => result.current.pushUndo('note', 'Expert', 'test'));
        act(() => result.current.dismissUndo());
        expect(result.current.undoToast).toBeNull();
    });

    it('handleUndoCommit calls setNote + setProf + saveNote', async () => {
        const setNote = vi.fn();
        const setProf = vi.fn();
        const saveNote = vi.fn().mockResolvedValue(undefined);
        const { result } = renderHook(() => useUndoStack({ saveNote, setNote, setProf }));

        act(() => result.current.pushUndo('restored note', 'Foundations', 'undo label'));
        await act(async () => result.current.handleUndoCommit());

        expect(setNote).toHaveBeenCalledWith('restored note');
        expect(setProf).toHaveBeenCalledWith('Foundations');
        expect(saveNote).toHaveBeenCalledWith('restored note', 'Foundations');
        expect(result.current.undoToast).toBeNull();
    });

    it('handleUndoCommit is a no-op when undoToast is null', async () => {
        const saveNote = vi.fn();
        const { result } = renderHook(() => useUndoStack({ saveNote }));
        await act(async () => result.current.handleUndoCommit());
        expect(saveNote).not.toHaveBeenCalled();
    });
});

// ─── useDoubtsLog ────────────────────────────────────────────────────────────
describe('useDoubtsLog', () => {
    beforeEach(() => localStorage.clear());

    it('initialises with empty array when nothing stored', () => {
        const { result } = renderHook(() => useDoubtsLog('nb-new'));
        expect(result.current.doubtsLog).toEqual([]);
    });

    it('initialises from localStorage when doubts exist', () => {
        const existing = [{ id: 99, doubt: 'test doubt', pageIdx: 0 }];
        localStorage.setItem('ag_doubts_nb-existing', JSON.stringify(existing));
        const { result } = renderHook(() => useDoubtsLog('nb-existing'));
        expect(result.current.doubtsLog).toEqual(existing);
    });

    it('setDoubtsLog updates the log', () => {
        const { result } = renderHook(() => useDoubtsLog('nb-update'));
        act(() => result.current.setDoubtsLog([{ id: 1 }]));
        expect(result.current.doubtsLog).toEqual([{ id: 1 }]);
    });
});
