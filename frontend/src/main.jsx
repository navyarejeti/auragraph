import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'
import 'katex/dist/katex.min.css'
import { Provider } from 'react-redux'
import { store } from './store.js'

try {
    ReactDOM.createRoot(document.getElementById('root')).render(
        <React.StrictMode>
            <Provider store={store}>
                <App />
            </Provider>
        </React.StrictMode>,
    )
} catch (e) {
    document.getElementById('root').innerHTML =
        `<div style="padding:40px;font-family:monospace;color:#991B1B;background:#FEF2F2;min-height:100vh">
            <h2>⚠️ Startup Error</h2>
            <pre style="margin-top:12px;white-space:pre-wrap">${e?.message}\n${e?.stack}</pre>
        </div>`
}
