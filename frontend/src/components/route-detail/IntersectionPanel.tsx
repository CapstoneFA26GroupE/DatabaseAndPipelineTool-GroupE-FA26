import { useMutation, useQueryClient } from "@tanstack/react-query";
import { reclassifyIntersections } from "../../api/intersections";
import type { IntersectionSummary } from "../../api/intersections";
import { FailureReason } from "../FailureReason";
import {
  EXPORT_INTERSECTION_FILTERS,
  INTERSECTION_STATUS_LABEL,
  INTERSECTION_STYLE,
  INTERSECTION_TYPES,
} from "../../utils/intersectionConfig";

interface Props {
  routeId: string;
  summary: IntersectionSummary | undefined;
  exportFilter: string;
  onExportFilterChange: (value: string) => void;
}

const smallCaps: React.CSSProperties = {
  fontSize: "9px",
  fontFamily: "var(--font-mono)",
  color: "var(--text-muted)",
  textTransform: "uppercase",
  letterSpacing: "0.08em",
  fontWeight: 600,
};

// this panel shows how the route's frames were labeled (signalized / unsignalized / non-intersection)
export function IntersectionPanel({ routeId, summary, exportFilter, onExportFilterChange }: Props) {
  const queryClient = useQueryClient();
  const rerun = useMutation({
    mutationFn: () => reclassifyIntersections(routeId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["intersections", routeId] }),
    meta: { errorTitle: "Could not re-run intersection labeling" },
  });

  const status = summary?.status ?? "pending";
  const counts = summary?.counts ?? {};
  const total = INTERSECTION_TYPES.reduce((sum, t) => sum + (counts[t] ?? 0), 0);
  const isDone = status === "done";
  const canRerun = status === "done" || status === "failed";
  const gpsShare = summary && summary.framesTotal > 0 ? Math.round((100 * summary.framesWithGps) / summary.framesTotal) : null;

  return (
    <section
      aria-label="Intersections"
      style={{ marginTop: "var(--space-5)", border: "1px solid var(--border-subtle)", backgroundColor: "var(--bg-surface)", padding: "var(--space-4)", display: "flex", flexDirection: "column", gap: "var(--space-3)" }}
    >
      {/* header: title, status, re-run */}
      <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", flexWrap: "wrap" }}>
        <span style={smallCaps}>Intersections</span>
        <span
          style={{ fontSize: "9px", fontWeight: 700, fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: "0.07em", padding: "2px 6px", border: "1px solid var(--border-subtle)", color: status === "failed" ? "var(--accent-alert)" : status === "done" ? "var(--accent-go)" : "var(--text-secondary)" }}
        >
          {INTERSECTION_STATUS_LABEL[status] ?? status}
        </span>
        {canRerun && (
          <button
            type="button"
            onClick={() => rerun.mutate()}
            disabled={rerun.isPending}
            title="Label this route's frames again"
            style={{ marginLeft: "auto", background: "none", border: "1px solid var(--border-subtle)", padding: "2px 8px", cursor: rerun.isPending ? "default" : "pointer", fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-secondary)" }}
          >
            {rerun.isPending ? "Queueing…" : "↻ Re-run"}
          </button>
        )}
      </div>

      {/* not labeled yet */}
      {status === "waiting_for_upload" && (
        <div style={{ fontSize: "11px", fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
          Frames are labeled automatically once the route finishes uploading.
        </div>
      )}
      {(status === "pending" || status === "running") && (
        <div style={{ fontSize: "11px", fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
          {status === "running"
            ? "Matching GPS positions to map intersections and checking frames for traffic lights…"
            : "Queued: the intersection worker will label this route shortly."}
        </div>
      )}
      {status === "failed" && summary?.error && <FailureReason text={summary.error} variant="block" />}

      {/* labeled: stacked bar + legend + facts */}
      {isDone && total > 0 && (
        <>
          <div style={{ display: "flex", height: "10px", width: "100%", overflow: "hidden", border: "1px solid var(--border-subtle)" }}>
            {INTERSECTION_TYPES.filter((t) => (counts[t] ?? 0) > 0).map((t) => (
              <div
                key={t}
                title={`${INTERSECTION_STYLE[t].label}: ${counts[t]} frames`}
                style={{ width: `${(100 * (counts[t] ?? 0)) / total}%`, backgroundColor: INTERSECTION_STYLE[t].color }}
              />
            ))}
          </div>
          <div style={{ display: "flex", gap: "var(--space-4)", flexWrap: "wrap" }}>
            {INTERSECTION_TYPES.filter((t) => t !== "unknown" || (counts.unknown ?? 0) > 0).map((t) => (
              <div key={t} style={{ display: "flex", alignItems: "center", gap: "6px", fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-secondary)" }}>
                <span style={{ width: "9px", height: "9px", backgroundColor: INTERSECTION_STYLE[t].color, border: "1px solid var(--border-subtle)" }} />
                <span style={{ color: "var(--text-primary)" }}>{INTERSECTION_STYLE[t].short}</span>
                <span>
                  {(counts[t] ?? 0).toLocaleString()} fr · {Math.round((100 * (counts[t] ?? 0)) / total)}%
                </span>
              </div>
            ))}
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-muted)", display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
            <span>{summary?.intersectionsPassed ?? 0} intersections passed</span>
            <span>· {summary?.signalizedIntersections ?? 0} signalized</span>
            {gpsShare !== null && <span>· GPS on {gpsShare}% of frames</span>}
            {summary && summary.framesGpsInterpolated > 0 && (
              <span title="frames without their own gps reading got a position from the readings just before and after them">
                ({summary.framesGpsInterpolated.toLocaleString()} filled in from neighbouring frames)
              </span>
            )}
            {summary?.camera.enabled && (
              <span>
                · camera checked {summary.camera.checkedIntersections} intersection{summary.camera.checkedIntersections === 1 ? "" : "s"} ({summary.camera.sampledFrames} frames)
              </span>
            )}
          </div>
          {summary?.camera.error && (
            <FailureReason text={`Camera check skipped (labels use map data only): ${summary.camera.error}`} tone="warning" variant="compact" maxWidth="100%" />
          )}
        </>
      )}
      {isDone && total === 0 && (
        <div style={{ fontSize: "11px", fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>No frames were labeled for this route.</div>
      )}

      {/* export filter used by the export buttons on job runs */}
      <label style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-secondary)", flexWrap: "wrap" }}>
        <span style={smallCaps}>Export frames</span>
        <select
          value={exportFilter}
          onChange={(e) => onExportFilterChange(e.target.value)}
          disabled={!isDone}
          title={isDone ? "Applies to the Export buttons on this route's job runs" : "Available once the route's frames are labeled"}
          style={{ padding: "var(--space-1) var(--space-2)", border: "1px solid var(--border-subtle)", backgroundColor: "var(--bg-surface)", fontSize: "var(--text-xs)", color: "var(--text-primary)", cursor: isDone ? "pointer" : "not-allowed" }}
        >
          {EXPORT_INTERSECTION_FILTERS.map((f) => (
            <option key={f.value} value={f.value}>{f.label}</option>
          ))}
        </select>
        <span style={{ color: "var(--text-muted)", fontSize: "10px" }}>applies to the job run Export buttons above</span>
      </label>
    </section>
  );
}
