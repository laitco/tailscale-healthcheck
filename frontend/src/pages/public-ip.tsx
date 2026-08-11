import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, RefreshCw } from 'lucide-react'
import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { StatusBadge } from '@/components/status-badge'
import {
  createPublicIpMapping,
  deletePublicIpMapping,
  errorMessage,
  fetchPublicIpStatus,
  syncPublicIp,
  updatePublicIpMapping,
  type PublicIpMapping,
  type PublicIpStatus,
} from '@/lib/admin-api'
import { relativeTime } from '@/lib/format'
import { useNow } from '@/lib/use-now'
import { useToast } from '@/lib/toast'

const EMPTY = { hostname: '', posture_name: 'PublicAddress', enabled: true }
const ALL = '__all__'

function displayPosture(name: string) {
  return name.replace(/^posture:/, '')
}

function MappingStatus({ mapping }: { mapping: PublicIpMapping }) {
  if (!mapping.enabled) return <Badge variant="outline">Disabled</Badge>
  if (mapping.status === 'pending') return <Badge variant="secondary">Pending</Badge>
  return <StatusBadge ok={mapping.status === 'healthy'} trueText="Healthy" falseText="Error" />
}

export default function PublicIpPage() {
  const [data, setData] = useState<PublicIpStatus | null>(null)
  const [form, setForm] = useState(EMPTY)
  const [editing, setEditing] = useState<number | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState(ALL)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const { notify } = useToast()
  useNow(30000)

  async function load() {
    try {
      setData(await fetchPublicIpStatus())
      setError('')
    } catch (err) {
      setError(errorMessage(err, 'Failed to load public-IP mappings'))
    }
  }

  useEffect(() => { void load() }, [])

  async function submit() {
    setBusy(true)
    try {
      if (editing == null) await createPublicIpMapping(form)
      else await updatePublicIpMapping(editing, form)
      notify(editing == null ? 'Mapping added.' : 'Mapping updated.')
      setForm(EMPTY)
      setEditing(null)
      setShowForm(false)
      await load()
    } catch (err) {
      notify(errorMessage(err, 'Failed to save mapping'), 'error')
    } finally {
      setBusy(false)
    }
  }

  function beginEdit(mapping: PublicIpMapping) {
    setEditing(mapping.id)
    setForm({ hostname: mapping.hostname, posture_name: displayPosture(mapping.posture_name), enabled: mapping.enabled })
    setShowForm(true)
  }

  async function remove(mapping: PublicIpMapping) {
    if (!window.confirm(`Delete the mapping for ${displayPosture(mapping.posture_name)}?`)) return
    setBusy(true)
    try {
      await deletePublicIpMapping(mapping.id)
      await load()
      notify('Mapping deleted.')
    } catch (err) {
      notify(errorMessage(err, 'Failed to delete mapping'), 'error')
    } finally {
      setBusy(false)
    }
  }

  async function sync(id?: number) {
    setBusy(true)
    try {
      const result = await syncPublicIp(id)
      await load()
      notify(result.changed ? `Updated ${result.changed} posture rule(s).` : result.message || 'Already current.')
    } catch (err) {
      await load()
      notify(errorMessage(err, 'Public-IP synchronization failed'), 'error')
    } finally {
      setBusy(false)
    }
  }

  async function setMappingEnabled(mapping: PublicIpMapping, enabled: boolean) {
    setBusy(true)
    try {
      await updatePublicIpMapping(mapping.id, {
        hostname: mapping.hostname,
        posture_name: displayPosture(mapping.posture_name),
        enabled,
      })
      await load()
    } catch (err) {
      await load()
      notify(errorMessage(err, 'Failed to update mapping'), 'error')
    } finally {
      setBusy(false)
    }
  }

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()
    return (data?.mappings ?? []).filter((mapping) => {
      if (query && !`${mapping.hostname} ${mapping.posture_name} ${mapping.resolved_ip || ''} ${mapping.configured_ip || ''}`.toLowerCase().includes(query)) return false
      if (status === 'enabled' && !mapping.enabled) return false
      if (status === 'disabled' && mapping.enabled) return false
      if (status === 'healthy' && (!mapping.enabled || mapping.status !== 'healthy')) return false
      if (status === 'error' && (!mapping.enabled || mapping.status !== 'error')) return false
      if (status === 'pending' && (!mapping.enabled || mapping.status !== 'pending')) return false
      return true
    })
  }, [data, search, status])

  if (!data) return <Alert>{error || 'Loading public-IP mappings…'}</Alert>

  return (
    <div className="space-y-4">
      {error && <Alert>{error}</Alert>}
      {!data.settings.public_ip_updater_enabled && (
        <Alert className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="font-medium">DynDNS posture updates are disabled</p>
            <p className="text-xs text-muted-foreground">Mappings remain available for manual synchronization.</p>
          </div>
          <Button asChild variant="outline" size="sm"><Link to="/admin/settings">Open settings</Link></Button>
        </Alert>
      )}

      <section className="flex flex-wrap items-center gap-2">
        <Input placeholder="Search posture, hostname, or IP" value={search} onChange={(event) => setSearch(event.target.value)} className="max-w-xs" />
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-40"><SelectValue placeholder="All status" /></SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>All status</SelectItem>
            <SelectItem value="healthy">Healthy</SelectItem>
            <SelectItem value="error">Error</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="enabled">Enabled</SelectItem>
            <SelectItem value="disabled">Disabled</SelectItem>
          </SelectContent>
        </Select>
        <div className="flex-1" />
        <Button variant="outline" disabled={busy || !data.mappings.some((mapping) => mapping.enabled)} onClick={() => void sync()}>
          <RefreshCw className={busy ? 'animate-spin' : ''} /> Sync all
        </Button>
        <Button onClick={() => { setEditing(null); setForm(EMPTY); setShowForm(true) }}><Plus /> Add mapping</Button>
      </section>

      {showForm && (
        <Card>
          <CardHeader>
            <CardTitle>{editing == null ? 'Add mapping' : 'Edit mapping'}</CardTitle>
            <CardDescription>The posture: prefix is added automatically.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-[1fr_1fr_auto] md:items-end">
            <label className="space-y-1 text-sm">DynDNS hostname
              <Input value={form.hostname} placeholder="home.example.net" onChange={(event) => setForm({ ...form, hostname: event.target.value })} />
            </label>
            <label className="space-y-1 text-sm">Posture rule name
              <Input value={form.posture_name} placeholder="PublicAddress" onChange={(event) => setForm({ ...form, posture_name: event.target.value.replace(/^posture:/, '') })} />
            </label>
            <div className="flex gap-2">
              <Button disabled={busy || !form.hostname || !form.posture_name} onClick={() => void submit()}>{editing == null ? 'Add' : 'Save'}</Button>
              <Button variant="outline" onClick={() => { setShowForm(false); setEditing(null); setForm(EMPTY) }}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Status</TableHead>
              <TableHead>Posture Rule</TableHead>
              <TableHead>DynDNS Hostname</TableHead>
              <TableHead>DNS IP</TableHead>
              <TableHead>Policy IP</TableHead>
              <TableHead>Last Checked</TableHead>
              <TableHead>Last Changed</TableHead>
              <TableHead>Backup</TableHead>
              <TableHead>Enabled</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filtered.length === 0 && (
              <TableRow><TableCell colSpan={10} className="text-center text-muted-foreground">No mappings match your filters.</TableCell></TableRow>
            )}
            {filtered.map((mapping) => (
              <TableRow key={mapping.id}>
                <TableCell><MappingStatus mapping={mapping} /></TableCell>
                <TableCell className="font-medium">{displayPosture(mapping.posture_name)}</TableCell>
                <TableCell>{mapping.hostname}</TableCell>
                <TableCell>{mapping.resolved_ip || '—'}</TableCell>
                <TableCell>{mapping.configured_ip || '—'}</TableCell>
                <TableCell title={mapping.last_checked_at || undefined}>{mapping.last_checked_at ? relativeTime(mapping.last_checked_at) : 'Never'}</TableCell>
                <TableCell title={mapping.last_changed_at || undefined}>{mapping.last_changed_at ? relativeTime(mapping.last_changed_at) : 'Never'}</TableCell>
                <TableCell className="max-w-48 truncate" title={mapping.last_backup || undefined}>{mapping.last_backup || '—'}</TableCell>
                <TableCell>
                  <Switch checked={mapping.enabled} disabled={busy} aria-label={`Enable ${displayPosture(mapping.posture_name)}`}
                    onCheckedChange={(enabled) => void setMappingEnabled(mapping, enabled)} />
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1">
                    <Button size="sm" variant="outline" disabled={busy || !mapping.enabled} onClick={() => void sync(mapping.id)}>Sync</Button>
                    <Button size="sm" variant="outline" disabled={busy} onClick={() => beginEdit(mapping)}>Edit</Button>
                    <Button size="sm" variant="destructive" disabled={busy} onClick={() => void remove(mapping)}>Delete</Button>
                  </div>
                  {mapping.last_error && <p className="mt-1 max-w-72 whitespace-normal text-right text-xs text-destructive" title={mapping.last_error}>{mapping.last_error}</p>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">Showing {filtered.length} of {data.mappings.length} mappings.</p>
    </div>
  )
}
