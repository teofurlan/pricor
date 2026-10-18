import type { Memory } from "../../api/types";
import { useI18n } from "../../i18n";

export function MemoryCitation({ memoryIds, memories }: { memoryIds?: string[]; memories: Memory[] }) {
  const { t } = useI18n();
  if (!memoryIds?.length) return null;
  const byId = new Map(memories.map((memory) => [memory.id, memory.text]));
  return (
    <aside className="memory-citation">
      <strong>{t("memory.citation")}</strong>
      <ul>
        {memoryIds.map((id) => <li key={id}>{byId.get(id) ?? t("memory.deleted")}</li>)}
      </ul>
    </aside>
  );
}
