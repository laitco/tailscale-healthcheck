import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AdminAuthLayout } from '@/components/admin-auth-layout'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { login, AdminApiError } from '@/lib/admin-api'

export default function AdminLoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await login(username, password)
      navigate('/dashboard')
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : 'Login failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AdminAuthLayout title="Sign in" description="Sign in to access the dashboard and admin settings.">
      <form className="space-y-3" onSubmit={onSubmit}>
        {error && (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 p-2 text-xs text-destructive">
            {error}
          </div>
        )}
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground" htmlFor="username">
            Username
          </label>
          <Input
            id="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-medium text-muted-foreground" htmlFor="password">
            Password
          </label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>
    </AdminAuthLayout>
  )
}
