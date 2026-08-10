import { Component, type ErrorInfo, type ReactNode } from "react";
import { withTranslation, type WithTranslation } from "react-i18next";

import { Button } from "@/components/ui";

type Props = WithTranslation & { children: ReactNode };

type State = { hasError: boolean };

/** Prevents a render crash from becoming a blank white screen (dogfood hardening). */
class ErrorBoundaryInner extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("ui.render_crash", error, info.componentStack);
  }

  render() {
    const { t, children } = this.props;
    if (!this.state.hasError) return children;
    return (
      <div className="mx-auto flex min-h-screen w-full max-w-lg flex-col justify-center gap-4 px-4">
        <h1 className="font-display text-2xl font-semibold text-slate-900">
          {t("shell.crashTitle")}
        </h1>
        <p className="text-sm text-slate-600">{t("shell.crashBody")}</p>
        <Button
          onClick={() => {
            this.setState({ hasError: false });
            window.location.assign("/");
          }}
        >
          {t("shell.crashReload")}
        </Button>
      </div>
    );
  }
}

export const ErrorBoundary = withTranslation()(ErrorBoundaryInner);
