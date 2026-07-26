import { useState, type KeyboardEvent } from "react"
import { X } from "lucide-react"

import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"

function splitTags(value: string): string[] {
  return value
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean)
}

function joinTags(tags: string[]): string {
  return tags.join(",")
}

export function TagInput({
  value,
  onChange,
  placeholder,
  disabled,
  className,
}: {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  disabled?: boolean
  className?: string
}) {
  const [draft, setDraft] = useState("")
  const tags = splitTags(value)

  function commitDraft() {
    const next = draft.trim()
    setDraft("")
    if (!next) return
    if (tags.includes(next)) return
    onChange(joinTags([...tags, next]))
  }

  function removeTag(tag: string) {
    onChange(joinTags(tags.filter((t) => t !== tag)))
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === "Tab" || e.key === ",") {
      if (draft.trim()) {
        e.preventDefault()
        commitDraft()
      }
      return
    }
    if (e.key === "Backspace" && !draft && tags.length > 0) {
      e.preventDefault()
      removeTag(tags[tags.length - 1])
    }
  }

  return (
    <div
      className={cn(
        "flex min-h-7 w-full flex-wrap items-center gap-1 rounded-md border border-input bg-input/20 px-1.5 py-1 transition-colors focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/30 dark:bg-input/30",
        disabled && "pointer-events-none cursor-not-allowed opacity-50",
        className
      )}
    >
      {tags.map((tag) => (
        <Badge key={tag} variant="outline" className="gap-1">
          {tag}
          {!disabled && (
            <button
              type="button"
              aria-label={`Remove ${tag}`}
              onClick={() => removeTag(tag)}
              className="text-muted-foreground hover:text-foreground"
            >
              <X className="size-2.5" />
            </button>
          )}
        </Badge>
      ))}
      <input
        className="h-5 min-w-24 flex-1 bg-transparent text-xs/relaxed outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={commitDraft}
        placeholder={tags.length === 0 ? placeholder : undefined}
        disabled={disabled}
      />
    </div>
  )
}
