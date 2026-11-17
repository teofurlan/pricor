import { useEffect, useMemo } from "react";
import { createApiClient } from "./api/client";
import { ServerConfigProvider } from "./api/serverConfig";
import { ImportWizard } from "./containers/ImportWizard";
import { I18nProvider } from "./i18n";

export function App() {
  const api = useMemo(() => createApiClient(), []);
  // Once per page load, in the background: Cloud Run only gives the model load CPU while a
  // request is open. Always sent (not gated on /config) so it never waits for anything else.
  useEffect(() => {
    void api.warmUp();
  }, [api]);
  return (
    <I18nProvider>
      <ServerConfigProvider api={api}>
        <ImportWizard api={api} />
      </ServerConfigProvider>
    </I18nProvider>
  );
}
