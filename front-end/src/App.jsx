import { useState } from 'react'
import { searchCandidates, downloadCSV } from './api.js'

const styles = {
  page: {
    fontFamily: "'Segoe UI', system-ui, sans-serif",
    maxWidth: 1100,
    margin: '0 auto',
    padding: '48px 24px',
    color: '#111',
  },
  header: {
    textAlign: 'center',
    marginBottom: 40,
  },
  title: {
    fontSize: 36,
    fontWeight: 700,
    letterSpacing: '-0.5px',
    margin: '0 0 8px',
  },
  subtitle: {
    fontSize: 16,
    color: '#666',
    margin: 0,
  },
  searchRow: {
    display: 'flex',
    gap: 10,
    maxWidth: 700,
    margin: '0 auto 40px',
  },
  input: {
    flex: 1,
    padding: '12px 16px',
    fontSize: 15,
    border: '1.5px solid #ddd',
    borderRadius: 8,
    outline: 'none',
  },
  button: {
    padding: '12px 24px',
    fontSize: 15,
    fontWeight: 600,
    background: '#111',
    color: '#fff',
    border: 'none',
    borderRadius: 8,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  },
  buttonDisabled: {
    background: '#999',
    cursor: 'not-allowed',
  },
  status: {
    textAlign: 'center',
    color: '#666',
    fontSize: 15,
    padding: '40px 0',
  },
  error: {
    textAlign: 'center',
    color: '#c00',
    fontSize: 15,
    padding: '20px 0',
  },
  resultsHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  resultCount: {
    fontSize: 15,
    color: '#444',
  },
  exportBtn: {
    padding: '8px 18px',
    fontSize: 14,
    fontWeight: 600,
    background: '#fff',
    color: '#111',
    border: '1.5px solid #111',
    borderRadius: 7,
    cursor: 'pointer',
  },
  tableWrap: {
    overflowX: 'auto',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: 14,
  },
  th: {
    textAlign: 'left',
    padding: '10px 14px',
    borderBottom: '2px solid #e5e5e5',
    fontWeight: 600,
    color: '#444',
    whiteSpace: 'nowrap',
  },
  td: {
    padding: '12px 14px',
    borderBottom: '1px solid #f0f0f0',
    verticalAlign: 'top',
  },
  scoreCell: {
    fontWeight: 700,
    fontSize: 15,
  },
  linkedinLink: {
    color: '#0a66c2',
    textDecoration: 'none',
    fontSize: 13,
  },
}

function scoreColor(score) {
  if (score >= 7) return '#16a34a'
  if (score >= 5) return '#ca8a04'
  return '#dc2626'
}

export default function App() {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [candidates, setCandidates] = useState(null)
  const [error, setError] = useState(null)

  async function handleSearch(e) {
    e.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    setError(null)
    setCandidates(null)
    try {
      const data = await searchCandidates(query.trim())
      setCandidates(data.candidates)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <h1 style={styles.title}>Sorceror</h1>
        <p style={styles.subtitle}>Find the right people, fast.</p>
      </div>

      <form style={styles.searchRow} onSubmit={handleSearch}>
        <input
          style={styles.input}
          type="text"
          placeholder="who are you looking for? e.g. AI founders in SF Berkeley grads"
          value={query}
          onChange={e => setQuery(e.target.value)}
          disabled={loading}
        />
        <button
          style={{ ...styles.button, ...(loading ? styles.buttonDisabled : {}) }}
          type="submit"
          disabled={loading}
        >
          {loading ? 'Searching...' : 'Find Candidates'}
        </button>
      </form>

      {loading && (
        <p style={styles.status}>Searching the web and analyzing candidates...</p>
      )}

      {error && (
        <p style={styles.error}>Error: {error}</p>
      )}

      {candidates !== null && !loading && (
        <>
          {candidates.length === 0 ? (
            <p style={styles.status}>No candidates found. Try a broader or different query.</p>
          ) : (
            <>
              <div style={styles.resultsHeader}>
                <span style={styles.resultCount}>{candidates.length} candidate{candidates.length !== 1 ? 's' : ''} found</span>
                <button style={styles.exportBtn} onClick={downloadCSV}>
                  Download CSV
                </button>
              </div>
              <div style={styles.tableWrap}>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>Name</th>
                      <th style={styles.th}>Company</th>
                      <th style={styles.th}>Title</th>
                      <th style={styles.th}>LinkedIn</th>
                      <th style={styles.th}>Fit</th>
                      <th style={styles.th}>Why Relevant</th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidates.map((c, i) => (
                      <tr key={i}>
                        <td style={styles.td}>{c.first_name} {c.last_name}</td>
                        <td style={styles.td}>{c.company}</td>
                        <td style={styles.td}>{c.role}</td>
                        <td style={styles.td}>
                          {c.linkedin_url ? (
                            <a href={c.linkedin_url} target="_blank" rel="noreferrer" style={styles.linkedinLink}>
                              View ↗
                            </a>
                          ) : '—'}
                        </td>
                        <td style={{ ...styles.td, ...styles.scoreCell, color: scoreColor(c.fit_score) }}>
                          {c.fit_score}/10
                        </td>
                        <td style={{ ...styles.td, maxWidth: 340 }}>{c.why_relevant}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
