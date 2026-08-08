import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "outline";
type Size = "xs" | "sm" | "md";

const variantClasses: Record<Variant, string> = {
  primary:
    "bg-accent-grad text-white hover:brightness-110 shadow-sm transition-all",
  secondary: "bg-hover text-fg hover:bg-line-strong/60",
  ghost: "text-fg-muted hover:bg-hover hover:text-fg",
  danger: "bg-danger-soft text-danger hover:bg-danger/20",
  outline:
    "border border-line bg-bg-elev text-fg hover:border-line-strong hover:bg-hover",
};

const sizeClasses: Record<Size, string> = {
  xs: "h-7 px-2 text-xs rounded-md gap-1",
  sm: "h-8 px-3 text-[13px] rounded-lg gap-1.5",
  md: "h-9 px-4 text-sm rounded-lg gap-2",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    { variant = "secondary", size = "sm", loading, className = "", children, disabled, ...rest },
    ref,
  ) {
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={`inline-flex items-center justify-center font-medium transition-colors select-none disabled:opacity-50 disabled:cursor-not-allowed ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
        {...rest}
      >
        {loading && <Loader2 size={13} className="animate-spin-slow" />}
        {children}
      </button>
    );
  },
);

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  active?: boolean;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  function IconButton({ label, active, className = "", children, ...rest }, ref) {
    return (
      <button
        ref={ref}
        title={label}
        aria-label={label}
        className={`inline-flex h-8 w-8 items-center justify-center rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
          active
            ? "bg-accent-soft text-accent"
            : "text-fg-muted hover:bg-hover hover:text-fg"
        } ${className}`}
        {...rest}
      >
        {children}
      </button>
    );
  },
);
