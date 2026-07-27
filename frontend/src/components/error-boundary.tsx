import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/**
 * Catches render-time exceptions so one broken component degrades to a message
 * instead of unmounting the whole app and leaving a blank white page - React
 * unmounts the entire tree on an uncaught render error, which previously meant
 * a single bad field on one page blanked the entire dashboard.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Unhandled UI error:', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div
        role="alert"
        className="space-y-3 rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive"
      >
        <div>
          <p className="font-medium">Something went wrong rendering this page.</p>
          <p className="text-xs text-destructive/90">{this.state.error.message}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => this.setState({ error: null })}>
          Try again
        </Button>
      </div>
    )
  }
}
