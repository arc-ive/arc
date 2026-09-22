import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App.jsx'
import { AuthProvider } from './auth/AuthContext.jsx'
import { TenantProvider } from './tenant/TenantContext.jsx'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30 * 1000,
      // Issue #225: React Query's default `online` network mode PAUSES a
      // fetch whenever its online heuristic says the browser is offline.
      // A paused query keeps `status: 'pending'` indefinitely, so every
      // page that renders a skeleton while pending shows a loading state
      // that never resolves and never reports an error — observed with
      // `navigator.onLine === true` and the API reachable. Arc talks to a
      // same-origin API, so pausing buys nothing and costs the user a
      // screen that hangs forever. Always attempt the request and let a
      // real failure surface as an error state.
      networkMode: 'always',
    },
    mutations: {
      retry: 0,
      networkMode: 'always',
    },
  },
})

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TenantProvider>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </TenantProvider>
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
)