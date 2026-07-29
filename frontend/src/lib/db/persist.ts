import { getPersistedFlag, setPersistedFlag } from "@/lib/db/meta";

/** FR-070a — best-effort persistent storage request. */
export async function requestPersistentStorage(userId: string): Promise<boolean> {
  let persisted = false;
  try {
    if (typeof navigator !== "undefined" && navigator.storage?.persist) {
      persisted = await navigator.storage.persist();
    }
  } catch {
    persisted = false;
  }
  await setPersistedFlag(userId, persisted);
  return persisted;
}

export async function readPersisted(userId: string): Promise<boolean | null> {
  return getPersistedFlag(userId);
}
