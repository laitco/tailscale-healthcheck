import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

// The destructive variant reproduces the inline markup that used to be
// hand-copied into nine different pages; success/info exist so those pages
// stop inventing their own (previously text-primary in one place and
// text-success in another for the same kind of message).
const alertVariants = cva("rounded-md border p-4 text-sm", {
  variants: {
    variant: {
      destructive: "border-destructive/50 bg-destructive/10 text-destructive",
      success: "border-success/50 bg-success/10 text-success",
      info: "border-border bg-muted/50 text-muted-foreground",
    },
  },
  defaultVariants: {
    variant: "destructive",
  },
})

function Alert({
  className,
  variant,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof alertVariants>) {
  return (
    <div
      // assertive for errors: a failed save or a dead backend should interrupt
      // a screen reader rather than wait for a pause in whatever it's reading.
      role={variant === "destructive" ? "alert" : "status"}
      aria-live={variant === "destructive" ? "assertive" : "polite"}
      className={cn(alertVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Alert, alertVariants }
