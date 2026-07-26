import { Route, Routes } from 'react-router-dom'
import { TooltipProvider } from '@/components/ui/tooltip'
import { Layout } from '@/components/layout'
import OverviewPage from '@/pages/overview'
import DevicesPage from '@/pages/devices'
import TailnetKeysPage from '@/pages/tailnet-keys'
import DebugPage from '@/pages/debug'
import DeviceDetailPage from '@/pages/device-detail'
import NotFoundPage from '@/pages/not-found'
import { useSystemTheme } from '@/lib/use-system-theme'
import { HealthProvider } from '@/lib/health-context'

export default function App() {
  useSystemTheme()
  return (
    <TooltipProvider>
      <HealthProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/dashboard" element={<OverviewPage />} />
            <Route path="/devices" element={<DevicesPage />} />
            <Route path="/tailnet-keys" element={<TailnetKeysPage />} />
            <Route path="/debug" element={<DebugPage />} />
            <Route path="/device/:identifier" element={<DeviceDetailPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </Layout>
      </HealthProvider>
    </TooltipProvider>
  )
}
