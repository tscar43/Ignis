import { useEffect, useState } from 'react'
import offlineFire from '../../demo_data/risk_demo.json'
import offlinePlan from './data/plan-demo.json'
import { loadFire, loadPlan } from './api'

const offline = {
  fire: offlineFire,
  plan: offlinePlan,
  metadata: { source: 'bundled fictional demo', stale: null, age: null },
  planMetadata: null,
  fireError: null,
  planError: null,
  loading: false,
}

export default function useEvacuationData(mode, revision) {
  const key = `${mode}:${revision}`
  const [result, setResult] = useState(null)

  useEffect(() => {
    if (mode === 'offline') return
    const controller = new AbortController()
    let cancelled = false
    let timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, 90000)
    const selection = { mode, t: 'T0' }
    Promise.allSettled([
      loadFire(selection, controller.signal),
      loadPlan(selection, controller.signal),
    ]).then(([fireResult, planResult]) => {
      if (cancelled) return
      const errorMessage = error => timedOut ? 'The backend request timed out. Retry to try again.'
        : error.message === 'Failed to fetch' ? 'Cannot reach the backend. Check the connection and retry.' : error.message
      const fire = fireResult.status === 'fulfilled' ? fireResult.value : null
      const plan = planResult.status === 'fulfilled' ? planResult.value : null
      const mismatch = fire && plan && ['firms', 'weather'].some(field =>
        fire.payload.data_as_of[field] !== plan.payload.data_as_of[field])
      setResult({
        key,
        fire: fire?.payload ?? null,
        plan: fire && !mismatch ? plan?.payload ?? null : null,
        metadata: fire?.metadata,
        planMetadata: plan?.metadata,
        fireError: fire ? null : errorMessage(fireResult.reason),
        planError: mismatch ? 'Fire observations changed while planning. Retry to synchronize the map and route.'
          : plan ? null : errorMessage(planResult.reason),
        unavailable: planResult.status === 'rejected' && planResult.reason.status === 422,
        loading: false,
      })
    }).finally(() => clearTimeout(timer))
    return () => {
      cancelled = true
      clearTimeout(timer)
      controller.abort()
    }
  }, [mode, key])

  if (mode === 'offline') return offline
  return result?.key === key ? result : { loading: true, fire: null, plan: null }
}
