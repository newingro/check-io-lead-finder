import type { ButtonHTMLAttributes, ReactNode } from "react";

export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "danger" | "ghost";

export function buttonClass(variant: Variant = "primary", className?: string) {
  return cn(
    "inline-flex min-h-11 items-center justify-center gap-2 rounded-md px-4 text-sm font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-60",
    variant === "primary" && "bg-navy-900 text-white hover:bg-navy-700",
    variant === "secondary" && "border border-line bg-white text-navy-900 hover:border-navy-900/40",
    variant === "danger" && "border border-danger/30 bg-white text-danger hover:bg-danger-soft",
    variant === "ghost" && "text-navy-900 hover:bg-mist",
    className,
  );
}

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button className={buttonClass(variant, className)} {...props} />;
}

export function Notice({ tone, children }: { tone: "ok" | "error" | "info"; children: ReactNode }) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "rounded-md border px-4 py-3 text-sm",
        tone === "ok" && "border-turq-500/40 bg-ok-soft text-navy-900",
        tone === "error" && "border-danger/30 bg-danger-soft text-danger",
        tone === "info" && "border-line bg-white text-slate",
      )}
    >
      {children}
    </div>
  );
}

export function PageHeader({ title, description, children }: { title: string; description?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold text-navy-900 sm:text-3xl">{title}</h1>
        {description ? <p className="mt-2 max-w-2xl text-slate">{description}</p> : null}
      </div>
      {children}
    </div>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "ok" | "warn" | "off"; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold",
        tone === "neutral" && "bg-mist text-navy-900",
        tone === "ok" && "bg-turq-500/15 text-turq-700",
        tone === "warn" && "bg-amber-100 text-amber-800",
        tone === "off" && "bg-navy-900/10 text-slate",
      )}
    >
      {children}
    </span>
  );
}
