import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { applyAppearance, loadLocal } from './appearance'
import { getColorScheme } from './telegram'
import { hideBoot } from './boot'
import './styles/tokens.css'
import './styles/base.css'
import './styles/wow.css'
import './styles/market.css'
import './styles/premium.css'
import './styles/appearance.css'

// Saqlangan ko'rinish birinchi kadrdan qo'llanadi (rang/fon miltillamaydi).
applyAppearance(loadLocal(), getColorScheme())

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
