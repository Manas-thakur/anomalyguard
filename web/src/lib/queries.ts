// React Query hooks for every API resource the pages read.

import { keepPreviousData, QueryClient, useQuery } from "@tanstack/react-query";

import { api, type Params } from "./api";
import type {
  Analysis,
  AnalysisRows,
  Change,
  DatasetProfile,
  Dataset,
  Detector,
  HealthOverview,
  Incident,
  IncidentChart,
  Job,
  PipelineDetail,
  PipelineList,
  PipelineTemplate,
  ReviewDetail,
  ReviewFacets,
  ReviewItem,
  RunDetail,
  RunIncidents,
  RunRow,
  Finding,
  SeriesPoint,
  Settings,
  Summary,
} from "./types";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      refetchOnWindowFocus: true,
      retry: (count, err) => {
        const status = (err as { status?: number }).status;
        if (status && status >= 400 && status < 500) return false;
        return count < 2;
      },
    },
  },
});

/** Refetch everything that might show changed data (after a run, triage, ...). */
export const refreshAll = () => queryClient.invalidateQueries();

export const useSummary = () => useQuery({ queryKey: ["summary"], queryFn: () => api.get<Summary>("/api/summary"), refetchInterval: 30_000 });

export const useHealth = () => useQuery({ queryKey: ["health"], queryFn: () => api.get<HealthOverview>("/api/health/overview") });

export const useRecentIncidents = (limit = 12) =>
  useQuery({ queryKey: ["incidents", "recent", limit], queryFn: () => api.get<Incident[]>("/api/incidents", { limit }) });

export const useSeries = () =>
  useQuery({ queryKey: ["series"], queryFn: () => api.get<{ since: string | null; series: { pipeline: string; points: SeriesPoint[] }[] }>("/api/metrics/series") });

export const useRuns = (params: Params) =>
  useQuery({ queryKey: ["runs", params], queryFn: () => api.list<RunRow>("/api/runs", params), placeholderData: keepPreviousData });

export const useRun = (id: number) => useQuery({ queryKey: ["run", id], queryFn: () => api.get<RunDetail>(`/api/runs/${id}`) });

export const useRunIncidents = (id: number, includeMuted: boolean) =>
  useQuery({
    queryKey: ["run", id, "incidents", includeMuted],
    queryFn: () => api.get<RunIncidents>(`/api/runs/${id}/incidents`, { include_muted: includeMuted ? "true" : undefined }),
    enabled: Number.isFinite(id) && id >= 0,
  });

export const useIncidentChart = (runId: number, incId: string, enabled: boolean) =>
  useQuery({
    queryKey: ["chart", runId, incId],
    queryFn: () => api.get<IncidentChart>(`/api/runs/${runId}/incidents/${incId}/chart`),
    enabled,
    staleTime: 60_000,
  });

export const useFindings = (runId: number, params: Params) =>
  useQuery({
    queryKey: ["run", runId, "findings", params],
    queryFn: () => api.list<Finding>(`/api/runs/${runId}/anomalies`, params),
    placeholderData: keepPreviousData,
  });

export const useDatasets = () => useQuery({ queryKey: ["datasets"], queryFn: () => api.get<Dataset[]>("/api/datasets") });
export const useAnalyses = (limit = 200) => useQuery({ queryKey: ["analyses", limit], queryFn: () => api.get<Analysis[]>("/api/analyses", { limit }) });
export const useProfile = (id: string) => useQuery({ queryKey: ["profile", id], queryFn: () => api.get<DatasetProfile>(`/api/datasets/${id}/profile`), staleTime: 300_000 });
export const useDetectors = () => useQuery({ queryKey: ["detectors"], queryFn: () => api.get<Detector[]>("/api/detectors"), staleTime: Infinity });

export const useAnalysis = (id: string) =>
  useQuery({
    queryKey: ["analysis", id],
    queryFn: () => api.get<Analysis>(`/api/analyses/${id}`),
    refetchInterval: (q) => (q.state.data && (q.state.data.status === "queued" || q.state.data.status === "running") ? 900 : false),
  });

export const useAnalysisRows = (id: string, params: Params) =>
  useQuery({
    queryKey: ["analysis", id, "rows", params],
    queryFn: () => api.get<AnalysisRows>(`/api/analyses/${id}/rows`, params),
    placeholderData: keepPreviousData,
  });

export const useChanges = (id: string, params: Params, enabled = true) =>
  useQuery({
    queryKey: ["analysis", id, "changes", params],
    queryFn: () => api.get<{ total: number; offset: number; items: Change[] }>(`/api/analyses/${id}/changes`, params),
    placeholderData: keepPreviousData,
    enabled,
  });

export const useReview = (params: Params) =>
  useQuery({ queryKey: ["review", "list", params], queryFn: () => api.list<ReviewItem>("/api/review", params), placeholderData: keepPreviousData });

export const useReviewFacets = (status: string) =>
  useQuery({ queryKey: ["review", "facets", status], queryFn: () => api.get<ReviewFacets>("/api/review/facets", { status }), placeholderData: keepPreviousData });

export const useReviewItem = (id: number | null) =>
  useQuery({ queryKey: ["review", "item", id], queryFn: () => api.get<ReviewDetail>(`/api/review/${id}`), enabled: id !== null });

export const usePipelines = () => useQuery({ queryKey: ["pipelines"], queryFn: () => api.get<PipelineList>("/api/pipelines") });
export const usePipeline = (id: string) => useQuery({ queryKey: ["pipeline", id], queryFn: () => api.get<PipelineDetail>(`/api/pipelines/${id}`) });
export const useTemplates = () => useQuery({ queryKey: ["templates"], queryFn: () => api.get<PipelineTemplate[]>("/api/pipelines/templates"), staleTime: Infinity });

export const useJobs = (enabled = true) =>
  useQuery({
    queryKey: ["jobs"],
    queryFn: () => api.get<Job[]>("/api/jobs", { limit: 12 }),
    enabled,
    refetchInterval: (q) => (q.state.data?.some((j) => j.status === "queued" || j.status === "running") ? 1000 : 15_000),
  });

export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/api/settings") });
