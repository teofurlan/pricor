import { useEffect, useState } from "react";
import { ApiError, type OutputFormatApiClient } from "../api/client";
import type { OutputFormat } from "../api/types";
import { OutputFormatPanel } from "../components/organisms/OutputFormatPanel";

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
    // The API instance is stable for the app lifetime; the format is loaded once per mount.
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
    <OutputFormatPanel
      format={format}
      loading={loading}
      busy={busy}
      error={error}
      fields={OUTPUT_FIELDS}
      onUpload={(file) => void change(() => api.uploadOutputFormat(file))}
      onSave={(columns) => void change(() => api.defineOutputFormat(columns))}
      onRemove={() => void change(async () => { await api.deleteOutputFormat(); return null; })}
    />
  );
}
