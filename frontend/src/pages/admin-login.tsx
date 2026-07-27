import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AdminAuthLayout } from '@/components/admin-auth-layout'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { login, loginMfa, errorMessage } from '@/lib/admin-api'
import { Alert } from '@/components/ui/alert'

export default function AdminLoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [mfaRequired, setMfaRequired] = useState(false)
  const [code, setCode] = useState('')
  const [useRecoveryCode, setUseRecoveryCode] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const res = await login(username, password)
      if (res.mfa_required) {
        setMfaRequired(true)
      } else {
        navigate('/dashboard')
      }
    } catch (err) {
      setError(errorMessage(err, 'Login failed'))
    } finally {
      setSubmitting(false)
    }
  }

  async function onSubmitMfa(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await loginMfa(useRecoveryCode ? { recovery_code: code } : { code })
      navigate('/dashboard')
    } catch (err) {
      setError(errorMessage(err, 'Verification failed'))
    } finally {
      setSubmitting(false)
    }
  }

  if (mfaRequired) {
    return (
      <AdminAuthLayout
        title="Two-factor verification"
        description={useRecoveryCode ? 'Enter one of your recovery codes.' : 'Enter the code from your authenticator app.'}
      >
        <form className="space-y-3" onSubmit={onSubmitMfa}>
          {error && (
            <Alert className="p-2 text-xs">
              {error}
            </Alert>
          )}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="mfa-code">
              {useRecoveryCode ? 'Recovery code' : 'Verification code'}
            </label>
            <Input
              id="mfa-code"
              autoComplete="one-time-code"
              inputMode={useRecoveryCode ? 'text' : 'numeric'}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              autoFocus
              required
            />
          </div>
          <Button type="submit" className="w-full" disabled={submitting}>
            {submitting ? 'Verifying…' : 'Verify'}
          </Button>
          <Button
            type="button"
            variant="link"
            className="w-full"
            onClick={() => {
              setUseRecoveryCode((v) => !v)
              setCode('')
              setError(null)
            }}
          >
            {useRecoveryCode ? 'Use an authenticator code instead' : 'Use a recovery code instead'}
          </Button>
        </form>
      </AdminAuthLayout>
    )
  }

  return (
    <AdminAuthLayout title="Sign in" description="Sign in to access the dashboard and admin settings.">
      <form className="space-y-3" onSubmit={onSubmit}>
        {error && (
          <Alert className="p-2 text-xs">
            {error}
          </Alert>
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
