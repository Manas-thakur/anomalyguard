import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Kbd, KbdGroup } from "@/components/ui/kbd";

import { MOD } from "./ui-context";

export const SHORTCUTS: [string, [string, string][]][] = [
  [
    "Anywhere",
    [
      [`${MOD} K`, "Open the command palette"],
      ["?", "Show keyboard shortcuts"],
      ["g h", "Go to Health"],
      ["g r", "Go to Runs"],
      ["g i", "Go to the review inbox"],
      ["g a", "Go to Analyze"],
      ["g p", "Go to Pipelines"],
      ["g s", "Go to Settings"],
      ["/", "Focus search on the page"],
      [`${MOD} B`, "Collapse or expand the sidebar"],
    ],
  ],
  [
    "Review inbox",
    [
      ["j k", "Next / previous item"],
      ["a", "Approve (selection, or the open item)"],
      ["r", "Reject: keep the original value"],
      ["m", "Mark as normal (false positive)"],
      ["e", "Edit the final value"],
      ["x", "Select or deselect the open item"],
      ["Shift click", "Select a range"],
      ["Esc", "Clear the selection or close the item"],
    ],
  ],
];

export function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>Single-key shortcuts work whenever focus is not in a text field.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-6 sm:grid-cols-2">
          {SHORTCUTS.map(([title, rows]) => (
            <section key={title}>
              <h3 className="text-muted-foreground mb-2 text-xs font-medium tracking-wide uppercase">{title}</h3>
              <dl className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 text-sm">
                {rows.map(([keys, what]) => (
                  <div key={keys} className="contents">
                    <dt>
                      <KbdGroup>
                        {keys.split(" ").map((k) => (
                          <Kbd key={k}>{k}</Kbd>
                        ))}
                      </KbdGroup>
                    </dt>
                    <dd className="text-muted-foreground">{what}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
