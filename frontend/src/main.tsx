import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import GamesPage from './pages/GamesPage'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <GamesPage />
  </StrictMode>,
)
