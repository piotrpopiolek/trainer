import { applyPull, flushOutbox } from "@/features/sync/flush";
import { requestPersistentStorage } from "@/lib/db/persist";
import { resetInFlightToPending } from "@/lib/db/outbox";
import { useSyncStore } from "@/stores/syncStore";

export async function bootstrapSync(userId: string, locale?: string): Promise<void> {
  useSyncStore.getState().setUserId(userId);
  await resetInFlightToPending(userId);
  await requestPersistentStorage(userId);
  try {
    if (navigator.onLine) {
      await applyPull(userId, locale);
      const result = await flushOutbox(userId);
      if (result.transportFailures > 0) {
        useSyncStore.getState().bumpTransportFail();
      } else {
        useSyncStore.getState().resetTransportFail();
      }
      if (result.progressionEvents.length) {
        useSyncStore.getState().pushEvents(result.progressionEvents);
      }
      if (result.conflicts > 0) {
        await useSyncStore.getState().refresh();
        const first = useSyncStore.getState().conflicts.find((c) => !c.acknowledged);
        if (first) useSyncStore.getState().setLastConflictToast(first);
      }
    }
  } finally {
    await useSyncStore.getState().refresh();
  }
}

export async function syncNow(userId: string, locale?: string): Promise<void> {
  await requestPersistentStorage(userId);
  if (!navigator.onLine) {
    await useSyncStore.getState().refresh();
    return;
  }
  try {
    const result = await flushOutbox(userId);
    await applyPull(userId, locale);
    if (result.transportFailures > 0) useSyncStore.getState().bumpTransportFail();
    else useSyncStore.getState().resetTransportFail();
    if (result.progressionEvents.length) {
      useSyncStore.getState().pushEvents(result.progressionEvents);
    }
  } finally {
    await useSyncStore.getState().refresh();
  }
}
