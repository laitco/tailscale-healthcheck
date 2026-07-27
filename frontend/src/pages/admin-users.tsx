import { useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert } from '@/components/ui/alert'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { fetchUsers, createUser, deleteUser, errorMessage, type AdminUser } from '@/lib/admin-api'
import { useTimezone } from '@/lib/health-context'
import { formatDateTime } from '@/lib/format'

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)
  const timezone = useTimezone()

  function load() {
    // Without this catch the rejection was unhandled and `users` stayed null,
    // leaving the page on its loading skeleton forever with no explanation.
    setLoadError(null)
    fetchUsers()
      .then((data) => setUsers(data.users))
      .catch((err) => {
        setUsers([])
        setLoadError(errorMessage(err, 'Failed to load users'))
      })
  }

  useEffect(load, [])

  async function onCreate(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await createUser(username, password)
      setUsername('')
      setPassword('')
      load()
    } catch (err) {
      setError(errorMessage(err, 'Failed to create user'))
    } finally {
      setSubmitting(false)
    }
  }

  async function onDelete(user: string) {
    setPendingDelete(null)
    setError(null)
    try {
      await deleteUser(user)
      load()
    } catch (err) {
      setError(errorMessage(err, 'Failed to delete user'))
    }
  }

  return (
    <div className="max-w-2xl space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Add a user</CardTitle>
          <CardDescription>Anyone with a login can access the dashboard and this admin UI.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="flex flex-wrap items-end gap-2" onSubmit={onCreate}>
            {error && (
              <Alert className="w-full p-2 text-xs">{error}</Alert>
            )}
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="new-username">
                Username
              </label>
              <Input id="new-username" value={username} onChange={(e) => setUsername(e.target.value)} required />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="new-user-password">
                Password
              </label>
              <Input
                id="new-user-password"
                type="password"
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <Button type="submit" disabled={submitting}>
              {submitting ? 'Adding…' : 'Add user'}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Users</CardTitle>
        </CardHeader>
        <CardContent>
          {loadError ? (
            <Alert>{loadError}</Alert>
          ) : !users ? (
            <Skeleton className="h-24" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Username</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Last login</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {users.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell>{u.username}</TableCell>
                    <TableCell>{formatDateTime(u.created_at, timezone)}</TableCell>
                    <TableCell>{u.last_login_at ? formatDateTime(u.last_login_at, timezone) : '—'}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        disabled={users.length <= 1}
                        aria-label={`Delete user ${u.username}`}
                        onClick={() => setPendingDelete(u.username)}
                      >
                        <Trash2 />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => !open && setPendingDelete(null)}
        title={`Delete user "${pendingDelete}"?`}
        description="This immediately revokes their access. It cannot be undone."
        confirmLabel="Delete user"
        onConfirm={() => pendingDelete && onDelete(pendingDelete)}
      />
    </div>
  )
}
