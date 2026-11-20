import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { clearPending, createRun, loadPending, moneyCents, RunApiError, savePending } from '../api/runs'
import type { PendingRun } from '../api/runs'

export default function DryRunForm({ selected, strategyId, enabled, visible, review, onBack, onPending }: {
  selected: string[]; strategyId?: string; enabled: boolean; visible: boolean
  review: ReactNode; onBack: () => void; onPending: (pending: boolean) => void
}) {
  const [intent, setIntent] = useState<PendingRun | null>(loadPending)
  const [bankroll, setBankroll] = useState('1000.00')
  const [stake, setStake] = useState('10.00')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const active = useRef<AbortController | null>(null)
  const current = useRef(intent)
  useEffect(() => { onPending(intent !== null) }, [intent, onPending])
  useEffect(() => () => { active.current?.abort(); active.current = null }, [])
  const bankrollCents = moneyCents(bankroll), stakeCents = moneyCents(stake)
  const valid = bankrollCents !== null && stakeCents !== null && name.trim().length <= 255
  const maximum = stakeCents === null ? null : stakeCents * BigInt(selected.length)
  const affordable = maximum !== null && bankrollCents !== null && maximum <= bankrollCents
  const maximumText = maximum === null ? '—' : `${maximum / 100n}.${(maximum % 100n).toString().padStart(2, '0')}`
  async function submit(saved: PendingRun) {
    if (active.current) return
    try { savePending(saved) } catch {
      setError('Unable to save retry recovery in this tab. Enable browser session storage before creating a Run.'); return
    }
    current.current = saved; setIntent(saved)
    const controller = new AbortController(), startingRoute = location.hash
    active.current = controller; setBusy(true); setError(null)
    try {
      const result = await createRun(saved, controller.signal)
      if (controller.signal.aborted || active.current !== controller || current.current?.key !== saved.key || location.hash !== startingRoute) return
      clearPending(saved.key); current.current = null; setIntent(null)
      location.hash = `/runs/${result.run.id}`
    } catch (failure) {
      if (controller.signal.aborted || active.current !== controller || current.current?.key !== saved.key || location.hash !== startingRoute) return
      if (failure instanceof RunApiError && failure.definite) {
        clearPending(saved.key); current.current = null; setIntent(null)
        setError(failure.message)
      } else setError('Creation may have succeeded, but its response was not received. Retry the saved request to recover the same Run.')
    } finally {
      if (active.current === controller) { active.current = null; setBusy(false) }
    }
  }
  return <section hidden={!visible && !intent} className="state-panel dry-run-panel" aria-label="Finalize Run">
    <h2>3 · Finalize Run</h2>
    <p>Predictions start after final submission. Leaving this page does not cancel an accepted Run.</p>
    {intent ? <div className="recovery-panel">
      <h3>Unresolved creation</h3>
      <p>{intent.body.game_ids.length} selected games · Starting bankroll {intent.body.starting_bankroll} · Stake {intent.body.stake_per_bet}{intent.body.name && ` · ${intent.body.name}`}</p>
      <p>Retry uses your saved settings. Leaving this page does not cancel a saved Run.</p>
      <button disabled={busy} onClick={() => void submit(intent)}>{busy ? 'Creating Run…' : 'Retry creation'}</button>{' '}
      <button className="secondary" disabled={busy} onClick={() => setConfirmDiscard(true)}>Discard pending request</button>
      {confirmDiscard && <div role="alert">
        <p>An earlier Run may already exist. Check <a href="#/runs">Run history</a> before creating another simulation.</p>
        <button className="secondary" onClick={() => { clearPending(intent.key); current.current = null; setIntent(null); setConfirmDiscard(false); setError(null) }}>Discard and edit settings</button>{' '}
        <button className="secondary" onClick={() => setConfirmDiscard(false)}>Keep saved request</button>
      </div>}
    </div> : <form onSubmit={event => {
      event.preventDefault()
      if (!visible || !valid || !affordable || !enabled || !strategyId || !selected.length || active.current) return
      void submit({ key: crypto.randomUUID(), body: { strategy_id: strategyId, game_ids: [...selected], starting_bankroll: bankroll, stake_per_bet: stake, ...(name.trim() ? { name: name.trim() } : {}) } })
    }}>
      {review}
      <div className="form-grid">
        <label>Starting bankroll<input inputMode="decimal" value={bankroll} onChange={e => setBankroll(e.target.value)} aria-invalid={bankrollCents === null} required /></label>
        <label>Stake per Bet<input inputMode="decimal" value={stake} onChange={e => setStake(e.target.value)} aria-invalid={stakeCents === null} required /></label>
        <label>Run name (optional)<input value={name} maxLength={255} onChange={e => setName(e.target.value)} /></label>
      </div>
      {!valid && <p role="alert">Enter positive amounts with at most two decimal places, up to 9999999999.99.</p>}
      <p>Maximum committed stake if every selected game produces a Bet: <strong>{maximumText}</strong></p>
      {!affordable && maximum !== null && bankrollCents !== null && <p role="alert">Maximum committed stake exceeds the starting bankroll.</p>}
      <p>{selected.length} games selected. The server rechecks eligibility and reports skipped games.</p>
      <button type="button" className="secondary" onClick={onBack}>Back to Games</button>{' '}
      <button disabled={!visible || !valid || !affordable || !enabled || !selected.length || busy} type="submit">Create Run</button>
    </form>}
    {error && <p className="request-error" role="alert">{error}</p>}
    <div aria-live="polite">{busy && <p role="status">Submitting Run…</p>}</div>
  </section>
}
