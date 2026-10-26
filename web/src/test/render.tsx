import { render } from "@testing-library/react";
import React, { type ReactElement } from "react";
import type { Language } from "../api/types";
import { I18nProvider } from "../i18n";

export function renderWithI18n(ui: ReactElement, language: Language = "en") {
  let currentLanguage = language;
  let updateLanguage: ((lang: Language) => void) | null = null;

  function Wrapper({ children }: { children: React.ReactNode }) {
    const [lang, setLang] = React.useState(currentLanguage);
    updateLanguage = setLang;
    return <I18nProvider initialLanguage={lang}>{children}</I18nProvider>;
  }

  const result = render(ui, {
    wrapper: Wrapper,
  });

  return {
    ...result,
    rerender(newUi: ReactElement, newLanguage?: Language) {
      if (newLanguage && newLanguage !== currentLanguage) {
        currentLanguage = newLanguage;
        updateLanguage?.(newLanguage);
      }
      return result.rerender(newUi);
    },
  };
}
