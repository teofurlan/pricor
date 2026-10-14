import { useMemo } from "react";
import { createApiClient } from "./api/client";
import { ImportWizard } from "./containers/ImportWizard";
import { I18nProvider } from "./i18n";

export function App() {
  const api = useMemo(() => createApiClient(), []);
  return (
    <I18nProvider>
      <ImportWizard api={api} />
    </I18nProvider>
  );
}
