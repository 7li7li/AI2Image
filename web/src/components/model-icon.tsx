import { cn } from "@/lib/utils";

const MODEL_ICON_SOURCES = {
  claude: "/model-icons/claude.svg",
  gemini: "/model-icons/gemini.svg",
  grok: "/model-icons/grok.svg",
  openai: "/model-icons/openai.svg",
} as const;

type ModelIconKey = keyof typeof MODEL_ICON_SOURCES;

type ModelIconProps = {
  className?: string;
  model?: string | null;
  title?: string;
};

export function getModelIconKey(model?: string | null): ModelIconKey {
  const normalized = String(model || "").trim().toLowerCase();
  if (/(claude|anthropic)/.test(normalized)) {
    return "claude";
  }
  if (/(gemini|google)/.test(normalized)) {
    return "gemini";
  }
  if (/(grok|xai|x-ai)/.test(normalized)) {
    return "grok";
  }
  return "openai";
}

export function ModelIcon({ className, model, title }: ModelIconProps) {
  const iconKey = getModelIconKey(model);
  const label = title || `${model || iconKey} icon`;

  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={cn("inline-block shrink-0 bg-contain bg-center bg-no-repeat", className)}
      style={{ backgroundImage: `url("${MODEL_ICON_SOURCES[iconKey]}")` }}
    />
  );
}
