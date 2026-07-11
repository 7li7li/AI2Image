import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-stone-50 text-stone-700",
        secondary: "border-transparent bg-stone-50 text-stone-700",
        outline: "border-stone-100 bg-white/70 text-foreground",
        success:
          "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300",
        warning:
          "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300",
        danger:
          "border-stone-200 bg-stone-50 text-stone-700 dark:border-stone-800 dark:bg-stone-950/30 dark:text-stone-300",
        info: "border-stone-200 bg-stone-50 text-stone-700 dark:border-stone-800 dark:bg-stone-950/30 dark:text-stone-300",
        violet:
          "border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-800 dark:bg-violet-950/30 dark:text-violet-300",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
