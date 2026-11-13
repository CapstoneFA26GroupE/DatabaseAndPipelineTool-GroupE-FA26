import type { IntersectionStatus, IntersectionType } from "../api/intersections";

// display names and colors for the intersection labels (colors are css tokens in index.css)
export const INTERSECTION_TYPES: IntersectionType[] = [
  "signalized_intersection",
  "unsignalized_intersection",
  "non_intersection",
  "unknown",
];

export const INTERSECTION_STYLE: Record<IntersectionType, { label: string; short: string; color: string }> = {
  signalized_intersection: { label: "Signalized intersection", short: "Signalized", color: "var(--intersection-signalized)" },
  unsignalized_intersection: { label: "Unsignalized intersection", short: "Unsignalized", color: "var(--intersection-unsignalized)" },
  non_intersection: { label: "Non-intersection", short: "Non-intersection", color: "var(--intersection-none)" },
  unknown: { label: "Unknown (no GPS)", short: "Unknown", color: "var(--intersection-unknown)" },
};

export const INTERSECTION_STATUS_LABEL: Record<IntersectionStatus, string> = {
  waiting_for_upload: "Waiting for upload",
  pending: "Queued",
  running: "Labeling…",
  done: "Done",
  failed: "Failed",
};

// segment filter options on the route page
export type SegmentIntersectionFilter = "all" | "signalized" | "unsignalized" | "any" | "none";

export const SEGMENT_INTERSECTION_FILTERS: { value: SegmentIntersectionFilter; label: string }[] = [
  { value: "all", label: "All intersections" },
  { value: "signalized", label: "Has signalized" },
  { value: "unsignalized", label: "Has unsignalized" },
  { value: "any", label: "Has any intersection" },
  { value: "none", label: "No intersections" },
];

// this decides if a segment matches the selected intersection filter, from its per-label frame counts
export function segmentMatchesIntersectionFilter(
  counts: Partial<Record<IntersectionType, number>> | undefined,
  filter: SegmentIntersectionFilter,
): boolean {
  if (filter === "all") return true;
  const signalized = counts?.signalized_intersection ?? 0;
  const unsignalized = counts?.unsignalized_intersection ?? 0;
  if (filter === "signalized") return signalized > 0;
  if (filter === "unsignalized") return unsignalized > 0;
  if (filter === "any") return signalized + unsignalized > 0;
  return counts !== undefined && signalized + unsignalized === 0;
}

// export filter options: which frames go into a dataset export
export const EXPORT_INTERSECTION_FILTERS: { value: string; label: string; types: IntersectionType[] | null }[] = [
  { value: "all", label: "All frames", types: null },
  { value: "signalized", label: "Signalized intersections only", types: ["signalized_intersection"] },
  { value: "unsignalized", label: "Unsignalized intersections only", types: ["unsignalized_intersection"] },
  { value: "intersections", label: "Any intersection", types: ["signalized_intersection", "unsignalized_intersection"] },
  { value: "non", label: "Non-intersection only", types: ["non_intersection"] },
];
