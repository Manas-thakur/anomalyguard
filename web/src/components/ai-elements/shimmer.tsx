// Text shimmer for in-progress states (AI Elements pattern, CSS-only so it adds
// no animation dependency and stops under prefers-reduced-motion).

import type { ElementType } from "react";

import { cn } from "@/lib/utils";

export type ShimmerProps = {
  children: string;
  as?: ElementType;
  className?: string;
};

export const Shimmer = ({ children, as: Component = "span", className }: ShimmerProps) => (
  <Component
    className={cn(
      "animate-shimmer inline-block bg-[length:250%_100%] bg-clip-text text-transparent motion-reduce:animate-none motion-reduce:text-muted-foreground",
      "bg-[linear-gradient(90deg,var(--muted-foreground)_0%,var(--muted-foreground)_40%,var(--foreground)_50%,var(--muted-foreground)_60%,var(--muted-foreground)_100%)]",
      className,
    )}
  >
    {children}
  </Component>
);
