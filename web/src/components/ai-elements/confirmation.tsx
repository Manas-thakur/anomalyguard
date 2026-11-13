// Confirmation (AI Elements pattern): an inline request to approve an action,
// showing what will happen before it does, and the outcome after.

import { createContext, useContext, type ComponentProps, type ReactNode } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type ConfirmationState = "requested" | "accepted" | "rejected";

const ConfirmationContext = createContext<ConfirmationState>("requested");

export type ConfirmationProps = ComponentProps<typeof Alert> & { state: ConfirmationState };

export const Confirmation = ({ className, state, ...props }: ConfirmationProps) => (
  <ConfirmationContext.Provider value={state}>
    <Alert
      data-state={state}
      className={cn("flex flex-col gap-2 data-[state=accepted]:border-ok/30 data-[state=requested]:border-primary/30 data-[state=requested]:bg-accent/40", className)}
      {...props}
    />
  </ConfirmationContext.Provider>
);

export const ConfirmationTitle = ({ className, ...props }: ComponentProps<typeof AlertTitle>) => <AlertTitle className={cn("line-clamp-none", className)} {...props} />;

export const ConfirmationBody = ({ className, ...props }: ComponentProps<typeof AlertDescription>) => <AlertDescription className={cn("text-sm", className)} {...props} />;

export const ConfirmationRequest = ({ children }: { children?: ReactNode }) => (useContext(ConfirmationContext) === "requested" ? children : null);
export const ConfirmationAccepted = ({ children }: { children?: ReactNode }) => (useContext(ConfirmationContext) === "accepted" ? children : null);
export const ConfirmationRejected = ({ children }: { children?: ReactNode }) => (useContext(ConfirmationContext) === "rejected" ? children : null);

export const ConfirmationActions = ({ className, ...props }: ComponentProps<"div">) =>
  useContext(ConfirmationContext) === "requested" ? <div className={cn("flex flex-wrap items-center justify-end gap-2", className)} {...props} /> : null;

export const ConfirmationAction = (props: ComponentProps<typeof Button>) => <Button size="sm" type="button" {...props} />;
