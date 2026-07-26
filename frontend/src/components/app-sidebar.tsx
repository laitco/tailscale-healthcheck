import { useEffect, useState } from 'react'
import { LayoutDashboard, Laptop, KeyRound, Bug, Network, RefreshCw, Settings, Users, ScrollText, LogOut, BookOpen, UserCircle } from 'lucide-react'
import { NavLink, useNavigate } from 'react-router-dom'
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useHealthContext } from '@/lib/health-context'
import { logout, fetchAdminStatus } from '@/lib/admin-api'
import { cn } from '@/lib/utils'

function VersionFooter() {
  const [version, setVersion] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchAdminStatus()
      .then((status) => {
        if (!cancelled) setVersion(status.version)
      })
      .catch(() => {
        // Version display is cosmetic - a failed fetch just leaves it blank.
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (!version) return null

  return (
    <div className="truncate px-2 pb-1 text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
      v{version}
    </div>
  )
}

const navItems = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/devices', label: 'Devices', icon: Laptop },
  { to: '/tailnet-keys', label: 'Tailnet Keys', icon: KeyRound },
  { to: '/debug', label: 'Debug', icon: Bug },
]

const adminItems = [
  { to: '/admin/settings', label: 'Settings', icon: Settings },
  { to: '/admin/users', label: 'Users', icon: Users },
  { to: '/admin/audit', label: 'Audit Log', icon: ScrollText },
  { to: '/admin/api-docs', label: 'API Docs', icon: BookOpen },
]

function ConnectionStatus() {
  const { health } = useHealthContext()
  const pollMeta = health?.poll_meta

  // Reuses the exact same signal the overview page's "can't reach Tailscale"
  // banner is driven by - last_poll_ok/last_poll_auth_error from the
  // background poller - rather than a second, potentially-diverging source
  // of truth for connectivity.
  let dotClass = 'bg-muted-foreground'
  let label = 'Checking connection…'
  let detail = 'No poll has completed yet.'
  if (pollMeta?.last_poll_ok === true) {
    dotClass = 'bg-success'
    label = 'Connected'
    detail = 'The Tailscale API is reachable.'
  } else if (pollMeta?.last_poll_ok === false) {
    dotClass = 'bg-destructive'
    label = pollMeta.last_poll_auth_error ? 'Auth error' : 'Disconnected'
    detail = pollMeta.last_poll_auth_error
      ? 'Check your auth token/OAuth credentials in Settings.'
      : pollMeta.last_poll_error || 'Unable to reach the Tailscale API.'
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-muted-foreground">
          <span className={cn('size-2 shrink-0 rounded-full', dotClass)} aria-hidden="true" />
          <span className="truncate group-data-[collapsible=icon]:hidden">{label}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent side="right">
        <div>
          <p className="font-medium">{label}</p>
          <p className="text-background/80">{detail}</p>
        </div>
      </TooltipContent>
    </Tooltip>
  )
}

export function AppSidebar() {
  const { refresh, loading } = useHealthContext()
  const navigate = useNavigate()
  const items = navItems

  async function onLogout() {
    try {
      await logout()
    } finally {
      navigate('/admin/login')
    }
  }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2 px-2 py-1.5">
          <Network className="size-5 shrink-0 text-primary" />
          <span className="truncate text-sm font-semibold tracking-tight group-data-[collapsible=icon]:hidden">
            Tailscale Healthcheck
          </span>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {items.map((item) => (
                <SidebarMenuItem key={item.to}>
                  <SidebarMenuButton asChild tooltip={item.label}>
                    <NavLink
                      to={item.to}
                      end={item.end}
                      className={({ isActive }) => cn(isActive && 'bg-sidebar-accent text-sidebar-accent-foreground')}
                    >
                      <item.icon />
                      <span>{item.label}</span>
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>Admin</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {adminItems.map((item) => (
                <SidebarMenuItem key={item.to}>
                  <SidebarMenuButton asChild tooltip={item.label}>
                    <NavLink
                      to={item.to}
                      className={({ isActive }) => cn(isActive && 'bg-sidebar-accent text-sidebar-accent-foreground')}
                    >
                      <item.icon />
                      <span>{item.label}</span>
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <div className="px-2 pt-2">
        <ConnectionStatus />
      </div>
      <SidebarMenu className="p-2 pt-1">
        <SidebarMenuItem>
          <SidebarMenuButton onClick={refresh} disabled={loading} tooltip="Refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton asChild tooltip="Profile">
            <NavLink
              to="/admin/profile"
              className={({ isActive }) => cn(isActive && 'bg-sidebar-accent text-sidebar-accent-foreground')}
            >
              <UserCircle />
              <span>Profile</span>
            </NavLink>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton onClick={onLogout} tooltip="Log out">
            <LogOut />
            <span>Log out</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
      <VersionFooter />
    </Sidebar>
  )
}
