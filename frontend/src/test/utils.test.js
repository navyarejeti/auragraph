import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { authHeaders, loadDoubts, saveDoubts } from '../components/utils';

describe('authHeaders', () => {
    beforeEach(() => localStorage.clear());

    it('returns Bearer token from localStorage', () => {
        localStorage.setItem('ag_token', 'test-token-123');
        expect(authHeaders()).toEqual({ Authorization: 'Bearer test-token-123' });
    });

    it('falls back to demo-token when nothing stored', () => {
        expect(authHeaders()).toEqual({ Authorization: 'Bearer demo-token' });
    });
});

describe('loadDoubts / saveDoubts', () => {
    beforeEach(() => localStorage.clear());

    it('returns empty array for unknown notebook', () => {
        expect(loadDoubts('unknown-id')).toEqual([]);
    });

    it('round-trips doubts correctly', () => {
        const doubts = [
            { id: 1, doubt: 'What is a Fourier transform?', insight: 'Decomposes signals.', pageIdx: 0, time: '10:00', success: true },
        ];
        saveDoubts('nb1', doubts);
        expect(loadDoubts('nb1')).toEqual(doubts);
    });

    it('returns empty array if stored value is corrupt JSON', () => {
        localStorage.setItem('ag_doubts_nb2', '{invalid');
        expect(loadDoubts('nb2')).toEqual([]);
    });

    it('namespaces doubts per notebook', () => {
        saveDoubts('nb-a', [{ id: 1 }]);
        saveDoubts('nb-b', [{ id: 2 }]);
        expect(loadDoubts('nb-a')[0].id).toBe(1);
        expect(loadDoubts('nb-b')[0].id).toBe(2);
    });
});
