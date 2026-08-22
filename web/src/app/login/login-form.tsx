"use client";

import { CheckCircle2, KeyRound, LoaderCircle, LogIn, Send, Sparkles, UserPlus } from "lucide-react";
import { type CSSProperties, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  confirmPasswordReset,
  fetchPublicAuthSettings,
  login,
  registerUser,
  requestPasswordReset,
  resendEmailVerification,
  verifyEmail,
  type LoginResponse,
  type PublicAuthSettings,
} from "@/lib/api";
import { useSiteSettingsStore } from "@/lib/site-settings";
import { cn } from "@/lib/utils";
import { getDefaultRouteForRole, setStoredAuthSession } from "@/store/auth";

type AuthView = "login" | "register" | "verify" | "forgot" | "admin";

const REGISTRATION_CODE_COOLDOWN_SECONDS = 60;

const DEFAULT_AUTH_SETTINGS: PublicAuthSettings = {
  allow_user_registration: false,
  email_verification_enabled: false,
  email_domain_whitelist_enabled: false,
  email_domain_whitelist: [],
};

function normalizeEmailDomainOptions(value: unknown): string[] {
  const items = Array.isArray(value) ? value : [];
  return Array.from(
    new Set(
      items
        .map((item) => String(item || "").trim().toLowerCase().replace(/^@/, ""))
        .filter((item) => item && !item.includes("@") && !item.startsWith("*.")),
    ),
  );
}

function emailLocalPart(value: string): string {
  return value.split("@", 1)[0].trim();
}

export function LoginForm({ initialView = "login" }: { initialView?: "login" | "register" }) {
  const [view, setView] = useState<AuthView>(initialView);
  const [email, setEmail] = useState("");
  const [registerEmailLocal, setRegisterEmailLocal] = useState("");
  const [registerEmailDomain, setRegisterEmailDomain] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [name, setName] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [authKey, setAuthKey] = useState("");
  const [resetCodeSent, setResetCodeSent] = useState(false);
  const [registrationCodeSent, setRegistrationCodeSent] = useState(false);
  const [registrationCodeCooldown, setRegistrationCodeCooldown] = useState(0);
  const [isSendingRegistrationCode, setIsSendingRegistrationCode] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [authSettings, setAuthSettings] = useState<PublicAuthSettings>(DEFAULT_AUTH_SETTINGS);
  const siteTitle = useSiteSettingsStore((state) => state.settings.site_title);
  const siteIcon = useSiteSettingsStore((state) => state.settings.site_icon);
  const siteBackground = useSiteSettingsStore((state) => state.settings.site_background);
  const [failedIconUrl, setFailedIconUrl] = useState("");
  const normalizedSiteIcon = siteIcon.trim();
  const normalizedSiteBackground = siteBackground.trim();
  const showSiteIcon = Boolean(normalizedSiteIcon && failedIconUrl !== normalizedSiteIcon);
  const emailDomainOptions = useMemo(
    () => normalizeEmailDomainOptions(authSettings.email_domain_whitelist),
    [authSettings.email_domain_whitelist],
  );
  const useRegisterDomainSelect = authSettings.email_domain_whitelist_enabled && emailDomainOptions.length > 0;
  const selectedRegisterEmailDomain =
    registerEmailDomain && emailDomainOptions.includes(registerEmailDomain) ? registerEmailDomain : emailDomainOptions[0] || "";
  const loginBackgroundStyle: CSSProperties | undefined = normalizedSiteBackground
    ? {
        backgroundImage: `linear-gradient(rgba(255, 255, 255, 0.64), rgba(248, 248, 249, 0.72)), url(${JSON.stringify(normalizedSiteBackground)})`,
        backgroundPosition: "center",
        backgroundSize: "cover",
      }
    : undefined;

  useEffect(() => {
    if (registrationCodeCooldown <= 0) {
      return;
    }
    const timer = window.setTimeout(() => {
      setRegistrationCodeCooldown((current) => Math.max(0, current - 1));
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [registrationCodeCooldown]);

  useEffect(() => {
    let cancelled = false;
    const loadAuthSettings = async () => {
      try {
        const data = await fetchPublicAuthSettings();
        if (!cancelled) {
          setAuthSettings(data.settings);
        }
      } catch {
        if (!cancelled) {
          setAuthSettings(DEFAULT_AUTH_SETTINGS);
        }
      }
    };
    void loadAuthSettings();
    return () => {
      cancelled = true;
    };
  }, []);

  const resolveRegistrationEmail = () => {
    if (!useRegisterDomainSelect) {
      return email.trim();
    }
    const local = emailLocalPart(registerEmailLocal);
    if (!local || !selectedRegisterEmailDomain) {
      return "";
    }
    return `${local}@${selectedRegisterEmailDomain}`;
  };

  const switchView = (nextView: AuthView) => {
    if (nextView === "register" && useRegisterDomainSelect && email.includes("@")) {
      const [local, domain] = email.trim().toLowerCase().split("@");
      if (local && domain && emailDomainOptions.includes(domain)) {
        setRegisterEmailLocal(local);
        setRegisterEmailDomain(domain);
      }
    }
    if (nextView !== "forgot") {
      setResetCodeSent(false);
    }
    if (nextView !== "verify") {
      setVerificationCode("");
    }
    if (nextView !== "register") {
      setRegistrationCodeSent(false);
      setRegistrationCodeCooldown(0);
    }
    setView(nextView);
  };

  const completeLogin = async (data: LoginResponse, fallbackKey = "") => {
    const sessionKey = fallbackKey || data.token || "";
    if (!sessionKey || !data.role || !data.subject_id) {
      throw new Error("登录未返回有效会话");
    }
    await setStoredAuthSession({
      key: sessionKey,
      role: data.role,
      subjectId: data.subject_id,
      name: data.name || data.email || "User",
      email: data.email,
      quota: data.quota,
    });
    window.location.replace(getDefaultRouteForRole(data.role));
  };

  const handleLogin = async () => {
    if (!email.trim() || !password) {
      toast.error("请输入邮箱和密码");
      return;
    }
    setIsSubmitting(true);
    try {
      const data = await login({ email: email.trim(), password });
      await completeLogin(data);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "登录失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAdminLogin = async () => {
    if (!authKey.trim()) {
      toast.error("请输入管理员密钥");
      return;
    }
    setIsSubmitting(true);
    try {
      const data = await login(authKey.trim());
      await completeLogin(data, authKey.trim());
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "登录失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const validateRegistrationFields = () => {
    const registrationEmail = resolveRegistrationEmail();
    if (!registrationEmail) {
      toast.error("请输入邮箱");
      return "";
    }
    if (!password || password.length < 6) {
      toast.error("密码至少 6 位");
      return "";
    }
    if (password !== confirmPassword) {
      toast.error("两次输入的密码不一致");
      return "";
    }
    return registrationEmail;
  };

  const handleSendRegistrationCode = async () => {
    if (isSubmitting || registrationCodeCooldown > 0) {
      return;
    }
    const registrationEmail = validateRegistrationFields();
    if (!registrationEmail) {
      return;
    }
    setIsSubmitting(true);
    setIsSendingRegistrationCode(true);
    const isResend = registrationCodeSent;
    let sentAsResend = isResend;
    try {
      let data: LoginResponse;
      if (isResend) {
        data = await resendEmailVerification({ email: registrationEmail, password });
      } else {
        try {
          data = await registerUser({ email: registrationEmail, password, name: name.trim() });
        } catch (error) {
          // A pending registration may already exist after a page reload; issue a fresh code for it.
          if (!(error instanceof Error) || !error.message.toLowerCase().includes("email already exists")) {
            throw error;
          }
          data = await resendEmailVerification({ email: registrationEmail, password });
          sentAsResend = true;
        }
      }
      if (!data.verification_required) {
        await completeLogin(data);
        return;
      }
      setEmail(registrationEmail);
      setRegistrationCodeSent(true);
      setVerificationCode("");
      setRegistrationCodeCooldown(REGISTRATION_CODE_COOLDOWN_SECONDS);
      toast.success(sentAsResend ? "验证码已重新发送" : "验证码已发送");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "发送验证码失败");
    } finally {
      setIsSubmitting(false);
      setIsSendingRegistrationCode(false);
    }
  };

  const handleRegister = async () => {
    const registrationEmail = validateRegistrationFields();
    if (!registrationEmail) {
      return;
    }
    if (authSettings.email_verification_enabled) {
      if (!registrationCodeSent) {
        toast.error("请先获取邮箱验证码");
        return;
      }
      if (!verificationCode.trim()) {
        toast.error("请输入邮箱验证码");
        return;
      }
      setIsSubmitting(true);
      try {
        const data = await verifyEmail({ email: registrationEmail, code: verificationCode.trim() });
        await completeLogin(data);
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "邮箱验证失败");
      } finally {
        setIsSubmitting(false);
      }
      return;
    }
    setIsSubmitting(true);
    try {
      const data = await registerUser({ email: registrationEmail, password, name: name.trim() });
      await completeLogin(data);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "注册失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleVerifyEmail = async () => {
    if (!email.trim() || !verificationCode.trim()) {
      toast.error("请输入邮箱验证码");
      return;
    }
    setIsSubmitting(true);
    try {
      const data = await verifyEmail({ email: email.trim(), code: verificationCode.trim() });
      await completeLogin(data);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "邮箱验证失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleResendVerification = async () => {
    if (!email.trim() || !password) {
      toast.error("请输入邮箱和密码");
      return;
    }
    setIsSubmitting(true);
    try {
      await resendEmailVerification({ email: email.trim(), password });
      setVerificationCode("");
      toast.success("验证码已重新发送");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "发送验证码失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRequestPasswordReset = async () => {
    if (!email.trim()) {
      toast.error("请输入邮箱");
      return;
    }
    setIsSubmitting(true);
    try {
      await requestPasswordReset({ email: email.trim() });
      setResetCodeSent(true);
      setVerificationCode("");
      setPassword("");
      setConfirmPassword("");
      toast.success("如果邮箱存在，验证码将发送到该邮箱");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "发送验证码失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleConfirmPasswordReset = async () => {
    if (!email.trim() || !verificationCode.trim()) {
      toast.error("请输入邮箱验证码");
      return;
    }
    if (!password || password.length < 6) {
      toast.error("密码至少 6 位");
      return;
    }
    if (password !== confirmPassword) {
      toast.error("两次输入的密码不一致");
      return;
    }
    setIsSubmitting(true);
    try {
      await confirmPasswordReset({ email: email.trim(), code: verificationCode.trim(), password });
      toast.success("密码已重置，请重新登录");
      setPassword("");
      setConfirmPassword("");
      setVerificationCode("");
      setResetCodeSent(false);
      setView("login");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "重置密码失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const primaryAction = async () => {
    if (isSubmitting) {
      return;
    }
    if (view === "admin") {
      await handleAdminLogin();
      return;
    }
    if (view === "register") {
      await handleRegister();
      return;
    }
    if (view === "verify") {
      await handleVerifyEmail();
      return;
    }
    if (view === "forgot") {
      await (resetCodeSent ? handleConfirmPasswordReset() : handleRequestPasswordReset());
      return;
    }
    await handleLogin();
  };

  const registrationVerificationEnabled = view === "register" && authSettings.email_verification_enabled;
  const registrationFieldsLocked = registrationVerificationEnabled && (registrationCodeSent || isSendingRegistrationCode);

  const primaryLabel =
    view === "admin"
      ? "管理员登录"
      : view === "register"
        ? registrationVerificationEnabled && registrationCodeSent
          ? "完成注册"
          : "注册"
        : view === "verify"
          ? "验证并登录"
          : view === "forgot"
            ? resetCodeSent
              ? "重置密码"
              : "发送验证码"
            : "登录";
  const PrimaryIcon =
    view === "register"
      ? registrationVerificationEnabled && registrationCodeSent
        ? CheckCircle2
        : UserPlus
      : view === "verify" || (view === "forgot" && !resetCodeSent)
        ? Send
        : view === "admin"
          ? KeyRound
          : LogIn;
  const navButtonClass = "text-sm text-stone-600 underline-offset-4 hover:text-black hover:underline disabled:pointer-events-none disabled:opacity-50";

  return (
    <div
      className={cn("grid min-h-screen w-full place-items-center px-4 py-6", normalizedSiteBackground ? "bg-white" : "bg-[#f7f7f8]")}
      style={loginBackgroundStyle}
    >
      <Card className="w-full max-w-[430px] overflow-hidden rounded-md border-white/80 bg-white/95 shadow-[0_20px_70px_rgba(15,23,42,0.12)]">
        <CardContent className="space-y-6 p-6 sm:p-8">
          <div className="space-y-3 text-center">
            <div
              className={cn(
                "mx-auto inline-flex size-14 items-center justify-center overflow-hidden rounded-lg shadow-sm",
                showSiteIcon ? "border border-stone-200 bg-white p-2" : "bg-neutral-900 text-white",
              )}
            >
              {showSiteIcon ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={normalizedSiteIcon}
                  alt=""
                  className="size-full object-contain"
                  onLoad={() => setFailedIconUrl((current) => (current === normalizedSiteIcon ? "" : current))}
                  onError={() => setFailedIconUrl(normalizedSiteIcon)}
                />
              ) : (
                <Sparkles className="size-5" />
              )}
            </div>
            <h1 className="text-2xl font-semibold tracking-normal text-stone-950">{siteTitle}</h1>
          </div>

          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              void primaryAction();
            }}
          >
            {view === "admin" ? (
              <Input
                type="password"
                value={authKey}
                onChange={(event) => setAuthKey(event.target.value)}
                placeholder="管理员密钥"
                className="h-11 rounded-[3px] border-stone-300 bg-white px-3 focus-visible:ring-stone-300/70"
              />
            ) : (
              <>
                {view === "register" && useRegisterDomainSelect ? (
                  <div className="flex h-11 min-w-0 overflow-hidden rounded-[3px] border border-stone-300 bg-white transition-[color,box-shadow] focus-within:border-stone-500 focus-within:ring-[3px] focus-within:ring-stone-300/60">
                    <Input
                      type="text"
                      value={registerEmailLocal}
                      onChange={(event) => setRegisterEmailLocal(emailLocalPart(event.target.value))}
                      placeholder="邮箱"
                      disabled={registrationFieldsLocked}
                      className="h-full min-w-0 flex-1 rounded-none border-0 bg-transparent px-3 shadow-none focus-visible:border-transparent focus-visible:ring-0"
                    />
                    <Select value={selectedRegisterEmailDomain} onValueChange={setRegisterEmailDomain} disabled={registrationFieldsLocked}>
                      <SelectTrigger
                        disabled={registrationFieldsLocked}
                        className="h-full w-[142px] shrink-0 rounded-none border-y-0 border-r-0 border-l border-stone-300 bg-white px-3 shadow-none focus:ring-0 focus-visible:ring-0"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="max-h-72">
                        {emailDomainOptions.map((domain) => (
                          <SelectItem key={domain} value={domain}>
                            @{domain}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                ) : (
                  <Input
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="邮箱"
                    disabled={registrationFieldsLocked}
                    className="h-11 rounded-[3px] border-stone-300 bg-white px-3 focus-visible:ring-stone-300/70"
                  />
                )}

                {view === "register" ? (
                  <Input
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="昵称"
                    disabled={registrationFieldsLocked}
                    className="h-11 rounded-[3px] border-stone-300 bg-white px-3 focus-visible:ring-stone-300/70"
                  />
                ) : null}

                {registrationVerificationEnabled ? (
                  <div className="space-y-2">
                    <div className="flex min-w-0 gap-2">
                      <Input
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        maxLength={6}
                        value={verificationCode}
                        onChange={(event) => setVerificationCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
                        placeholder="邮箱验证码"
                        className="h-11 min-w-0 flex-1 rounded-[3px] border-stone-300 bg-white px-3 tracking-[0.24em] focus-visible:ring-stone-300/70"
                      />
                      <Button
                        type="button"
                        variant="outline"
                        className="h-11 w-[126px] rounded-[3px] border-stone-300 px-2 text-sm text-stone-800 shadow-none hover:bg-stone-50"
                        onClick={() => void handleSendRegistrationCode()}
                        disabled={isSubmitting || registrationCodeCooldown > 0}
                      >
                        {isSendingRegistrationCode ? <LoaderCircle className="size-4 animate-spin" /> : <Send className="size-4" />}
                        {registrationCodeCooldown > 0
                          ? `${registrationCodeCooldown}s`
                          : registrationCodeSent
                            ? "重新发送"
                            : "获取验证码"}
                      </Button>
                    </div>
                    <p className="px-1 text-xs leading-5 text-stone-500">
                      {registrationCodeSent ? "验证码已发送，请查收邮箱" : "请先获取验证码，再完成注册"}
                    </p>
                  </div>
                ) : view === "verify" || (view === "forgot" && resetCodeSent) ? (
                  <Input
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    value={verificationCode}
                    onChange={(event) => setVerificationCode(event.target.value)}
                    placeholder="邮箱验证码"
                    className="h-11 rounded-[3px] border-stone-300 bg-white px-3 tracking-[0.24em] focus-visible:ring-stone-300/70"
                  />
                ) : null}

                {view !== "verify" && (view !== "forgot" || resetCodeSent) ? (
                  <Input
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder={view === "forgot" ? "新密码" : "密码"}
                    disabled={registrationFieldsLocked}
                    className="h-11 rounded-[3px] border-stone-300 bg-white px-3 focus-visible:ring-stone-300/70"
                  />
                ) : null}

                {view === "register" || (view === "forgot" && resetCodeSent) ? (
                  <Input
                    type="password"
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    placeholder="确认密码"
                    disabled={registrationFieldsLocked}
                    className="h-11 rounded-[3px] border-stone-300 bg-white px-3 focus-visible:ring-stone-300/70"
                  />
                ) : null}
              </>
            )}

            <Button
              type="submit"
              className="h-11 w-full rounded-md bg-neutral-900 text-base font-semibold text-white hover:bg-black"
              disabled={isSubmitting}
            >
              {isSubmitting ? <LoaderCircle className="size-4 animate-spin" /> : <PrimaryIcon className="size-4" />}
              {primaryLabel}
            </Button>
          </form>

          {view === "verify" ? (
            <div className="flex items-center justify-center gap-4 text-sm">
              <button
                type="button"
                className="font-medium text-stone-800 hover:text-black"
                onClick={() => void handleResendVerification()}
                disabled={isSubmitting}
              >
                重新发送验证码
              </button>
              <button type="button" className="text-stone-500 hover:text-stone-700" onClick={() => switchView("login")}>
                返回登录
              </button>
            </div>
          ) : null}
        </CardContent>

        <div className="flex min-h-12 items-center justify-between gap-4 border-t border-stone-200 bg-stone-50 px-6 py-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {view === "login" ? (
              <>
                {authSettings.allow_user_registration ? (
                  <button type="button" className={navButtonClass} onClick={() => switchView("register")} disabled={isSubmitting}>
                    注册
                  </button>
                ) : null}
                <button type="button" className={navButtonClass} onClick={() => switchView("forgot")} disabled={isSubmitting}>
                  忘记密码
                </button>
              </>
            ) : view === "register" ? (
              <>
                <button type="button" className={navButtonClass} onClick={() => switchView("login")} disabled={isSubmitting}>
                  登录
                </button>
                <button type="button" className={navButtonClass} onClick={() => switchView("forgot")} disabled={isSubmitting}>
                  忘记密码
                </button>
              </>
            ) : view === "forgot" ? (
              <>
                <button type="button" className={navButtonClass} onClick={() => switchView("login")} disabled={isSubmitting}>
                  登录
                </button>
                {authSettings.allow_user_registration ? (
                  <button type="button" className={navButtonClass} onClick={() => switchView("register")} disabled={isSubmitting}>
                    注册
                  </button>
                ) : null}
              </>
            ) : view === "admin" ? (
              <>
                <button type="button" className={navButtonClass} onClick={() => switchView("login")} disabled={isSubmitting}>
                  用户登录
                </button>
                {authSettings.allow_user_registration ? (
                  <button type="button" className={navButtonClass} onClick={() => switchView("register")} disabled={isSubmitting}>
                    注册
                  </button>
                ) : null}
                <button type="button" className={navButtonClass} onClick={() => switchView("forgot")} disabled={isSubmitting}>
                  忘记密码
                </button>
              </>
            ) : (
              <>
                <button type="button" className={navButtonClass} onClick={() => switchView("login")} disabled={isSubmitting}>
                  登录
                </button>
                <button type="button" className={navButtonClass} onClick={() => switchView("forgot")} disabled={isSubmitting}>
                  忘记密码
                </button>
              </>
            )}
          </div>
          {view !== "admin" ? (
            <button
              type="button"
              className={`${navButtonClass} shrink-0`}
              onClick={() => switchView("admin")}
              disabled={isSubmitting}
            >
              管理员登录
            </button>
          ) : null}
        </div>
      </Card>
    </div>
  );
}
