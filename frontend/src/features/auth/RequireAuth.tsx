import { useQuery } from "@tanstack/react-query";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { ApiError } from "@/lib/api";
import { fetchMe } from "@/features/auth/api";
import { useAuthStore } from "@/stores/authStore";

export function RequireAuth() {
  const location = useLocation();
  const setMe = useAuthStore((s) => s.setMe);
  const me = useAuthStore((s) => s.me);

  const q = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const data = await fetchMe();
      setMe(data);
      return data;
    },
    retry: false,
  });

  if (q.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-600">
        …
      </div>
    );
  }

  if (q.isError) {
    if (q.error instanceof ApiError && q.error.status === 401) {
      return <Navigate to="/login" replace state={{ from: location.pathname }} />;
    }
    return <Navigate to="/login" replace />;
  }

  const user = q.data ?? me;
  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (!user.onboarding_completed && !location.pathname.startsWith("/onboarding")) {
    return <Navigate to="/onboarding" replace />;
  }

  if (user.onboarding_completed && location.pathname.startsWith("/onboarding")) {
    return <Navigate to="/" replace />;
  }

  if (
    user.onboarding_completed &&
    !user.health_disclaimer_accepted &&
    !location.pathname.startsWith("/legal")
  ) {
    return <Navigate to="/legal" replace />;
  }

  if (user.health_disclaimer_accepted && location.pathname.startsWith("/legal")) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
