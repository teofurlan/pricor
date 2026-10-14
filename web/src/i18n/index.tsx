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

export interface I18n {
  language: Language;
  setLanguage(language: Language): void;
  t(key: TextKey, params?: Params): string;
}

const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({
  children,
  initialLanguage = "en",
}: {
  children: ReactNode;
  initialLanguage?: Language;
}) {
  const [language, setLanguage] = useState<Language>(initialLanguage);

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
