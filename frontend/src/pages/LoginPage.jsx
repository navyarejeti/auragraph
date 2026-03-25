import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDispatch } from 'react-redux';
import { setUser } from '../store';
import { Loader2, Sparkles } from 'lucide-react';
import { parseApiError } from '../components/utils';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export default function LoginPage() {
    const navigate = useNavigate();
    const dispatch = useDispatch();

    const [mode, setMode] = useState('login');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [name, setName] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    const [demoLoading, setDemoLoading] = useState(false);

    const tryDemo = async () => {
        setDemoLoading(true);
        try {
            const res = await fetch(`${API}/auth/demo-login`, { method: 'POST' });
            const data = await res.json();
            const mockUser = { id: data.id, name: data.name, email: data.email, token: data.token };
            dispatch(setUser(mockUser));
            localStorage.setItem('ag_token', data.token);
            localStorage.setItem('ag_user', JSON.stringify(mockUser));
            localStorage.setItem('ag_demo_issued_at', String(Date.now()));
            localStorage.removeItem('ag_offline_mode');
            navigate(data.demo_notebook_id ? `/notebook/${data.demo_notebook_id}` : '/dashboard');
        } catch {
            const mockUser = { id: 'demo-user', name: 'Demo Student', email: 'demo@auragraph.local', token: 'demo-token' };
            dispatch(setUser(mockUser));
            localStorage.setItem('ag_token', 'demo-token');
            localStorage.setItem('ag_user', JSON.stringify(mockUser));
            localStorage.setItem('ag_demo_issued_at', String(Date.now()));
            localStorage.setItem('ag_offline_mode', '1');
            navigate('/dashboard');
        }
        setDemoLoading(false);
    };

    const submit = async (e) => {
        e.preventDefault();
        if (!email || !password) { setError('Email and password are required.'); return; }
        setError(''); setLoading(true);
        try {
            const body = mode === 'register' ? { email, password, name: name || email.split('@')[0] } : { email, password };
            const res = await fetch(`${API}/auth/${mode === 'login' ? 'login' : 'register'}`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
            });
            const data = await res.json();
            if (!res.ok) { setError(parseApiError(data.detail, 'Something went wrong.')); setLoading(false); return; }
            dispatch(setUser(data));
            localStorage.setItem('ag_token', data.token);
            localStorage.setItem('ag_user', JSON.stringify(data));
            navigate('/dashboard');
        } catch {
            const mockUser = { id: 'demo-user', name: email.split('@')[0] || 'Student', email, token: 'demo-token' };
            dispatch(setUser(mockUser));
            localStorage.setItem('ag_token', 'demo-token');
            localStorage.setItem('ag_user', JSON.stringify(mockUser));
            navigate('/dashboard');
        }
        setLoading(false);
    };

    return (
        <div style={{
            minHeight: '100vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '48px 24px',
            background: 'var(--bg)',
            position: 'relative',
        }}>
            <div style={{ width: '100%', maxWidth: 460, background: 'var(--bg)' }}>
                <div style={{ width: '100%', maxWidth: 380, margin: '0 auto' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 28 }}>
                        <div style={{ background: 'var(--surface)', borderRadius: 10, padding: '6px 12px', border: '1px solid var(--border)' }}>
                            <img src="/logo.jpeg" alt="AuraGraph" style={{ height: 28, width: 'auto', display: 'block' }} />
                        </div>
                    </div>

                    <div style={{ marginBottom: 32 }}>
                        <h2 style={{ fontSize: 24, fontWeight: 800, color: 'var(--text)', marginBottom: 6, letterSpacing: '-0.02em' }}>
                            {mode === 'login' ? 'Welcome back 👋' : 'Join AuraGraph'}
                        </h2>
                        <p style={{ fontSize: 14, color: 'var(--text3)' }}>
                            {mode === 'login' ? 'Sign in to your notebooks and knowledge graph.' : 'Create your account and start building smarter notes.'}
                        </p>
                    </div>

                    {error && (
                        <div style={{ padding: '10px 14px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 10, fontSize: 13, color: 'var(--danger)', marginBottom: 18, display: 'flex', gap: 8, alignItems: 'center' }}>
                            <span style={{ flexShrink: 0 }}>⚠</span> {error}
                        </div>
                    )}

                    <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                        {mode === 'register' && (
                            <div>
                                <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text2)', display: 'block', marginBottom: 6 }}>Your name</label>
                                <input className="input" type="text" placeholder="e.g. Rohan Sharma" value={name} onChange={e => setName(e.target.value)} />
                            </div>
                        )}
                        <div>
                            <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text2)', display: 'block', marginBottom: 6 }}>Email address</label>
                            <input className="input" type="email" placeholder="you@university.edu" value={email} onChange={e => setEmail(e.target.value)} autoFocus={mode === 'login'} />
                        </div>
                        <div>
                            <label style={{ fontSize: 13, fontWeight: 600, color: 'var(--text2)', display: 'block', marginBottom: 6 }}>Password</label>
                            <input className="input" type="password" placeholder={mode === 'register' ? 'Min 8 characters' : '••••••••'} value={password} onChange={e => setPassword(e.target.value)} />
                        </div>
                        <button type="submit" className="btn btn-primary btn-lg" style={{ width: '100%', marginTop: 4 }} disabled={loading}>
                            {loading ? <Loader2 className="spin" size={18} /> : mode === 'login' ? 'Sign In' : 'Create Account'}
                        </button>
                    </form>

                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '20px 0' }}>
                        <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
                        <span style={{ fontSize: 12, color: 'var(--text3)', fontWeight: 500 }}>or</span>
                        <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
                    </div>

                    <button
                        type="button"
                        onClick={tryDemo}
                        disabled={demoLoading}
                        style={{ width: '100%', padding: '12px 16px', borderRadius: 10, border: '1.5px solid #C4B5FD', background: 'linear-gradient(135deg, #F5F3FF, #EDE9FE)', color: '#5B21B6', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, fontSize: 14, fontWeight: 700, transition: 'all 0.15s' }}
                        onMouseEnter={e => { e.currentTarget.style.background = 'linear-gradient(135deg, #EDE9FE, #DDD6FE)'; e.currentTarget.style.transform = 'translateY(-1px)'; }}
                        onMouseLeave={e => { e.currentTarget.style.background = 'linear-gradient(135deg, #F5F3FF, #EDE9FE)'; e.currentTarget.style.transform = 'none'; }}
                    >
                        {demoLoading ? <Loader2 className="spin" size={16} /> : <><Sparkles size={16} /> Try Demo — no sign-up needed</>}
                    </button>
                    <p style={{ textAlign: 'center', fontSize: 11, color: 'var(--text3)', marginTop: 8 }}>Loads a pre-built DSP notebook · no account required</p>

                    <p style={{ textAlign: 'center', fontSize: 13, color: 'var(--text3)', marginTop: 24 }}>
                        {mode === 'login' ? "New here? " : 'Have an account? '}
                        <button onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); }}
                            style={{ background: 'none', border: 'none', color: 'var(--ag-purple)', fontWeight: 700, cursor: 'pointer', fontSize: 13, textDecoration: 'none' }}>
                            {mode === 'login' ? 'Create a free account →' : '← Sign in'}
                        </button>
                    </p>
                </div>
            </div>

            <div style={{
                position: 'absolute',
                bottom: 16,
                left: 0,
                right: 0,
                textAlign: 'center',
                fontSize: 11,
                color: 'var(--text3)',
                fontWeight: 700,
                letterSpacing: '0.12em',
                textTransform: 'uppercase',
                pointerEvents: 'none',
            }}>
                IIT Roorkee · Team Wowffulls
            </div>
        </div>
    );
}
