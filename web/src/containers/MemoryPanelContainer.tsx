import { useEffect, useState } from "react";
import { ApiError, type MemoryApiClient } from "../api/client";
import type { Memory } from "../api/types";
import { MemoryPanel } from "../components/organisms/MemoryPanel";
import { SideDrawer } from "../components/organisms/SideDrawer";
import { useI18n } from "../i18n";

interface Props {
  api: MemoryApiClient;
  open: boolean;
  onClose(): void;
  onMemoriesChange?(memories: Memory[]): void;
}

export function MemoryPanelContainer({ api, open, onClose, onMemoriesChange }: Props) {
  const { t } = useI18n();
  const [memories, setMemories] = useState<Memory[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function publish(next: Memory[]) {
    setMemories(next);
    onMemoriesChange?.(next);
  }

  useEffect(() => {
    let active = true;
    api.listMemories()
      .then((items) => {
        if (active) publish(items);
      })
      .catch((failure: unknown) => {
        if (!active) return;
        setError(failure instanceof ApiError && failure.status === 503 ? t("memory.unavailable") : failure instanceof Error ? failure.message : String(failure));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
    // The API instance is stable for the app lifetime; memory is intentionally loaded once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  async function mutate(action: () => Promise<Memory[]>) {
    setBusy(true);
    setError(null);
    try {
      publish(await action());
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 503 ? t("memory.unavailable") : failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SideDrawer open={open} label={t("memory.title")} closeLabel={t("memory.close")} onClose={onClose} className="memory-drawer">
      <MemoryPanel
        memories={memories}
        loading={loading}
        busy={busy}
        error={error}
        onAdd={(text, supplierName) => void mutate(async () => [...memories, await api.createMemoryNote(text, supplierName)])}
        onEdit={(id, text) => void mutate(async () => {
          const updated = await api.editMemory(id, text);
          return memories.map((item) => item.id === id ? updated : item);
        })}
        onDelete={(id) => void mutate(async () => {
          await api.deleteMemory(id);
          return memories.filter((item) => item.id !== id);
        })}
      />
    </SideDrawer>
  );
}
