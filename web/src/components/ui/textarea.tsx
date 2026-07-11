import * as React from "react";

import { cn } from "@/lib/utils";

const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<"textarea">>(function Textarea(
  { className, ...props },
  ref,
) {
  return (
    <textarea
      ref={ref}
      data-slot="textarea"
      className={cn(
        "border-input placeholder:text-muted-foreground flex min-h-32 w-full rounded-lg border bg-white/78 px-4 py-3 text-sm shadow-sm outline-none focus-visible:border-stone-200 focus-visible:ring-[3px] focus-visible:ring-stone-100/80 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
});

Textarea.displayName = "Textarea";

export { Textarea };
