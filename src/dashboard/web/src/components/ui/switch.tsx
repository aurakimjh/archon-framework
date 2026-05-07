import { forwardRef, type InputHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export interface SwitchProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "size"> {
  size?: "sm" | "md";
}

export const Switch = forwardRef<HTMLInputElement, SwitchProps>(
  ({ className, size = "md", checked, disabled, ...props }, ref) => {
    const dims =
      size === "sm"
        ? "h-4 w-7 after:h-3 after:w-3 after:translate-x-0.5 peer-checked:after:translate-x-3"
        : "h-5 w-9 after:h-4 after:w-4 after:translate-x-0.5 peer-checked:after:translate-x-4";

    return (
      <label
        className={cn(
          "relative inline-flex cursor-pointer items-center",
          disabled && "cursor-not-allowed opacity-50",
          className,
        )}
      >
        <input
          ref={ref}
          type="checkbox"
          role="switch"
          aria-checked={!!checked}
          checked={checked}
          disabled={disabled}
          className="peer sr-only"
          {...props}
        />
        <span
          className={cn(
            "rounded-full bg-secondary ring-1 ring-inset ring-border transition-colors",
            "peer-checked:bg-primary peer-focus-visible:ring-2 peer-focus-visible:ring-ring peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-background",
            "after:absolute after:top-1/2 after:-translate-y-1/2 after:rounded-full after:bg-primary-foreground after:shadow-sm after:transition-transform",
            dims,
          )}
        />
      </label>
    );
  },
);
Switch.displayName = "Switch";
