import { createContext, useContext, useState, useEffect, useCallback } from 'react';

// Theme modes: 'dark' | 'light' | 'hybrid' (dark login, light app)
const STORAGE_KEY = 'ag_theme';
const DEFAULT_THEME = 'light';

const ThemeContext = createContext({ theme: DEFAULT_THEME, setTheme: () => { }, effectiveTheme: 'light' });

export function ThemeProvider({ children }) {
    const [theme, setThemeState] = useState(() => {
        try { return localStorage.getItem(STORAGE_KEY) || DEFAULT_THEME; }
        catch { return DEFAULT_THEME; }
    });

    const setTheme = useCallback((t) => {
        setThemeState(t);
        try { localStorage.setItem(STORAGE_KEY, t); } catch { }
    }, []);

    return (
        <ThemeContext.Provider value={{ theme, setTheme }}>
            {children}
        </ThemeContext.Provider>
    );
}

/** Returns the effective theme for a given page context.
 *  - Login page always uses 'dark'.
 *  - In 'hybrid' mode, app pages use 'light'.
 *  - In 'dark'/'light' modes, all pages use that mode.
 */
export function useTheme(pageContext = 'app') {
    const { theme, setTheme } = useContext(ThemeContext);
    let effective;
    if (pageContext === 'login') {
        effective = 'dark'; // login is always dark
    } else if (theme === 'hybrid') {
        effective = 'light'; // hybrid means app pages are light
    } else {
        effective = theme;
    }
    return { theme, setTheme, effective };
}

/** Sets data-theme attribute on <body> — call from useEffect in page components. */
export function applyThemeToBody(effective) {
    document.body.setAttribute('data-theme', effective);
}

export function ThemeToggle({ theme, setTheme }) {
    const modes = [
        { key: 'hybrid', label: '☀️', title: 'Hybrid — Dark login, Light app' },
        { key: 'light', label: '🌤', title: 'Light — All pages light' },
        { key: 'dark', label: '🌙', title: 'Dark — All pages dark' },
    ];
    const idx = modes.findIndex(m => m.key === theme);
    const next = modes[(idx + 1) % modes.length];
    return (
        <button
            onClick={() => setTheme(next.key)}
            title={`Theme: ${theme} — Click for ${next.title}`}
            style={{
                background: 'var(--surface)',
                border: '1px solid var(--border2)',
                borderRadius: 8,
                padding: '4px 10px',
                cursor: 'pointer',
                fontSize: 14,
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                color: 'var(--text2)',
                transition: 'all 0.15s',
            }}
        >
            {modes[idx]?.label || '☀️'}
            <span style={{ fontSize: 10, fontWeight: 600 }}>{theme === 'hybrid' ? 'Hybrid' : theme === 'light' ? 'Light' : 'Dark'}</span>
        </button>
    );
}
