import { SettingsPanel } from '@/components/settings-panel'
import { useHealthContext } from '@/lib/health-context'

export default function DebugPage() {
  const { health } = useHealthContext()

  if (!health?.settings) {
    return <p className="text-sm text-muted-foreground">DISPLAY_SETTINGS_IN_OUTPUT is not enabled.</p>
  }

  return <SettingsPanel settings={health.settings} />
}
