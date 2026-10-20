import { useEffect, useState } from "react";

/**
 * Remembers which of a component's actions started the current wait, so only that key shows
 * the loader. The mark clears when the wait ends.
 */
export function usePendingAction<T extends string>(busy: boolean) {
  const [pending, setPending] = useState<T | null>(null);
  useEffect(() => {
    if (!busy) setPending(null);
  }, [busy]);
  return {
    isLoading: (action: T) => busy && pending === action,
    mark: (action: T) => setPending(action),
  };
}
