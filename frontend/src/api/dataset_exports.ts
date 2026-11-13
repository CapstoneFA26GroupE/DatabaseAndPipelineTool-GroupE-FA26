import { apiFetch, API_BASE } from "./client";

export type DatasetExportStatus = "queued" | "running" | "succeeded" | "failed";

interface DatasetExportJobRunSelectionResponse {
  job_def_id: number;
  job_run_num: number;
  camera: string;
}

interface DatasetExportResponse {
  export_id: number;
  route_id: string;
  camera_views: string[];
  status: DatasetExportStatus;
  error: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  zip_artifact_id: string | null;
  intersection_types?: string[] | null;
  job_runs: DatasetExportJobRunSelectionResponse[];
}

export interface DatasetExport {
  exportId: number;
  routeId: string;
  cameraViews: string[];
  status: DatasetExportStatus;
  error: string | null;
  queuedAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  zipArtifactId: string | null;
  // null means every frame was exported
  intersectionTypes: string[] | null;
  jobRuns: { jobDefId: number; jobRunNum: number; camera: string }[];
}

function mapDatasetExport(r: DatasetExportResponse): DatasetExport {
  return {
    exportId: r.export_id,
    routeId: r.route_id,
    cameraViews: r.camera_views,
    status: r.status,
    error: r.error,
    queuedAt: r.queued_at,
    startedAt: r.started_at,
    finishedAt: r.finished_at,
    zipArtifactId: r.zip_artifact_id,
    intersectionTypes: r.intersection_types ?? null,
    jobRuns: r.job_runs.map((j) => ({
      jobDefId: j.job_def_id,
      jobRunNum: j.job_run_num,
      camera: j.camera,
    })),
  };
}

export async function listDatasetExportsForRoute(routeId: string): Promise<DatasetExport[]> {
  const data = await apiFetch<DatasetExportResponse[]>(
    `/dataset-exports/?route_id=${encodeURIComponent(routeId)}`
  );
  return data.map(mapDatasetExport);
}

export async function createDatasetExport(payload: {
  routeId: string;
  cameraViews: string[];
  jobRuns: { jobDefId: number; jobRunNum: number; camera: string }[];
  intersectionTypes?: string[] | null;
}): Promise<DatasetExport> {
  const data = await apiFetch<DatasetExportResponse>("/dataset-exports/", {
    method: "POST",
    body: JSON.stringify({
      route_id: payload.routeId,
      camera_views: payload.cameraViews,
      job_runs: payload.jobRuns.map((j) => ({
        job_def_id: j.jobDefId,
        job_run_num: j.jobRunNum,
        camera: j.camera,
      })),
      intersection_types: payload.intersectionTypes ?? null,
    }),
  });
  return mapDatasetExport(data);
}

export async function getDatasetExport(exportId: number): Promise<DatasetExport> {
  const data = await apiFetch<DatasetExportResponse>(`/dataset-exports/${exportId}`);
  return mapDatasetExport(data);
}

export async function deleteDatasetExport(exportId: number): Promise<void> {
  await apiFetch<void>(`/dataset-exports/${exportId}`, { method: "DELETE" });
}

export function getDatasetExportDownloadUrl(exportId: number): string {
  return `${API_BASE}/dataset-exports/${exportId}/download`;
}
