import { useMemo } from "react";
import { createApiClient } from "./api/client";
import { ServerConfigProvider } from "./api/serverConfig";
import { ImportWizard } from "./containers/ImportWizard";
import { I18nProvider } from "./i18n";

export function App() {
  const api = useMemo(() => createApiClient(), []);
  return (
    <I18nProvider>
      <ServerConfigProvider api={api}>
        <ImportWizard api={api} />
      </ServerConfigProvider>
    </I18nProvider>
  );
}
