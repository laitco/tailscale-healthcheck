import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface PaginationProps {
  /** Zero-based index of the first row shown. */
  offset: number
  pageSize: number
  total: number
  /** Noun for the result count line, e.g. "device" / "audit entry". */
  noun: string
  nounPlural?: string
  onOffsetChange: (offset: number) => void
}

/**
 * Result count plus prev/next controls. The count line matters as much as the
 * buttons: these tables used to render a hard-capped slice with nothing to
 * indicate that results had been truncated at all.
 */
export function Pagination({
  offset,
  pageSize,
  total,
  noun,
  nounPlural,
  onOffsetChange,
}: PaginationProps) {
  const plural = nounPlural ?? `${noun}s`
  const first = total === 0 ? 0 : offset + 1
  const last = Math.min(offset + pageSize, total)
  const canPrev = offset > 0
  const canNext = offset + pageSize < total

  // Nothing to page through and nothing being hidden - stay out of the way.
  if (total <= pageSize && offset === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        {total} {total === 1 ? noun : plural}
      </p>
    )
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-xs text-muted-foreground" aria-live="polite">
        Showing {first}–{last} of {total} {total === 1 ? noun : plural}
      </p>
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="sm"
          disabled={!canPrev}
          aria-label="Previous page"
          onClick={() => onOffsetChange(Math.max(0, offset - pageSize))}
        >
          <ChevronLeft />
          Previous
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!canNext}
          aria-label="Next page"
          onClick={() => onOffsetChange(offset + pageSize)}
        >
          Next
          <ChevronRight />
        </Button>
      </div>
    </div>
  )
}
