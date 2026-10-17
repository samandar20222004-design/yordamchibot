import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { hideBoot } from './boot'
import './styles/tokens.css'
import './styles/base.css'
import './styles/wow.css'

const root = document.getElementById('root')
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

// Himoya: biror sabab bilan ilova tayyor bo'lmasa ham yuklash ekrani abadiy qolmasin.
setTimeout(hideBoot, 15000)
