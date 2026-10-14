import { Badge, type BadgeTone } from "../atoms/Badge";
import { useI18n, type TextKey } from "../../i18n";

const KNOWN: Record<string, { tone: BadgeTone; key: TextKey }> = {
  heuristics: { tone: "heuristics", key: "provenance.heuristics" },
  gemma: { tone: "gemma", key: "provenance.gemma" },
  user: { tone: "user", key: "provenance.user" },
  saved_plan: { tone: "saved", key: "provenance.saved_plan" },
};

/** Who settled a column's role: a cascade stage, the user, or nobody yet. */
export function ProvenanceBadge({ decidedBy }: { decidedBy: string | null }) {
  const { t } = useI18n();
  if (decidedBy === null) return <Badge tone="pending">{t("provenance.undecided")}</Badge>;
  const known = KNOWN[decidedBy];
  if (!known) return <Badge>{decidedBy}</Badge>;
  return <Badge tone={known.tone}>{t(known.key)}</Badge>;
}
