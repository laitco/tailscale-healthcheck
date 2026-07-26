import { useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchUsers, createUser, deleteUser, AdminApiError, type AdminUser } from '@/lib/admin-api'

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  function load() {
    fetchUsers().then((data) => setUsers(data.users))
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
      setError(err instanceof AdminApiError ? err.message : 'Failed to create user')
    } finally {
      setSubmitting(false)
    }
  }

  async function onDelete(user: string) {
    if (!confirm(`Delete user "${user}"?`)) return
    setError(null)
    try {
      await deleteUser(user)
      load()
    } catch (err) {
      setError(err instanceof AdminApiError ? err.message : 'Failed to delete user')
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
              <div className="w-full rounded-md border border-destructive/50 bg-destructive/10 p-2 text-xs text-destructive">
                {error}
              </div>
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
          {!users ? (
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
                    <TableCell>{new Date(u.created_at).toLocaleString()}</TableCell>
                    <TableCell>{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : '—'}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        disabled={users.length <= 1}
                        onClick={() => onDelete(u.username)}
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
    </div>
  )
}
