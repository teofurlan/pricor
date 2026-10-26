import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Language } from "../api/types";
import { en, type TextKey } from "./en";
import { es } from "./es";

export type { TextKey } from "./en";

const DICTIONARIES: Record<Language, Record<TextKey, string>> = { en, es };

export type Params = Record<string, string | number>;

/** Replaces `{name}` placeholders; an unknown placeholder stays visible. */
export function interpolate(template: string, params: Params = {}): string {
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in params ? String(params[name]) : match,
  );
}

/** True when `key` is a defined dictionary key (for keys built at runtime). */
export function isTextKey(key: string): key is TextKey {
  return key in en;
}

export const LANGUAGE_STORAGE_KEY = "pricor.language";

export function getStoredLanguage(): Language | null {
  try {
    const value = localStorage.getItem(LANGUAGE_STORAGE_KEY);
    if (value === "en" || value === "es") return value;
    return null;
  } catch {
    return null;
  }
}

export function setStoredLanguage(language: Language): void {
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // blocked storage never breaks the app
  }
}

export function detectLanguage(): Language {
  const stored = getStoredLanguage();
  if (stored) return stored;

  try {
    if (typeof navigator !== "undefined" && typeof navigator.language === "string") {
      if (navigator.language.startsWith("en")) {
        return "en";
      }
    }
  } catch {
    // blocked or unavailable navigator falls back to Spanish
  }

  return "es";
}

export interface I18n {
  language: Language;
  setLanguage(language: Language): void;
  t(key: TextKey, params?: Params): string;
}

const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({
  children,
  initialLanguage,
}: {
  children: ReactNode;
  initialLanguage?: Language;
}) {
  const [language, setLanguage] = useState<Language>(() => initialLanguage ?? detectLanguage());

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const t = useCallback(
    (key: TextKey, params?: Params) => interpolate(DICTIONARIES[language][key] ?? en[key], params),
    [language],
  );
  const value = useMemo(() => ({ language, setLanguage, t }), [language, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const context = useContext(I18nContext);
  if (!context) throw new Error("useI18n must be used inside <I18nProvider>");
  return context;
}
