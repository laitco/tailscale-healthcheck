import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { SidebarProvider, SidebarInset, SidebarTrigger } from '@/components/ui/sidebar'
import { AppSidebar } from '@/components/app-sidebar'
import { Separator } from '@/components/ui/separator'

const TITLES: { test: (path: string) => boolean; title: string }[] = [
  { test: (p) => p === '/' || p === '/dashboard', title: 'Overview' },
  { test: (p) => p === '/devices', title: 'Devices' },
  { test: (p) => p === '/tailnet-keys', title: 'Tailnet Keys' },
  { test: (p) => p === '/debug', title: 'Debug' },
  { test: (p) => p.startsWith('/device/'), title: 'Device' },
  { test: (p) => p === '/admin/settings', title: 'Settings' },
  { test: (p) => p === '/admin/users', title: 'Users' },
  { test: (p) => p === '/admin/audit', title: 'Audit Log' },
  { test: (p) => p === '/admin/api-docs', title: 'API Docs' },
]

function useTitle() {
  const { pathname } = useLocation()
  return TITLES.find((t) => t.test(pathname))?.title ?? 'Tailscale Healthcheck'
}

export function Layout({ children }: { children: ReactNode }) {
  const title = useTitle()
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
          <SidebarTrigger />
          <Separator orientation="vertical" className="mr-2 h-4" />
          <h1 className="text-sm font-medium">{title}</h1>
        </header>
        <main className="flex-1 overflow-x-auto p-4 sm:p-6">{children}</main>
      </SidebarInset>
    </SidebarProvider>
  )
}
