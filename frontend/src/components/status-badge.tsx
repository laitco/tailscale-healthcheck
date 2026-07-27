import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

export function StatusBadge({
  ok,
  trueText,
  falseText,
  title,
}: {
  ok: boolean
  trueText: string
  falseText: string
  title?: string
}) {
  return (
    <Badge
      variant="outline"
      title={title}
      className={cn(
        'border-transparent',
        ok
          ? 'bg-success/10 text-success dark:bg-success/20'
          : 'bg-destructive/10 text-destructive dark:bg-destructive/20',
      )}
    >
      {ok ? trueText : falseText}
    </Badge>
  )
}
