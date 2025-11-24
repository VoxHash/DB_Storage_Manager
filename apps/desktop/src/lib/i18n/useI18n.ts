import { useState, useEffect } from 'react'
import { translations } from './translations'

type Language = 'en' | 'es' | 'fr' | 'de'

export function useI18n() {
  const [language, setLanguage] = useState<Language>('en')

  useEffect(() => {
    // Load saved language from localStorage
    const savedLanguage = localStorage.getItem('db-manager-language') as Language
    if (savedLanguage && translations[savedLanguage]) {
      setLanguage(savedLanguage)
    }
  }, [])

  const changeLanguage = (newLanguage: Language) => {
    setLanguage(newLanguage)
    localStorage.setItem('db-manager-language', newLanguage)
    console.log('Language changed to:', newLanguage)
  }

  const t = (key: string): string => {
    const keys = key.split('.')
    let value: any = translations[language]
    
    for (const k of keys) {
      value = value?.[k]
    }
    
    return value || key
  }

  return {
    language,
    changeLanguage,
    t
  }
}