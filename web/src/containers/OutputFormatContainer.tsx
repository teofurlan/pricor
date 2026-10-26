import { useEffect, useState } from "react";
import { ApiError, type OutputFormatApiClient } from "../api/client";
import type { OutputFormat } from "../api/types";
import { OutputFormatPanel } from "../components/organisms/OutputFormatPanel";
import { useI18n } from "../i18n";
import { describeError } from "../i18n/serverText";

/**
 * The product file's fields, in file order, mirroring the server's `OUTPUT_FIELDS`. The server
 * sends them with a stored format; they are needed here only while there is none.
 */
export const OUTPUT_FIELDS = [
  "supplier_code", "description", "unit_cost_net", "currency", "vat_rate", "units_per_pack", "barcode",
  "suggested_retail_price", "unit_cost_net_converted", "fx_rate", "fx_source", "fx_date", "source_row",
];

interface Props {
  api: OutputFormatApiClient;
  /** The stored format after every load or change; null when the standard format applies. */
  onChange?(format: OutputFormat | null): void;
}

export function OutputFormatContainer({ api, onChange }: Props) {
  const [format, setFormat] = useState<OutputFormat | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  // The failure itself, not its text, so the message follows the interface language.
  const [failure, setFailure] = useState<unknown>(null);

  function publish(next: OutputFormat | null) {
    setFormat(next);
    onChange?.(next);
  }

  const { language } = useI18n();
  const message = (failure: unknown) =>
    failure instanceof ApiError ? describeError(failure, language) : failure instanceof Error ? failure.message : String(failure);

  useEffect(() => {
    let active = true;
    api.getOutputFormat()
      .then((stored) => { if (active) publish(stored); })
      .catch((caught: unknown) => { if (active) setFailure(caught); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
    // The API instance is stable for the app lifetime; the format is loaded once per mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  async function change(action: () => Promise<OutputFormat | null>) {
    setBusy(true);
    setFailure(null);
    try {
      publish(await action());
    } catch (caught) {
      setFailure(caught);
    } finally {
      setBusy(false);
    }
  }

  return (
    <OutputFormatPanel
      format={format}
      loading={loading}
      busy={busy}
      error={failure === null ? null : message(failure)}
      fields={OUTPUT_FIELDS}
      onUpload={(file) => void change(() => api.uploadOutputFormat(file))}
      onSave={(columns) => void change(() => api.defineOutputFormat(columns))}
      onRemove={() => void change(async () => { await api.deleteOutputFormat(); return null; })}
    />
  );
}
