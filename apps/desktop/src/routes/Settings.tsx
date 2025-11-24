import React, { useState } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Settings as SettingsIcon, Bell, Globe, Shield } from 'lucide-react'
import { useI18n } from '@/lib/i18n/useI18n'

export default function Settings() {
  const { t, language, changeLanguage } = useI18n()
  const [notifications, setNotifications] = useState(true)
  const [telemetry, setTelemetry] = useState(false)
  const [autoStartup, setAutoStartup] = useState(false)

  const handleLanguageChange = (value: string) => {
    changeLanguage(value as any)
  }

  const handleNotificationChange = (checked: boolean) => {
    setNotifications(checked)
    console.log('Notifications:', checked ? 'enabled' : 'disabled')
  }

  const handleTelemetryChange = (checked: boolean) => {
    setTelemetry(checked)
    console.log('Telemetry:', checked ? 'enabled' : 'disabled')
  }

  const handleAutoStartupChange = (checked: boolean) => {
    setAutoStartup(checked)
    console.log('Auto-startup:', checked ? 'enabled' : 'disabled')
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center gap-2">
        <SettingsIcon className="h-6 w-6" />
        <h1 className="text-3xl font-bold">{t('settings')}</h1>
      </div>

      <div className="grid gap-6">
        {/* Language Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Globe className="h-5 w-5" />
              {t('languageRegion')}
            </CardTitle>
            <CardDescription>
              {t('chooseLanguage')}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label className="block text-sm font-medium mb-2">{t('language')}</label>
              <Select value={language} onValueChange={handleLanguageChange}>
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select language" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="en">English</SelectItem>
                  <SelectItem value="es">Español</SelectItem>
                  <SelectItem value="fr">Français</SelectItem>
                  <SelectItem value="de">Deutsch</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        {/* Notifications */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Bell className="h-5 w-5" />
              {t('notifications')}
            </CardTitle>
            <CardDescription>
              {t('manageNotifications')}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="font-medium">{t('enableNotifications')}</div>
                <div className="text-sm text-muted-foreground">
                  {t('receiveNotifications')}
                </div>
              </div>
              <Switch
                checked={notifications}
                onCheckedChange={handleNotificationChange}
              />
            </div>
          </CardContent>
        </Card>

        {/* Auto-startup */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <SettingsIcon className="h-5 w-5" />
              {t('startup')}
            </CardTitle>
            <CardDescription>
              {t('controlStartup')}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="font-medium">{t('startWithWindows')}</div>
                <div className="text-sm text-muted-foreground">
                  {t('launchWhenStarts')}
                </div>
              </div>
              <Switch
                checked={autoStartup}
                onCheckedChange={handleAutoStartupChange}
              />
            </div>
          </CardContent>
        </Card>

        {/* Privacy */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Shield className="h-5 w-5" />
              {t('privacy')}
            </CardTitle>
            <CardDescription>
              {t('controlDataCollection')}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="font-medium">{t('anonymousUsageData')}</div>
                <div className="text-sm text-muted-foreground">
                  {t('helpImprove')}
                </div>
              </div>
              <Switch
                checked={telemetry}
                onCheckedChange={handleTelemetryChange}
              />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}