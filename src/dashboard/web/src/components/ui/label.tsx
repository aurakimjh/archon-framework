import { forwardRef, type LabelHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export const Label = forwardRef<
  HTMLLabelElement,
  LabelHTMLAttributes<HTMLLabelElement>
>(({ className, ...props }, ref) => (
  <label
    ref={ref}
    className={cn(
      "text-xs font-medium uppercase tracking-wider text-muted-foreground",
      className,
    )}
    {...props}
  />
));
Label.displayName = "Label";
