"use client";

import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { LoginForm } from "@/app/login/login-form";
import { getDefaultRouteForRole, getStoredAuthSession } from "@/store/auth";

export default function HomePage() {
  const [isCheckingAuth, setIsCheckingAuth] = useState(true);

  useEffect(() => {
    let active = true;

    const redirect = async () => {
      let session: Awaited<ReturnType<typeof getStoredAuthSession>> = null;
      try {
        session = await getStoredAuthSession();
      } catch {
        session = null;
      }

      if (!active) {
        return;
      }
      if (session) {
        window.location.replace(getDefaultRouteForRole(session.role));
        return;
      }
      setIsCheckingAuth(false);
    };

    void redirect();
    return () => {
      active = false;
    };
  }, []);

  if (isCheckingAuth) {
    return (
      <div className="grid min-h-[calc(100vh-1rem)] w-full place-items-center px-4 py-6">
        <LoaderCircle className="size-5 animate-spin text-rose-400" />
      </div>
    );
  }

  return <LoginForm />;
}
