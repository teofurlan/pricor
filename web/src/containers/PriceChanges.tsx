import { useCallback, useEffect, useState } from "react";
import type { ApiClient, ApiError } from "../api/client";
import type { PriceReport } from "../api/types";
import { ErrorBanner } from "../components/organisms/ErrorBanner";
import { PriceReportView } from "../components/organisms/PriceReportView";
import { useI18n } from "../i18n";
import { percentToRatio, ratioToPercent } from "../lib/percent";
import { toApiError } from "./usePreview";

const STORAGE_KEY = "pricor.anomalyThresholdPercent";

type Load =
  | { state: "loading" }
  | { state: "first_import" }
  | { state: "failed"; error: ApiError }
  | { state: "ready"; report: PriceReport };

// The threshold the user picked last is a per-browser convenience; the page works without it.
function rememberedThreshold(): string | undefined {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === null ? undefined : (percentToRatio(stored) ?? undefined);
  } catch {
    return undefined;
  }
}

function remember(ratio: string) {
  try {
    localStorage.setItem(STORAGE_KEY, ratioToPercent(ratio));
  } catch {
    // Storage can be blocked; the threshold simply is not remembered.
  }
}

/** The price-change report of an approved import, or a quiet note when there is nothing to compare. */
export function PriceChanges({
  api,
  sessionId,
  supplierName,
}: {
  api: ApiClient;
  sessionId: string;
  supplierName: string;
}) {
  const { t } = useI18n();
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [busy, setBusy] = useState(false);

  const fetchReport = useCallback(
    async (threshold: string | undefined) => {
      setBusy(true);
      try {
        setLoad({ state: "ready", report: await api.report(sessionId, threshold) });
      } catch (failure) {
        const error = toApiError(failure);
        setLoad(error.code === "no_previous_import" ? { state: "first_import" } : { state: "failed", error });
      } finally {
        setBusy(false);
      }
    },
    [api, sessionId],
  );

  useEffect(() => {
    void fetchReport(rememberedThreshold());
  }, [fetchReport]);

  const apply = (ratio: string) => {
    remember(ratio);
    void fetchReport(ratio);
  };

  switch (load.state) {
    case "loading":
      return <p className="lede">{t("common.loading")}</p>;
    case "first_import":
      return <p className="lede">{t("report.empty", { supplier: supplierName })}</p>;
    case "failed":
      return <ErrorBanner error={load.error} />;
    case "ready":
      // The CSV follows the threshold of the report on screen.
      return (
        <PriceReportView
          report={load.report}
          csvUrl={api.reportUrl(sessionId, load.report.threshold)}
          busy={busy}
          onThreshold={apply}
        />
      );
  }
}
