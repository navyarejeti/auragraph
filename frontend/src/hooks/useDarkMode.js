import React from 'react';

export function useDarkMode() {
    const [dark, setDark] = React.useState(() => localStorage.getItem('ag_dark') === '1');
    React.useEffect(() => {
        document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
        localStorage.setItem('ag_dark', dark ? '1' : '0');
    }, [dark]);
    return [dark, setDark];
}
