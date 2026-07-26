import { Route, Routes } from 'react-router-dom'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Layout } from '@/components/layout'
import OverviewPage from '@/pages/overview'
import DevicesPage from '@/pages/devices'
import TailnetKeysPage from '@/pages/tailnet-keys'
import DebugPage from '@/pages/debug'
import DeviceDetailPage from '@/pages/device-detail'
import NotFoundPage from '@/pages/not-found'
import AdminSetupPage from '@/pages/admin-setup'
import AdminLoginPage from '@/pages/admin-login'
import AdminSettingsPage from '@/pages/admin-settings'
import AdminUsersPage from '@/pages/admin-users'
import AdminAuditPage from '@/pages/admin-audit'
import ApiDocsPage from '@/pages/api-docs'
import { useSystemTheme } from '@/lib/use-system-theme'
import { HealthProvider } from '@/lib/health-context'

export default function App() {
  useSystemTheme()
  return (
    <TooltipProvider>
      <Routes>
        {/* Standalone, unauthenticated shell - no sidebar, no /health fetch */}
        <Route path="/admin/setup" element={<AdminSetupPage />} />
        <Route path="/admin/login" element={<AdminLoginPage />} />

        {/* Everything else shares the authenticated dashboard chrome */}
        <Route
          path="*"
          element={
            <HealthProvider>
              <Layout>
                <Routes>
                  <Route path="/" element={<OverviewPage />} />
                  <Route path="/dashboard" element={<OverviewPage />} />
                  <Route path="/devices" element={<DevicesPage />} />
                  <Route path="/tailnet-keys" element={<TailnetKeysPage />} />
                  <Route path="/debug" element={<DebugPage />} />
                  <Route path="/device/:identifier" element={<DeviceDetailPage />} />
                  <Route path="/admin/settings" element={<AdminSettingsPage />} />
                  <Route path="/admin/users" element={<AdminUsersPage />} />
                  <Route path="/admin/audit" element={<AdminAuditPage />} />
                  <Route path="/admin/api-docs" element={<ApiDocsPage />} />
                  <Route path="*" element={<NotFoundPage />} />
                </Routes>
              </Layout>
            </HealthProvider>
          }
        />
      </Routes>
    </TooltipProvider>
  )
}
