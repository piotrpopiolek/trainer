import { NavLink, Outlet } from "react-router-dom";
import { useTranslation } from "react-i18next";

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `flex-1 rounded-lg px-2 py-2 text-center text-xs font-semibold ${
    isActive ? "bg-teal-700 text-white" : "text-slate-600 hover:bg-slate-100"
  }`;

export function AppShell() {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-screen flex-col bg-[radial-gradient(ellipse_at_top,_#ecfdf5_0%,_#f8fafc_45%,_#f1f5f9_100%)]">
      <div className="flex-1 pb-20">
        <Outlet />
      </div>
      <nav className="fixed inset-x-0 bottom-0 border-t border-slate-200/80 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-lg gap-1 p-2">
          <NavLink to="/" end className={linkClass}>
            {t("nav.today")}
          </NavLink>
          <NavLink to="/progress" className={linkClass}>
            {t("nav.progress")}
          </NavLink>
          <NavLink to="/satellites" className={linkClass}>
            {t("nav.satellites")}
          </NavLink>
          <NavLink to="/measurements" className={linkClass}>
            {t("nav.measurements")}
          </NavLink>
          <NavLink to="/settings" className={linkClass}>
            {t("nav.settings")}
          </NavLink>
        </div>
      </nav>
    </div>
  );
}
