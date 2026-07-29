import { openDB, type DBSchema, type IDBPDatabase } from "idb";

import type { CachedConflict, OutboxItem, SyncMeta } from "@/lib/db/types";

interface TrainerDb extends DBSchema {
  meta: {
    key: string;
    value: SyncMeta;
  };
  outbox: {
    key: string;
    value: OutboxItem;
    indexes: {
      by_status: string;
      by_created: string;
    };
  };
  sessions: {
    key: string;
    value: Record<string, unknown>;
  };
  measurements: {
    key: string;
    value: Record<string, unknown>;
  };
  satellites: {
    key: string;
    value: Record<string, unknown>;
  };
  progress: {
    key: string;
    value: Record<string, unknown>;
  };
  conflicts: {
    key: string;
    value: CachedConflict;
  };
  catalog: {
    key: string;
    value: Record<string, unknown>;
  };
}

const DB_VERSION = 1;

function dbName(userId: string): string {
  return `trainer.${userId}`;
}

const openCaches = new Map<string, Promise<IDBPDatabase<TrainerDb>>>();

export async function openUserDb(userId: string): Promise<IDBPDatabase<TrainerDb>> {
  let pending = openCaches.get(userId);
  if (!pending) {
    pending = openDB<TrainerDb>(dbName(userId), DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains("meta")) {
          db.createObjectStore("meta", { keyPath: "key" });
        }
        if (!db.objectStoreNames.contains("outbox")) {
          const outbox = db.createObjectStore("outbox", {
            keyPath: "client_mutation_id",
          });
          outbox.createIndex("by_status", "status");
          outbox.createIndex("by_created", "created_at");
        }
        if (!db.objectStoreNames.contains("sessions")) {
          db.createObjectStore("sessions", { keyPath: "id" });
        }
        if (!db.objectStoreNames.contains("measurements")) {
          db.createObjectStore("measurements", { keyPath: "id" });
        }
        if (!db.objectStoreNames.contains("satellites")) {
          db.createObjectStore("satellites", { keyPath: "id" });
        }
        if (!db.objectStoreNames.contains("progress")) {
          db.createObjectStore("progress", { keyPath: "exercise_id" });
        }
        if (!db.objectStoreNames.contains("conflicts")) {
          db.createObjectStore("conflicts", { keyPath: "id" });
        }
        if (!db.objectStoreNames.contains("catalog")) {
          db.createObjectStore("catalog", { keyPath: "key" });
        }
      },
    });
    openCaches.set(userId, pending);
  }
  return pending;
}

export async function clearUserDb(userId: string): Promise<void> {
  const existing = openCaches.get(userId);
  if (existing) {
    const db = await existing;
    db.close();
    openCaches.delete(userId);
  }
  await indexedDB.deleteDatabase(dbName(userId));
}

export type { IDBPDatabase, TrainerDb };
