import type { Metadata } from "next";
import Script from "next/script";
import { Toaster } from "sonner";

import { AppShell } from "@/components/app-shell";
import { SiteSettingsProvider } from "@/components/site-settings-provider";

import "./globals.css";

export const metadata: Metadata = {
  title: "Image Studio",
  description: "AI image creation and management",
  icons: {
    icon: "/favicon.ico",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body
        className="antialiased"
        style={{
          fontFamily:
            '"SF Pro Display","SF Pro Text","PingFang SC","Microsoft YaHei","Helvetica Neue",sans-serif',
        }}
      >
        <Script id="site-settings-bootstrap" strategy="beforeInteractive">
          {`
            try {
              var raw = localStorage.getItem("yanai_site_settings");
              if (raw) {
                var settings = JSON.parse(raw);
                if (settings.site_title) document.title = settings.site_title;
                if (settings.site_icon) {
                  document.querySelectorAll("link[rel='icon'], link[rel='shortcut icon'], link[rel='apple-touch-icon']").forEach(function(item) {
                    item.remove();
                  });
                  var icon = document.createElement("link");
                  icon.rel = "icon";
                  if (String(settings.site_icon).toLowerCase().split("?", 1)[0].endsWith(".png")) {
                    icon.type = "image/png";
                  }
                  icon.href = settings.site_icon;
                  document.head.appendChild(icon);
                }
                if (settings.site_background) {
                  document.documentElement.style.setProperty("--yan-site-background-image", "url('" + settings.site_background + "')");
                  document.documentElement.classList.add("has-site-background");
                }
              }
            } catch (error) {}
          `}
        </Script>
        <SiteSettingsProvider />
        <Toaster position="top-center" richColors offset={48} />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
