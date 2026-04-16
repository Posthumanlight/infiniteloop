export function getTelegramWebApp(): TelegramWebApp | null {
  if (typeof window === 'undefined') {
    return null;
  }
  return window.Telegram?.WebApp ?? null;
}

export function applyTelegramTheme(webApp: TelegramWebApp | null): void {
  if (!webApp?.themeParams || typeof document === 'undefined') {
    return;
  }

  const root = document.documentElement;
  for (const [key, value] of Object.entries(webApp.themeParams)) {
    root.style.setProperty(`--tg-${key.replace(/_/g, '-')}`, value);
  }
}
