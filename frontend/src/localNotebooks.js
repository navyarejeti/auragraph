/**
 * Notebook persistence via localStorage — used as fallback when backend is offline.
 * All functions mirror the backend API shape so DashboardPage/NotebookWorkspace
 * can swap transparently.
 */

const KEY = 'ag_notebooks';

function load() {
    try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch { return []; }
}

function save(notebooks) {
    localStorage.setItem(KEY, JSON.stringify(notebooks));
}

export function ls_getNotebooks(userId) {
    return load().filter(nb => !userId || nb.user_id === userId);
}

export function ls_getNotebook(id) {
    return load().find(nb => nb.id === id) || null;
}

export function ls_createNotebook(userId, name, course) {
    const notebooks = load();
    const nb = {
        id: Math.random().toString(36).slice(2) + Date.now(),
        user_id: userId,
        name,
        course,
        note: '',
        proficiency: 'Intermediate',
        graph: { nodes: [], edges: [] },
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    };
    notebooks.unshift(nb);
    save(notebooks);
    return nb;
}

export function ls_saveNote(id, note, proficiency) {
    const notebooks = load();
    const nb = notebooks.find(n => n.id === id);
    if (nb) {
        nb.note = note;
        if (proficiency) nb.proficiency = proficiency;
        nb.updated_at = new Date().toISOString();
        save(notebooks);
        return nb;
    }
    return null;
}

export function ls_deleteNotebook(id) {
    save(load().filter(nb => nb.id !== id));
}
