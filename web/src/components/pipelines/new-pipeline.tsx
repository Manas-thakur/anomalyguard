// "New pipeline" sheet: a template, a name and the template's fields
// (react-hook-form + zod through the shadcn Form components).

import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useNavigate } from "react-router";
import { toast } from "sonner";
import { z } from "zod";

import { ErrorState, InlineError, LoadingRows } from "@/components/common";
import { FilterSelect } from "@/components/filters";
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { api } from "@/lib/api";
import { fmtInt } from "@/lib/format";
import { refreshAll, useDatasets, useTemplates } from "@/lib/queries";
import type { Pipeline } from "@/lib/types";

const schema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Give the pipeline a name.")
    .regex(/^[A-Za-z0-9][A-Za-z0-9_.-]*$/, "Letters, digits, dot, dash or underscore; start with a letter or digit."),
  template: z.string(),
  dataset: z.string(),
  source: z.string(),
  group_by: z.string(),
  value_column: z.string(),
  table: z.string(),
  cursor: z.string(),
});
type Values = z.infer<typeof schema>;

const LABELS: Record<string, string> = { group_by: "Group by (optional)", value_column: "Value column", table: "Table", cursor: "Cursor column" };

export function NewPipelineSheet({ open, onOpenChange, writeDir }: { open: boolean; onOpenChange: (o: boolean) => void; writeDir?: string }) {
  const navigate = useNavigate();
  const templates = useTemplates();
  const datasets = useDatasets();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", template: "csv_quality", dataset: "", source: "", group_by: "", value_column: "", table: "", cursor: "" },
  });
  const template = useWatch({ control: form.control, name: "template" });
  const dataset = useWatch({ control: form.control, name: "dataset" });
  const t = templates.data?.find((x) => x.name === template);

  useEffect(() => {
    if (open && datasets.data?.length && !form.getValues("dataset") && !form.getValues("source")) form.setValue("dataset", datasets.data[0].id);
  }, [open, datasets.data, form]);

  async function submit(v: Values) {
    const source = template === "database_quality" ? v.source : v.dataset ? `dataset:${v.dataset}` : v.source;
    try {
      const p = await api.post<Pipeline>("/api/pipelines", {
        name: v.name,
        template: v.template,
        source: source || undefined,
        group_by: v.group_by || undefined,
        value_column: v.value_column || undefined,
        table: v.table || undefined,
        cursor: v.cursor || undefined,
      });
      toast.success(`Created ${p.file}`);
      refreshAll();
      onOpenChange(false);
      form.reset();
      navigate(`/pipelines/${p.id}`);
    } catch (err) {
      form.setError("root", { message: (err as Error).message });
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full gap-0 sm:max-w-md">
        <SheetHeader className="border-b">
          <SheetTitle>New pipeline</SheetTitle>
          <SheetDescription>{writeDir ? `Written to ${writeDir}/<name>.yaml` : "Created from a built-in template; edit the YAML afterwards."}</SheetDescription>
        </SheetHeader>
        {templates.error ? (
          <ErrorState error={templates.error} retry={() => templates.refetch()} />
        ) : !templates.data || !datasets.data ? (
          <LoadingRows rows={6} />
        ) : (
          <Form {...form}>
            <form onSubmit={form.handleSubmit(submit)} className="flex min-h-0 flex-1 flex-col">
              <div className="flex-1 space-y-5 overflow-y-auto p-4">
                <FormField
                  control={form.control}
                  name="name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Name</FormLabel>
                      <FormControl>
                        <Input placeholder="orders_daily" autoFocus autoComplete="off" {...field} />
                      </FormControl>
                      <FormDescription>Also the run and metrics key.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="template"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Template</FormLabel>
                      <FilterSelect label="Template" size="default" className="w-full" value={field.value} onChange={field.onChange} options={templates.data!.map((x) => ({ value: x.name, label: x.name.replace(/_/g, " ") }))} />
                      <FormDescription>{t?.description}</FormDescription>
                    </FormItem>
                  )}
                />
                {t?.fields.map((f) =>
                  f === "source" ? (
                    <div key={f} className="space-y-3">
                      {template !== "database_quality" ? (
                        <FormField
                          control={form.control}
                          name="dataset"
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>Source</FormLabel>
                              <FilterSelect
                                label="Uploaded dataset"
                                size="default"
                                className="w-full"
                                allLabel="Type a path instead"
                                value={field.value}
                                onChange={field.onChange}
                                options={datasets.data!.map((d) => ({ value: d.id, label: `${d.name} (uploaded, ${fmtInt(d.rows)} rows)` }))}
                              />
                            </FormItem>
                          )}
                        />
                      ) : null}
                      {template === "database_quality" || !dataset ? (
                        <FormField
                          control={form.control}
                          name="source"
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>{template === "database_quality" ? "Database" : "Path"}</FormLabel>
                              <FormControl>
                                <Input className="font-mono" placeholder={t.defaults.source || "data.csv"} {...field} />
                              </FormControl>
                              <FormDescription>{template === "database_quality" ? "SQLite file path or a SQLAlchemy URL." : "Relative to the pipeline file, or absolute."}</FormDescription>
                            </FormItem>
                          )}
                        />
                      ) : null}
                    </div>
                  ) : (
                    <FormField
                      key={f}
                      control={form.control}
                      name={f as keyof Values}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>{LABELS[f] ?? f}</FormLabel>
                          <FormControl>
                            <Input className="font-mono" placeholder={t.defaults[f] || ""} {...field} />
                          </FormControl>
                        </FormItem>
                      )}
                    />
                  ),
                )}
                {form.formState.errors.root ? <InlineError>{form.formState.errors.root.message}</InlineError> : null}
              </div>
              <SheetFooter className="border-t sm:flex-row sm:justify-end">
                <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={form.formState.isSubmitting}>
                  {form.formState.isSubmitting ? <Spinner /> : null} Create pipeline
                </Button>
              </SheetFooter>
            </form>
          </Form>
        )}
      </SheetContent>
    </Sheet>
  );
}
