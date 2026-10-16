import { useEffect, useMemo, useRef, useState } from 'react'

const COLUMN_COUNT = 4
const COLUMN_WIDTH = 250
const ROW_HEIGHT = 110

function edgeIdentity(edge) {
  return `${edge.source}-${edge.target}-${edge.type}-${edge.line || ''}-${encodeURIComponent(edge.evidence || '')}`
}

function isSafeGitHubUrl(value) {
  if (!value) return false
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && url.hostname === 'github.com'
  } catch {
    return false
  }
}

function Graph({ nodes, edges, onSelectNode, onSelectEdge, selectedId, graphRef }) {
  const positions = useMemo(() => {
    const result = new Map()
    nodes.forEach((node, index) => {
      const column = index % COLUMN_COUNT
      const row = Math.floor(index / COLUMN_COUNT)
      result.set(node.id, {
        x: 24 + column * COLUMN_WIDTH,
        y: 24 + row * ROW_HEIGHT,
      })
    })
    return result
  }, [nodes])

  const width = COLUMN_COUNT * COLUMN_WIDTH + 48
  const height = Math.max(160, Math.ceil(nodes.length / COLUMN_COUNT) * ROW_HEIGHT + 48)

  return (
    <svg
      className="architecture-graph"
      role="group"
      aria-label="Inferred repository architecture graph"
      ref={graphRef}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      xmlns="http://www.w3.org/2000/svg"
    >
      <title>Repository architecture graph. Relationships are inferred from static source analysis.</title>
      <defs>
        <marker id="architecture-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" />
        </marker>
      </defs>
      <g className="architecture-edges">
        {edges.map((edge) => {
          const source = positions.get(edge.source)
          const target = positions.get(edge.target)
          if (!source || !target) return null
          const id = edgeIdentity(edge)
          const x1 = source.x + 90
          const y1 = source.y + 32
          const x2 = target.x + 90
          const y2 = target.y + 32
          return (
            <g
              key={id}
              className={`architecture-edge${selectedId === id ? ' is-selected' : ''}`}
              role="button"
              tabIndex="0"
              aria-label={`${edge.label}: ${edge.explanation}`}
              onClick={() => onSelectEdge({ ...edge, id })}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onSelectEdge({ ...edge, id })
                }
              }}
            >
              <line x1={x1} y1={y1} x2={x2} y2={y2} markerEnd="url(#architecture-arrow)" />
              <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 4}>{edge.label}</text>
            </g>
          )
        })}
      </g>
      <g className="architecture-nodes">
        {nodes.map((node) => {
          const position = positions.get(node.id)
          const selected = selectedId === node.id
          return (
            <g
              key={node.id}
              className={`architecture-node architecture-node-${node.type}${selected ? ' is-selected' : ''}`}
              role="button"
              tabIndex="0"
              aria-label={`${node.type}: ${node.label}`}
              transform={`translate(${position.x}, ${position.y})`}
              onClick={() => onSelectNode(node)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onSelectNode(node)
                }
              }}
            >
              <title>{`${node.label}: ${node.explanation}`}</title>
              <rect width="180" height="64" rx="10" />
              <text className="architecture-node-kind" x="10" y="19">{node.type}</text>
              <text className="architecture-node-label" x="10" y="43">
                {node.label.length > 24 ? `${node.label.slice(0, 21)}...` : node.label}
              </text>
            </g>
          )
        })}
      </g>
    </svg>
  )
}

function ArchitectureExplorer({ repoUrl }) {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState(null)
  const graphRef = useRef(null)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    setResult(null)
    setSelected(null)

    fetch('/api/architecture', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_url: repoUrl }),
      signal: controller.signal,
    })
      .then(async (response) => {
        const data = await response.json()
        if (!response.ok) {
          throw new Error(data.detail || 'Architecture analysis failed.')
        }
        return data
      })
      .then(setResult)
      .catch((requestError) => {
        if (requestError.name !== 'AbortError') {
          setError(requestError.message || 'Architecture analysis failed.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => controller.abort()
  }, [repoUrl])

  const exportSvg = () => {
    if (!graphRef.current) return
    const svg = graphRef.current.cloneNode(true)
    svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
    const styles = document.createElementNS('http://www.w3.org/2000/svg', 'style')
    styles.textContent = `
      text { font-family: Arial, sans-serif; fill: #1f2937; }
      .architecture-edge line { stroke: #94a3b8; stroke-width: 1.5; }
      .architecture-edge text { fill: #475569; font-size: 10px; }
      .architecture-node rect { fill: #fff; stroke: #64748b; stroke-width: 1.5; }
      .architecture-node-framework rect { fill: #eef2ff; stroke: #4f46e5; }
      .architecture-node-route rect { fill: #ecfdf5; stroke: #059669; }
      .architecture-node-kind { fill: #64748b; font-size: 10px; }
      .architecture-node-label { font-size: 13px; font-weight: 600; }
    `
    svg.insertBefore(styles, svg.firstChild)
    const blob = new Blob([new XMLSerializer().serializeToString(svg)], {
      type: 'image/svg+xml;charset=utf-8',
    })
    const downloadUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = downloadUrl
    link.download = 'reposense-architecture.svg'
    link.click()
    URL.revokeObjectURL(downloadUrl)
  }

  const nodes = result?.nodes || []
  const edges = result?.edges || []
  return (
    <section className="card architecture-card" aria-labelledby="architecture-heading">
      <div className="architecture-header">
        <div>
          <h2 id="architecture-heading">Architecture explorer</h2>
          <p>Static analysis only: relationships are inferred from repository paths, manifests, imports, and decorators—not runtime-verified.</p>
        </div>
        {result && nodes.length > 1 && (
          <button type="button" onClick={exportSvg}>Export SVG</button>
        )}
      </div>

      {loading && <div className="status-box" role="status">Analyzing repository structure and source…</div>}
      {error && <div className="error-box" role="alert">{error}</div>}

      {result && !loading && (
        <>
          {result.status === 'partial' && (
            <div className="status-box architecture-partial" role="status">
              Partial analysis: {result.warnings.join(' ')}
            </div>
          )}
          <div className="architecture-metadata">
            <div>
              <strong>Languages</strong>
              <p>{result.languages.length
                ? result.languages.map(({ name, files }) => `${name} (${files})`).join(', ')
                : 'No supported language files found.'}</p>
            </div>
            <div>
              <strong>Frameworks</strong>
              <p>{result.frameworks.length
                ? result.frameworks.map(({ name }) => name).join(', ')
                : 'No frameworks detected from supported manifests or imports.'}</p>
            </div>
          </div>

          {nodes.length <= 1 ? (
            <div className="architecture-empty" role="status">
              No supported source or manifest files were available to build a graph.
            </div>
          ) : (
            <div className="architecture-layout">
              <div className="architecture-graph-scroll" aria-label="Scrollable architecture diagram">
                <Graph
                  nodes={nodes}
                  edges={edges}
                  onSelectNode={setSelected}
                  onSelectEdge={(edge) => setSelected(edge)}
                  selectedId={selected ? (selected.id || edgeIdentity(selected)) : ''}
                  graphRef={graphRef}
                />
              </div>
              <aside className="architecture-inspector" aria-live="polite">
                {selected ? (
                  <>
                    <span className="architecture-inspector-type">{selected.type}</span>
                    <h3>{selected.label}</h3>
                    <p>{selected.explanation}</p>
                    {selected.path && <p><strong>File:</strong> {selected.path}</p>}
                    {(selected.line_start || selected.line) && (
                      <p><strong>Line:</strong> {selected.line_start || selected.line}{selected.line_end && selected.line_end !== selected.line_start ? `–${selected.line_end}` : ''}</p>
                    )}
                    {selected.evidence && <p><strong>Evidence:</strong> {selected.evidence}</p>}
                    {isSafeGitHubUrl(selected.source_url) && (
                      <a href={selected.source_url} target="_blank" rel="noreferrer">
                        Open source on GitHub
                      </a>
                    )}
                  </>
                ) : (
                  <p>Select a node or relationship to inspect its evidence and explanation.</p>
                )}
              </aside>
            </div>
          )}

          <details className="architecture-tree">
            <summary>Repository structure and graph items ({nodes.length} nodes)</summary>
            <ul>
              {nodes.map((node) => (
                <li key={node.id} style={{ '--tree-depth': Math.min((node.path?.split('/').length || 0), 8) }}>
                  <button type="button" className="architecture-tree-item" onClick={() => setSelected(node)}>
                    <span>{node.type}</span> {node.path || node.label}
                  </button>
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
    </section>
  )
}

export default ArchitectureExplorer
