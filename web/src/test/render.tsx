import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import type { Language } from "../api/types";
import { I18nProvider } from "../i18n";

export function renderWithI18n(ui: ReactElement, language: Language = "en") {
  return render(ui, {
    wrapper: ({ children }) => <I18nProvider initialLanguage={language}>{children}</I18nProvider>,
  });
}
