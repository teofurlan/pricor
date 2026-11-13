import type { Suggestion } from "../../api/types";
import { useI18n } from "../../i18n";
import { confidenceLevel } from "../../lib/confidence";
import { Badge } from "../atoms/Badge";

/** A model hypothesis, labeled with its source and whether its confidence is calibrated. */
export function SuggestionBadge({ suggestion }: { suggestion: Suggestion }) {
  const { t } = useI18n();
  // The API labels every advisor suggestion "model"; Gemma is the only advisor wired today.
  if (suggestion.suggested_by === "setting") {
    return <Badge tone="user">{t("suggestion.setting")}</Badge>;
  }
  if (suggestion.suggested_by === "detected") {
    return <Badge tone="user">{t("suggestion.detected")}</Badge>;
  }
  const level = t(`confidence.${confidenceLevel(suggestion.confidence)}`);
  const confidence = `${Math.round(suggestion.confidence * 100)}%`;
  const explanation = t(suggestion.calibrated ? "suggestion.calibrated" : "suggestion.uncalibrated", { level, confidence });
  return (
    <Badge tone="gemma">
      <abbr title={explanation}>{t("format.confidence", { level })}</abbr>
    </Badge>
  );
}
