import type { Suggestion } from "../../api/types";
import { useI18n } from "../../i18n";
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
  const who = ["gemma", "model"].includes(suggestion.suggested_by) ? "Gemma" : suggestion.suggested_by;
  const confidence = String(Number(suggestion.confidence.toFixed(2))).replace(/^0\./, ".");
  const explanation = t(suggestion.calibrated ? "suggestion.calibrated" : "suggestion.uncalibrated", { who, confidence: Number(suggestion.confidence.toFixed(2)) });
  return (
    <Badge tone="gemma">
      <abbr title={explanation}>{who.toUpperCase()} {suggestion.calibrated ? "" : "~"}{confidence}</abbr>
    </Badge>
  );
}
