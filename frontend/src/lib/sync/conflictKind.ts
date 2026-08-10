/** FR-073a conflict kind helpers. */

/** Server DB kinds + push ACK status strings both appear in CachedConflict.conflict_kind. */
export function conflictNeedsModal(kind: string): boolean {
  return (
    kind === "conflict_tie" ||
    kind === "tie_revision" ||
    kind === "session_immutable_after_evaluate" ||
    kind === "session_date_immutable"
  );
}

export function conflictIsLost(kind: string): boolean {
  return kind === "conflict_lost" || kind === "lost_push";
}

export function conflictKindI18nKey(kind: string): string {
  switch (kind) {
    case "conflict_lost":
    case "lost_push":
      return "sync.conflictKindLost";
    case "conflict_tie":
    case "tie_revision":
      return "sync.conflictKindTie";
    case "session_immutable_after_evaluate":
      return "sync.conflictKindImmutable";
    case "session_date_immutable":
      return "sync.conflictKindDateImmutable";
    case "satellite_config_activation_lost":
      return "sync.conflictKindSatelliteConfig";
    default:
      return "sync.conflictKindUnknown";
  }
}

export type LosingPayloadDoc = {
  schema_version?: number;
  payload?: Record<string, unknown> | null;
  op?: "upsert" | "delete";
  revision?: number;
};

export function parseLosingPayload(raw: unknown): LosingPayloadDoc | null {
  if (!raw || typeof raw !== "object") return null;
  const doc = raw as LosingPayloadDoc;
  return doc;
}
