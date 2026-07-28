import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Button, Modal } from "@/components/ui";
import type { ProgressionEvent } from "@/lib/schemas";
import { useSeenEventsStore } from "@/stores/seenEventsStore";

export function ProgressionSurface({
  events,
  names,
}: {
  events: ProgressionEvent[];
  names: Record<string, string>;
}) {
  const { t } = useTranslation();
  const filterUnseen = useSeenEventsStore((s) => s.filterUnseen);
  const markSeen = useSeenEventsStore((s) => s.markSeen);
  const queue = useMemo(() => filterUnseen(events), [events, filterUnseen]);
  const current = queue[0];

  if (!current) return null;

  const isAdvance = current.event_type === "advance";
  const name = names[current.exercise_id] ?? t("progress.unknownExercise");

  return (
    <Modal
      open
      title={isAdvance ? t("progress.advanceTitle") : t("progress.regressTitle")}
      onClose={() => markSeen(current.id)}
      actions={
        <Button onClick={() => markSeen(current.id)}>{t("progress.ack")}</Button>
      }
    >
      <p>
        {t(isAdvance ? "progress.advanceBody" : "progress.regressBody", {
          name,
          from: current.from_step,
          to: current.to_step,
        })}
      </p>
    </Modal>
  );
}
