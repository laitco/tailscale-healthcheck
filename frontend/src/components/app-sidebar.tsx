import { LayoutDashboard, Laptop, KeyRound, Bug, Network, RefreshCw } from 'lucide-react'
import { NavLink } from 'react-router-dom'
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
import { cn } from '@/lib/utils'

const navItems = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/devices', label: 'Devices', icon: Laptop },
  { to: '/tailnet-keys', label: 'Tailnet Keys', icon: KeyRound },
]

export function AppSidebar() {
  const { refresh, loading, health } = useHealthContext()
  const items = health?.settings
    ? [...navItems, { to: '/debug', label: 'Debug', icon: Bug }]
    : navItems

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
      </SidebarContent>
      <SidebarMenu className="p-2">
        <SidebarMenuItem>
          <SidebarMenuButton onClick={refresh} disabled={loading} tooltip="Refresh">
            <RefreshCw className={loading ? 'animate-spin' : ''} />
            <span>Refresh</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </Sidebar>
  )
}
