import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type ApiClient } from "../api/client";
import type { PreviewPage } from "../api/types";

export const PREVIEW_PAGE_SIZE = 50;

export function toApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError(0, "unexpected_error", error instanceof Error ? error.message : String(error));
}

/**
 * Loads preview pages while `active`; forgets them when the user leaves the preview.
 * A new `revision` (anything that changes the plan's result) reloads the first page.
 */
export function usePreview(api: ApiClient, sessionId: string | null, active: boolean, revision = "") {
  const [page, setPage] = useState<PreviewPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const latest = useRef(0);

  const load = useCallback(
    async (offset: number) => {
      if (!sessionId) return;
      // Only the latest request may update the page: an older one may describe an older plan.
      const ticket = ++latest.current;
      setLoading(true);
      setError(null);
      try {
        const loaded = await api.preview(sessionId, offset, PREVIEW_PAGE_SIZE);
        if (ticket === latest.current) setPage(loaded);
      } catch (failure) {
        if (ticket === latest.current) setError(toApiError(failure));
      } finally {
        if (ticket === latest.current) setLoading(false);
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
  }, [active, load, revision]);

  return { page, loading, error, load };
}
