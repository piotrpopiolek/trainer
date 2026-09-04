import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import { useTranslation } from "react-i18next";

export function Button({
  className = "",
  variant = "primary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
}) {
  const styles: Record<string, string> = {
    primary:
      "bg-teal-700 text-white hover:bg-teal-800 disabled:bg-slate-300 disabled:text-slate-500",
    secondary:
      "bg-white text-slate-900 border border-slate-300 hover:bg-slate-50 disabled:opacity-50",
    ghost: "bg-transparent text-slate-700 hover:bg-slate-100 disabled:opacity-50",
    danger: "bg-rose-700 text-white hover:bg-rose-800 disabled:opacity-50",
  };
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center rounded-lg px-4 py-2.5 text-sm font-semibold transition ${styles[variant]} ${className}`}
      {...props}
    />
  );
}

export function Input({
  className = "",
  label,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label?: string }) {
  return (
    <label className="flex flex-col gap-1.5 text-sm text-slate-700">
      {label ? <span className="font-medium">{label}</span> : null}
      <input
        className={`rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-slate-900 outline-none ring-teal-700/30 focus:ring-2 ${className}`}
        {...props}
      />
    </label>
  );
}

export function Select({
  className = "",
  label,
  children,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement> & {
  label?: string;
  children: ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5 text-sm text-slate-700">
      {label ? <span className="font-medium">{label}</span> : null}
      <select
        className={`rounded-lg border border-slate-300 bg-white px-3 py-2.5 text-slate-900 outline-none ring-teal-700/30 focus:ring-2 ${className}`}
        {...props}
      >
        {children}
      </select>
    </label>
  );
}

export function Modal({
  open,
  title,
  children,
  onClose,
  actions,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
  actions?: ReactNode;
}) {
  const { t } = useTranslation();
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/50 p-4 sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      <div className="flex max-h-[min(100dvh-2rem,40rem)] w-full max-w-md flex-col rounded-2xl bg-white shadow-xl">
        <div className="flex shrink-0 items-start justify-between gap-3 px-5 pb-3 pt-5">
          <h2 id="modal-title" className="font-display text-xl font-semibold text-slate-900">
            {title}
          </h2>
          <button
            type="button"
            className="text-slate-500 hover:text-slate-800"
            onClick={onClose}
            aria-label={t("common.close")}
          >
            ×
          </button>
        </div>
        <div
          className={
            actions
              ? "min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 text-sm text-slate-700"
              : "min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 pb-5 text-sm text-slate-700"
          }
        >
          {children}
        </div>
        {actions ? (
          <div className="flex shrink-0 flex-wrap justify-end gap-2 border-t border-slate-100 px-5 pb-5 pt-4">
            {actions}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function Page({
  title,
  children,
  actions,
}: {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="mx-auto flex w-full max-w-lg flex-col gap-5 px-4 py-6">
      <header className="flex items-start justify-between gap-3">
        <h1 className="font-display text-2xl font-semibold tracking-tight text-slate-900">
          {title}
        </h1>
        {actions}
      </header>
      {children}
    </div>
  );
}
