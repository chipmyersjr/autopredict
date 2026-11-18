import { useEffect, useState } from 'react'
import GamesPage from './pages/GamesPage'
import DashboardPage from './pages/DashboardPage'
import { RunDetail, RunsPage } from './pages/RunsPage'
export default function App() {
  const [route, setRoute] = useState(location.hash || '#/games')
  useEffect(() => {
    const changed = () => { setRoute(location.hash || '#/games'); window.scrollTo(0, 0) }
    window.addEventListener('hashchange', changed)
    return () => window.removeEventListener('hashchange', changed)
  }, [])
  const isGames = route === '#/games' || route === '#/' || route === '#'
  return <><nav className="main-nav" aria-label="Main navigation"><a href="#/games" aria-current={isGames ? 'page' : undefined}>Games</a><a href="#/runs" aria-current={route.startsWith('#/runs') ? 'page' : undefined}>Runs</a><a href="#/dashboard" aria-current={route === '#/dashboard' ? 'page' : undefined}>Dashboard</a></nav>
    {isGames ? <GamesPage /> : route === '#/dashboard' ? <DashboardPage /> : route === '#/runs' ? <RunsPage /> : route.startsWith('#/runs/') ? <RunDetail key={route} id={route.slice(7)} /> : <main><h1>Page not found</h1><a href="#/games">Choose games</a></main>}
  </>
}
