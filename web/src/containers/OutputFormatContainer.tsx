import { useEffect, useState } from "react";
import { ApiError, type OutputFormatApiClient } from "../api/client";
import type { OutputFormat } from "../api/types";
import { OutputFormatPanel } from "../components/organisms/OutputFormatPanel";
import { SideDrawer } from "../components/organisms/SideDrawer";
import { useI18n } from "../i18n";

interface Props {
  api: OutputFormatApiClient;
  open: boolean;
  onClose(): void;
  /** The stored format after every load or change; null when the standard format applies. */
  onChange?(format: OutputFormat | null): void;
}

export function OutputFormatContainer({ api, open, onClose, onChange }: Props) {
  const { t } = useI18n();
  const [format, setFormat] = useState<OutputFormat | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function publish(next: OutputFormat | null) {
    setFormat(next);
    onChange?.(next);
  }

  const message = (failure: unknown) =>
    failure instanceof ApiError || failure instanceof Error ? failure.message : String(failure);

  useEffect(() => {
    let active = true;
    api.getOutputFormat()
      .then((stored) => { if (active) publish(stored); })
      .catch((failure: unknown) => { if (active) setError(message(failure)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
    // The API instance is stable for the app lifetime; the format is loaded once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  async function change(action: () => Promise<OutputFormat | null>) {
    setBusy(true);
    setError(null);
    try {
      publish(await action());
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SideDrawer open={open} label={t("format.title")} closeLabel={t("format.close")} onClose={onClose} className="format-drawer">
      <OutputFormatPanel
        format={format}
        loading={loading}
        busy={busy}
        error={error}
        onUpload={(file) => void change(() => api.uploadOutputFormat(file))}
        onConfirm={(sources) => void change(() => api.confirmOutputFormat(sources))}
        onRemove={() => void change(async () => { await api.deleteOutputFormat(); return null; })}
      />
    </SideDrawer>
  );
}
