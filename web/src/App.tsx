import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router";

import { LoadingRows } from "@/components/common";
import { AppShell } from "@/components/layout/app-shell";
import { HealthPage } from "@/pages/health";
import { NotFoundPage } from "@/pages/not-found";

const RunsPage = lazy(() => import("@/pages/runs"));
const RunDetailPage = lazy(() => import("@/pages/run-detail"));
const ReviewPage = lazy(() => import("@/pages/review"));
const AnalyzePage = lazy(() => import("@/pages/analyze-upload"));
const DatasetPage = lazy(() => import("@/pages/analyze-dataset"));
const AnalysisPage = lazy(() => import("@/pages/analyze-results"));
const PipelinesPage = lazy(() => import("@/pages/pipelines"));
const PipelineDetailPage = lazy(() => import("@/pages/pipeline-detail"));
const SettingsPage = lazy(() => import("@/pages/settings"));

export function App() {
  return (
    <AppShell>
      <Suspense fallback={<LoadingRows rows={6} />}>
        <Routes>
          {/* Health lives at "/": GET /health is the server's liveness probe */}
          <Route path="/" element={<HealthPage />} />
          <Route path="/health" element={<Navigate to="/" replace />} />
          <Route path="/overview" element={<Navigate to="/" replace />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/analyze" element={<AnalyzePage />} />
          <Route path="/analyze/d/:id" element={<DatasetPage />} />
          <Route path="/analyze/a/:id" element={<AnalysisPage />} />
          <Route path="/pipelines" element={<PipelinesPage />} />
          <Route path="/pipelines/:id" element={<PipelineDetailPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
