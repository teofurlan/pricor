import type { ApiError } from "../../api/client";
import { isTextKey, useI18n } from "../../i18n";

/** A failed call, in words the user can act on; unknown codes show the server's own message. */
export function ErrorBanner({ error }: { error: ApiError | null }) {
  const { t } = useI18n();
  if (!error) return null;
  const key = `error.${error.code}`;
  return (
    <div role="alert" className="error">
      {isTextKey(key) ? t(key) : error.message}
    </div>
  );
}
