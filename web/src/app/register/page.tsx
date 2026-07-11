"use client";

import { LoaderCircle } from "lucide-react";

import { LoginForm } from "@/app/login/login-form";
import { useRedirectIfAuthenticated } from "@/lib/use-auth-guard";

export default function RegisterPage() {
  const { isCheckingAuth } = useRedirectIfAuthenticated();

  if (isCheckingAuth) {
    return (
      <div className="grid min-h-[calc(100vh-1rem)] w-full place-items-center px-4 py-6">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <LoginForm initialView="register" />;
}
