import { useCallback, useEffect, useState } from "react";
import { ApiError, type ApiClient } from "../api/client";
import type { PreviewPage } from "../api/types";

export const PREVIEW_PAGE_SIZE = 50;

export function toApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError(0, "unexpected_error", error instanceof Error ? error.message : String(error));
}

/** Loads preview pages while `active`; forgets them when the user leaves the preview. */
export function usePreview(api: ApiClient, sessionId: string | null, active: boolean) {
  const [page, setPage] = useState<PreviewPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(
    async (offset: number) => {
      if (!sessionId) return;
      setLoading(true);
      setError(null);
      try {
        setPage(await api.preview(sessionId, offset, PREVIEW_PAGE_SIZE));
      } catch (failure) {
        setError(toApiError(failure));
      } finally {
        setLoading(false);
      }
    },
    [api, sessionId],
  );

  useEffect(() => {
    if (!active) {
      setPage(null);
      return;
    }
    void load(0);
  }, [active, load]);

  return { page, loading, error, load };
}
