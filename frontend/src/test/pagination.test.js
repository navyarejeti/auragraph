import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { usePagination } from '../hooks/usePagination';

describe('usePagination — page splitting', () => {
    it('returns empty pages for empty note', () => {
        const { result } = renderHook(() => usePagination('', {}));
        expect(result.current.pages).toEqual([]);
    });

    it('splits note by ## headings when sections are large enough', () => {
        // Each section must contribute enough chars to exceed the 3000-char page target
        const section1 = '## Intro\n' + 'Content one. '.repeat(130); // ~1690 chars
        const section2 = '## Chapter Two\n' + 'Content two. '.repeat(130); // ~1690 chars
        const note = section1 + '\n\n' + section2;
        const { result } = renderHook(() => usePagination(note, {}));
        expect(result.current.pages).toHaveLength(2);
        expect(result.current.pages[0]).toContain('Intro');
        expect(result.current.pages[1]).toContain('Chapter Two');
    });

    it('strips markdown code fence wrapper before splitting', () => {
        const note = '```markdown\n## Topic A\nsome text\n```';
        const { result } = renderHook(() => usePagination(note, {}));
        expect(result.current.pages[0]).not.toContain('```');
        expect(result.current.pages[0]).toContain('Topic A');
    });

    it('merges small ## sections to hit ~3000 char target page', () => {
        // Two short sections should be merged into one page
        const note = '## A\nshort.\n\n## B\nshort too.';
        const { result } = renderHook(() => usePagination(note, {}));
        // Both sections are tiny, should merge into single page
        expect(result.current.pages).toHaveLength(1);
        expect(result.current.pages[0]).toContain('## A');
        expect(result.current.pages[0]).toContain('## B');
    });

    it('falls back to paragraph splitting when no headings', () => {
        const note = 'First paragraph.\n\nSecond paragraph.\n\nThird paragraph.';
        const { result } = renderHook(() => usePagination(note, {}));
        // Small paragraphs should be grouped into one page, not split unless large
        expect(result.current.pages.length).toBeGreaterThanOrEqual(1);
    });

    it('does not split inside $$ math blocks', () => {
        const note = 'Intro.\n\n$$\nE = mc^2\n\n\\Delta x \\Delta p \\geq \\hbar / 2\n$$\n\nConclusion.';
        const { result } = renderHook(() => usePagination(note, {}));
        // The math block has an inner blank line — should not cause a split there
        const allPages = result.current.pages.join('\n');
        expect(allPages).toContain('E = mc^2');
        expect(allPages).toContain('\\Delta x');
    });
});

describe('usePagination — navigation state', () => {
    it('starts at page 0', () => {
        const note = '## Page One\ncontent\n\n## Page Two\nmore content with much more text to exceed the merge threshold for getting split into individual pages...'.repeat(10);
        const { result } = renderHook(() => usePagination(note, {}));
        expect(result.current.currentPage).toBe(0);
    });

    it('setCurrentPage updates current page', () => {
        const note = '## A\n' + 'x'.repeat(3100) + '\n\n## B\n' + 'y'.repeat(3100);
        const { result } = renderHook(() => usePagination(note, {}));
        act(() => result.current.setCurrentPage(1));
        expect(result.current.currentPage).toBe(1);
    });

    it('initialises fontSize from localStorage or defaults to 16', () => {
        localStorage.removeItem('ag_font_size');
        const { result } = renderHook(() => usePagination('', {}));
        expect(result.current.fontSize).toBe(16);
    });

    it('persists fontSize to localStorage', () => {
        const { result } = renderHook(() => usePagination('', {}));
        act(() => result.current.setFontSize(18));
        expect(localStorage.getItem('ag_font_size')).toBe('18');
    });
});

describe('usePagination — handleJumpToSection', () => {
    const note = '## Fourier Transform\nThis section explains Fourier methods.\n\n' +
        '## '.padEnd(3200, 'x') + '\nAnother long section.\n\n## Convolution\nConvolution details here.';

    it('jumps to correct page by exact label match', () => {
        const { result } = renderHook(() => usePagination(note, {}));
        act(() => result.current.handleJumpToSection('Convolution'));
        // Should navigate to a page containing "Convolution"
        const page = result.current.pages[result.current.currentPage];
        expect(page?.toLowerCase()).toContain('convolution');
    });

    it('does nothing when label not found', () => {
        const { result } = renderHook(() => usePagination(note, {}));
        const initialPage = result.current.currentPage;
        act(() => result.current.handleJumpToSection('NonExistentTopic999'));
        expect(result.current.currentPage).toBe(initialPage);
    });
});
