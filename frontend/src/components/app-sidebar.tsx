import { LayoutDashboard, Laptop, KeyRound, Bug, Network, RefreshCw, Settings, Users, ScrollText, LogOut, BookOpen } from 'lucide-react'
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
import { useHealthContext } from '@/lib/health-context'
import { logout } from '@/lib/admin-api'
import { cn } from '@/lib/utils'

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
      <SidebarMenu className="p-2">
        <SidebarMenuItem>
          <SidebarMenuButton onClick={refresh} disabled={loading} tooltip="Refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton onClick={onLogout} tooltip="Log out">
            <LogOut />
            <span>Log out</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </Sidebar>
  )
}
