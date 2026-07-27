import { useEffect, useRef, useState } from 'react'

/**
 * Minimal inline SVG sparkline/area chart for stat-tile trends. No chart library -
 * a single normalized line + light area wash, per the dataviz skill's mark specs
 * (2px line, rounded caps, ~10% opacity area fill), plus a recessive time axis and
 * a crosshair+tooltip hover layer per the skill's interaction conventions.
 */

const AXIS_HEIGHT = 16
const AXIS_GAP = 4
const TICK_COUNT = 5

function formatTick(iso: string, timezone?: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  try {
    return new Intl.DateTimeFormat(undefined, {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: timezone,
    }).format(d)
  } catch {
    // Invalid/unknown IANA timezone string - fall back to browser-local formatting.
    return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', hour12: false }).format(d)
  }
}

function formatTooltipTime(iso: string, timezone?: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: timezone,
    }).format(d)
  } catch {
    return d.toLocaleString()
  }
}

export function Sparkline({
  data,
  timestamps,
  timezone,
  width = 320,
  height = 72,
  color = 'currentColor',
  strokeWidth = 2,
  className,
}: {
  data: number[]
  timestamps?: string[]
  timezone?: string
  width?: number
  height?: number
  color?: string
  strokeWidth?: number
  className?: string
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  // The SVG is rendered at width="100%" of its container, but the viewBox
  // needs to match that *actual* pixel width - not the `width` prop default -
  // otherwise preserveAspectRatio="none" non-uniformly stretches everything
  // (including the axis-label <text> glyphs, which then look squashed/
  // stretched instead of using the intended font). Measure the real width
  // and use it as the viewBox width so the scale factor is 1:1.
  const [measuredWidth, setMeasuredWidth] = useState<number | null>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width
      if (w && w > 0) setMeasuredWidth(w)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  if (!data || data.length < 2) {
    return <div className={className} style={{ width, height }} aria-hidden="true" />
  }

  const viewBoxWidth = measuredWidth ?? width
  const hasAxis = Boolean(timestamps && timestamps.length === data.length)
  const plotHeight = height
  const totalHeight = plotHeight + (hasAxis ? AXIS_HEIGHT + AXIS_GAP : 0)

  const min = Math.min(...data)
  const max = Math.max(...data)
  const range = max - min || 1
  const pad = strokeWidth
  const innerHeight = plotHeight - pad * 2

  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * viewBoxWidth
    const y = pad + innerHeight - ((v - min) / range) * innerHeight
    return [x, y] as const
  })

  const linePath = points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`).join(' ')
  const areaPath = `${linePath} L${points[points.length - 1][0].toFixed(2)},${plotHeight} L${points[0][0].toFixed(2)},${plotHeight} Z`

  // Evenly-spaced tick indices across the data (endpoints included), capped at TICK_COUNT.
  const tickIndices: number[] = []
  if (hasAxis) {
    const n = Math.min(TICK_COUNT, data.length)
    for (let i = 0; i < n; i++) {
      const idx = n === 1 ? 0 : Math.round((i / (n - 1)) * (data.length - 1))
      if (!tickIndices.includes(idx)) tickIndices.push(idx)
    }
  }

  function indexFromClientX(clientX: number): number {
    const rect = containerRef.current?.getBoundingClientRect()
    if (!rect || rect.width === 0) return 0
    const fraction = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
    return Math.round(fraction * (data.length - 1))
  }

  const hovered = hoverIndex !== null ? points[hoverIndex] : null
  const hoveredPct = hovered ? (hovered[0] / viewBoxWidth) * 100 : 0
  // Flip the tooltip to the left side once it would otherwise overflow the right edge.
  const tooltipAlign = hoveredPct > 70 ? 'right' : hoveredPct < 30 ? 'left' : 'center'

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ width: '100%', height: totalHeight, position: 'relative' }}
      onMouseMove={(e) => setHoverIndex(indexFromClientX(e.clientX))}
      onMouseLeave={() => setHoverIndex(null)}
    >
      <svg
        viewBox={`0 0 ${viewBoxWidth} ${totalHeight}`}
        width="100%"
        height={totalHeight}
        preserveAspectRatio="none"
        role="img"
        aria-label="Trend over the last 24 hours"
      >
        <path d={areaPath} fill={color} fillOpacity={0.1} stroke="none" />
        <path d={linePath} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" />

        {hovered && (
          <g>
            <line
              x1={hovered[0]}
              x2={hovered[0]}
              y1={0}
              y2={plotHeight}
              stroke="var(--muted-foreground)"
              strokeWidth={1}
              strokeOpacity={0.4}
            />
            <circle cx={hovered[0]} cy={hovered[1]} r={4} fill={color} stroke="var(--card)" strokeWidth={2} />
          </g>
        )}

        {hasAxis && (
          <g>
            {tickIndices.map((idx) => {
              const x = points[idx][0]
              const anchor = idx === 0 ? 'start' : idx === data.length - 1 ? 'end' : 'middle'
              return (
                <text
                  key={idx}
                  x={x}
                  y={plotHeight + AXIS_GAP + AXIS_HEIGHT - 4}
                  textAnchor={anchor}
                  fontSize={9}
                  fill="var(--muted-foreground)"
                >
                  {formatTick(timestamps![idx], timezone)}
                </text>
              )
            })}
          </g>
        )}
      </svg>

      {hovered && (
        <div
          className="pointer-events-none absolute top-0 z-10 rounded-md border bg-popover px-2 py-1 text-[0.65rem] text-popover-foreground shadow-sm"
          style={{
            left: tooltipAlign === 'center' ? `${hoveredPct}%` : tooltipAlign === 'left' ? 0 : undefined,
            right: tooltipAlign === 'right' ? 0 : undefined,
            transform: tooltipAlign === 'center' ? 'translateX(-50%)' : undefined,
            whiteSpace: 'nowrap',
          }}
        >
          <div className="font-semibold">{data[hoverIndex!].toLocaleString()}</div>
          {timestamps && (
            <div className="text-muted-foreground">{formatTooltipTime(timestamps[hoverIndex!], timezone)}</div>
          )}
        </div>
      )}
    </div>
  )
}
