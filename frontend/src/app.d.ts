declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }

  interface TelegramWebApp {
    initData: string;
    colorScheme?: 'light' | 'dark';
    themeParams?: Record<string, string>;
    ready(): void;
    expand(): void;
  }
}

export {};
