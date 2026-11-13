import { apiFetch } from "./client";

// intersection labels the intersection_worker puts on every frame after a route is uploaded
export type IntersectionType =
  | "signalized_intersection"
  | "unsignalized_intersection"
  | "non_intersection"
  | "unknown";

export type IntersectionStatus = "waiting_for_upload" | "pending" | "running" | "done" | "failed";

interface IntersectionSummaryResponse {
  route_id: string;
  status: IntersectionStatus;
  version: number | null;
  error: string | null;
  error_code: string | null;
  started_at: string | null;
  finished_at: string | null;
  counts: Partial<Record<IntersectionType, number>>;
  segments: { segment_id: number; counts: Partial<Record<IntersectionType, number>> }[];
  frames_total: number;
  frames_with_gps: number;
  intersections_passed: number;
  signalized_intersections: number;
  camera: { enabled: boolean; sampled_frames: number; checked_intersections: number; error: string | null };
}

export interface IntersectionSummary {
  routeId: string;
  status: IntersectionStatus;
  error: string | null;
  errorCode: string | null;
  finishedAt: string | null;
  counts: Partial<Record<IntersectionType, number>>;
  // segment_id -> frames per label
  segmentCounts: Record<number, Partial<Record<IntersectionType, number>>>;
  framesTotal: number;
  framesWithGps: number;
  intersectionsPassed: number;
  signalizedIntersections: number;
  camera: { enabled: boolean; sampledFrames: number; checkedIntersections: number; error: string | null };
}

export interface IntersectionFrame {
  segmentId: number;
  frameId: number;
  type: IntersectionType;
  details: {
    intersection_id?: string;
    distance_m?: number;
    source?: string;
    confidence?: string;
    reason?: string;
    map_controls?: string[];
    road_types?: string[];
    camera_sampled?: number;
    camera_signal_frames?: number;
  } | null;
}

// this turns the api's snake_case summary into the shape the ui uses
function mapSummary(r: IntersectionSummaryResponse): IntersectionSummary {
  return {
    routeId: r.route_id,
    status: r.status,
    error: r.error,
    errorCode: r.error_code,
    finishedAt: r.finished_at,
    counts: r.counts,
    segmentCounts: Object.fromEntries(r.segments.map((s) => [s.segment_id, s.counts])),
    framesTotal: r.frames_total,
    framesWithGps: r.frames_with_gps,
    intersectionsPassed: r.intersections_passed,
    signalizedIntersections: r.signalized_intersections,
    camera: {
      enabled: r.camera?.enabled ?? false,
      sampledFrames: r.camera?.sampled_frames ?? 0,
      checkedIntersections: r.camera?.checked_intersections ?? 0,
      error: r.camera?.error ?? null,
    },
  };
}

export async function getIntersectionSummary(routeId: string): Promise<IntersectionSummary> {
  const data = await apiFetch<IntersectionSummaryResponse>(
    `/intersections/summary?route_id=${encodeURIComponent(routeId)}`,
  );
  return mapSummary(data);
}

export async function listIntersectionFrames(
  routeId: string,
  segmentId?: number,
  types?: IntersectionType[],
): Promise<IntersectionFrame[]> {
  const params = new URLSearchParams({ route_id: routeId });
  if (segmentId !== undefined) params.set("segment_id", String(segmentId));
  for (const t of types ?? []) params.append("intersection_type", t);
  const data = await apiFetch<
    { segment_id: number; frame_id: number; intersection_type: IntersectionType; intersection_details: IntersectionFrame["details"] }[]
  >(`/intersections/frames?${params.toString()}`);
  return data.map((f) => ({ segmentId: f.segment_id, frameId: f.frame_id, type: f.intersection_type, details: f.intersection_details }));
}

export async function reclassifyIntersections(routeId: string): Promise<void> {
  await apiFetch(`/intersections/reclassify?route_id=${encodeURIComponent(routeId)}`, { method: "POST" });
}
