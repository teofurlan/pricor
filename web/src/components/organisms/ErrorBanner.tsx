import type { ApiError } from "../../api/client";
import { isTextKey, useI18n } from "../../i18n";
import { describeError } from "../../i18n/serverText";

/** A failed call, in words the user can act on; other codes are described by `describeError`. */
export function ErrorBanner({ error }: { error: ApiError | null }) {
  const { t, language } = useI18n();
  if (!error) return null;
  const key = `error.${error.code}`;
  return (
    <div role="alert" className="error">
      {isTextKey(key) ? t(key) : describeError(error, language)}
    </div>
  );
}
