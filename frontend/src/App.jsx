import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useSelector, useDispatch } from 'react-redux';
import { setUser, addToast } from './store';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import NotebookWorkspace from './pages/NotebookWorkspace';
import { ToastContainer } from './components/Toast';
import { API } from './components/utils';

class ErrorBoundary extends React.Component {
    constructor(props) { super(props); this.state = { error: null }; }
    static getDerivedStateFromError(e) { return { error: e }; }
    render() {
        if (this.state.error) {
            return (
                <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#FEF2F2', flexDirection: 'column', gap: 12, padding: 32 }}>
                    <div style={{ fontSize: 28 }}>⚠️</div>
                    <div style={{ fontWeight: 700, fontSize: 18, color: '#991B1B' }}>Something went wrong</div>
                    <pre style={{ background: '#fff', border: '1px solid #FCA5A5', borderRadius: 8, padding: '12px 18px', fontSize: 13, color: '#7F1D1D', maxWidth: 680, overflowX: 'auto', whiteSpace: 'pre-wrap' }}>
                        {this.state.error?.message}
                        {this.state.error?.stack}
                    </pre>
                    <button onClick={() => { this.setState({ error: null }); window.location.href = '/dashboard'; }}
                        style={{ padding: '8px 20px', background: '#DC2626', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer', fontWeight: 600 }}>
                        Back to Dashboard
                    </button>
                </div>
            );
        }
        return this.props.children;
    }
}

const DEMO_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours

/** Silently renews the stored token every 6 h (no-op for demo tokens). */
function TokenRefresher() {
    const dispatch = useDispatch();
    useEffect(() => {
        async function doRefresh() {
            const token = localStorage.getItem('ag_token');
            if (!token || token === 'demo-token') return;
            try {
                const res = await fetch(`${API}/auth/refresh`, {
                    method: 'POST',
                    headers: { Authorization: `Bearer ${token}` },
                });
                if (res.ok) {
                    const data = await res.json();
                    localStorage.setItem('ag_token', data.token);
                    localStorage.setItem('ag_user', JSON.stringify(data));
                    dispatch(setUser(data));
                } else if (res.status === 401) {
                    // Token truly expired — force re-login
                    localStorage.removeItem('ag_token');
                    localStorage.removeItem('ag_user');
                    dispatch(setUser(null));
                    dispatch(addToast({
                        kind: 'error',
                        title: 'Session expired',
                        message: 'Please log in again.',
                        duration: 8000,
                    }));
                }
            } catch { /* network down — stay logged in, retry next cycle */ }
        }
        doRefresh();
        const id = setInterval(doRefresh, 6 * 60 * 60 * 1000); // every 6 h
        return () => clearInterval(id);
    }, [dispatch]);
    return null;
}

function PrivateRoute({ children }) {
    const user = useSelector(s => s.graph.user);
    const token = localStorage.getItem('ag_token');
    // Check demo token expiry
    if (token === 'demo-token') {
        const issuedAt = parseInt(localStorage.getItem('ag_demo_issued_at') || '0', 10);
        if (issuedAt && Date.now() - issuedAt > DEMO_TTL_MS) {
            // Demo session expired — clear and redirect to login
            localStorage.removeItem('ag_token');
            localStorage.removeItem('ag_user');
            localStorage.removeItem('ag_demo_issued_at');
            return <Navigate to="/" replace />;
        }
    }
    return user || token ? children : <Navigate to="/" replace />;
}

export default function App() {
    return (
        <BrowserRouter>
            <ErrorBoundary>
                <TokenRefresher />
                <Routes>
                    <Route path="/" element={<LoginPage />} />
                    <Route path="/dashboard" element={<PrivateRoute><DashboardPage /></PrivateRoute>} />
                    <Route path="/notebook/:id" element={<PrivateRoute><ErrorBoundary><NotebookWorkspace /></ErrorBoundary></PrivateRoute>} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                </Routes>
                <ToastContainer />
            </ErrorBoundary>
        </BrowserRouter>
    );
}
