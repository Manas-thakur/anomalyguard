// Asks for the server's API key the first time a request gets a 401.

import { KeyRoundIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api } from "@/lib/api";

export function ApiKeyDialog() {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [error, setError] = useState(false);
  const [checking, setChecking] = useState(false);
  const resolver = useRef<((key: string | null) => void) | null>(null);

  useEffect(() => {
    api.onKeyRequired(
      () =>
        new Promise<string | null>((resolve) => {
          resolver.current = resolve;
          setValue("");
          setError(false);
          setOpen(true);
        }),
    );
    return () => api.onKeyRequired(null);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const key = value.trim();
    if (!key) return;
    setChecking(true);
    const ok = await api.checkKey(key);
    setChecking(false);
    if (!ok) {
      setError(true);
      return;
    }
    setOpen(false);
    resolver.current?.(key);
    resolver.current = null;
  }

  return (
    <Dialog open={open} onOpenChange={() => { /* the key is required to continue */ }}>
      <DialogContent showCloseButton={false} onEscapeKeyDown={(e) => e.preventDefault()} onInteractOutside={(e) => e.preventDefault()}>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <div className="bg-accent text-accent-foreground mb-1 flex size-9 items-center justify-center rounded-lg">
              <KeyRoundIcon className="size-4" aria-hidden />
            </div>
            <DialogTitle>API key required</DialogTitle>
            <DialogDescription>
              This server has <code className="font-mono text-xs">ANOMALYGUARD_API_KEY</code> set. Enter the key once; it is kept in this browser and sent as the{" "}
              <code className="font-mono text-xs">X-API-Key</code> header.
            </DialogDescription>
          </DialogHeader>
          <Field data-invalid={error || undefined}>
            <FieldLabel htmlFor="api-key">API key</FieldLabel>
            <Input id="api-key" type="password" autoComplete="off" autoFocus value={value} onChange={(e) => { setValue(e.target.value); setError(false); }} aria-invalid={error || undefined} required />
            {error ? <FieldError>That key was not accepted.</FieldError> : <FieldDescription>Forget it later in Settings.</FieldDescription>}
          </Field>
          <DialogFooter>
            <Button type="submit" disabled={checking || !value.trim()}>
              {checking ? <Spinner /> : null} Continue
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
