const BASE_URL = import.meta.env.VITE_API_URL || ''

export async function searchCandidates(query) {
  const res = await fetch(`${BASE_URL}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export function downloadCSV() {
  window.location.href = `${BASE_URL}/export`
}
