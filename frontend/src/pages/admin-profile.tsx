import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  fetchProfile,
  changePassword,
  enrollMfa,
  confirmMfa,
  disableMfa,
  AdminApiError,
  type ProfileResponse,
} from '@/lib/admin-api'

function ErrorBox({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <div className="rounded-md border border-destructive/50 bg-destructive/10 p-2 text-xs text-destructive">
      {message}
    </div>
  )
}

function ChangePasswordCard() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSuccess(false)
    if (newPassword !== confirmPassword) {
      setError('New password and confirmation do not match')
      return
    }
    setSubmitting(true)
    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setSuccess(true)
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : 'Failed to change password')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Change password</CardTitle>
        <CardDescription>Requires your current password.</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="max-w-sm space-y-3" onSubmit={onSubmit}>
          <ErrorBox message={error} />
          {success && (
            <div className="rounded-md border border-success/50 bg-success/10 p-2 text-xs text-success">
              Password updated.
            </div>
          )}
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="current-password">
              Current password
            </label>
            <Input
              id="current-password"
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="new-password">
              New password
            </label>
            <Input
              id="new-password"
              type="password"
              autoComplete="new-password"
              minLength={8}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-muted-foreground" htmlFor="confirm-password">
              Confirm new password
            </label>
            <Input
              id="confirm-password"
              type="password"
              autoComplete="new-password"
              minLength={8}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
            />
          </div>
          <Button type="submit" disabled={submitting}>
            {submitting ? 'Saving…' : 'Update password'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

type EnrollState = { secret: string; provisioning_uri: string } | null

function MfaCard({ profile, onChanged }: { profile: ProfileResponse; onChanged: () => void }) {
  const [enroll, setEnroll] = useState<EnrollState>(null)
  const [confirmCode, setConfirmCode] = useState('')
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null)
  const [disableCode, setDisableCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onStartEnroll() {
    setError(null)
    setSubmitting(true)
    try {
      setEnroll(await enrollMfa())
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : 'Failed to start MFA enrollment')
    } finally {
      setSubmitting(false)
    }
  }

  async function onConfirm(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const res = await confirmMfa(confirmCode)
      setRecoveryCodes(res.recovery_codes)
      setEnroll(null)
      setConfirmCode('')
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : 'Invalid verification code')
    } finally {
      setSubmitting(false)
    }
  }

  async function onDisable(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await disableMfa(disableCode)
      setDisableCode('')
      onChanged()
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : 'Failed to disable MFA')
    } finally {
      setSubmitting(false)
    }
  }

  function onDoneWithRecoveryCodes() {
    setRecoveryCodes(null)
    onChanged()
  }

  if (recoveryCodes) {
    return (
      <Card className="border-primary/50">
        <CardHeader>
          <CardTitle>Save your recovery codes</CardTitle>
          <CardDescription>
            Each code can be used once to sign in if you lose access to your authenticator app. They are shown only
            this one time and cannot be retrieved again.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-2 rounded-md border bg-muted/40 p-3 font-mono text-sm sm:grid-cols-3">
            {recoveryCodes.map((code) => (
              <span key={code}>{code}</span>
            ))}
          </div>
          <Button onClick={onDoneWithRecoveryCodes}>I've saved these codes</Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Two-factor authentication</CardTitle>
        <CardDescription>
          {profile.mfa.enabled
            ? 'Enabled - a verification code is required at sign-in.'
            : 'Add an authenticator app (TOTP) as a second sign-in factor.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <ErrorBox message={error} />

        {profile.mfa.enabled ? (
          <form className="max-w-sm space-y-3" onSubmit={onDisable}>
            <p className="text-sm text-muted-foreground">
              Enter a current code from your authenticator app to disable MFA.
            </p>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="disable-code">
                Verification code
              </label>
              <Input
                id="disable-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={disableCode}
                onChange={(e) => setDisableCode(e.target.value)}
                required
              />
            </div>
            <Button type="submit" variant="destructive" disabled={submitting}>
              {submitting ? 'Disabling…' : 'Disable MFA'}
            </Button>
          </form>
        ) : enroll ? (
          <form className="max-w-sm space-y-3" onSubmit={onConfirm}>
            <p className="text-sm text-muted-foreground">
              Scan this into your authenticator app, or enter the key manually, then confirm with a generated code.
            </p>
            <div className="space-y-1 rounded-md border bg-muted/40 p-3">
              <p className="text-xs font-medium text-muted-foreground">Manual entry key</p>
              <p className="break-all font-mono text-sm">{enroll.secret}</p>
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="confirm-code">
                Verification code
              </label>
              <Input
                id="confirm-code"
                inputMode="numeric"
                autoComplete="one-time-code"
                value={confirmCode}
                onChange={(e) => setConfirmCode(e.target.value)}
                required
              />
            </div>
            <div className="flex gap-2">
              <Button type="submit" disabled={submitting}>
                {submitting ? 'Confirming…' : 'Confirm and enable'}
              </Button>
              <Button type="button" variant="ghost" onClick={() => setEnroll(null)}>
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <Button onClick={onStartEnroll} disabled={submitting}>
            {submitting ? 'Starting…' : 'Enable two-factor authentication'}
          </Button>
        )}
      </CardContent>
    </Card>
  )
}

export default function AdminProfilePage() {
  const [profile, setProfile] = useState<ProfileResponse | null>(null)

  function load() {
    fetchProfile().then(setProfile)
  }

  useEffect(load, [])

  return (
    <div className="max-w-2xl space-y-4">
      {profile && (
        <Card>
          <CardHeader>
            <CardTitle>{profile.username}</CardTitle>
            <CardDescription>Your account</CardDescription>
          </CardHeader>
        </Card>
      )}
      <ChangePasswordCard />
      {!profile ? <Skeleton className="h-40" /> : <MfaCard profile={profile} onChanged={load} />}
    </div>
  )
}
