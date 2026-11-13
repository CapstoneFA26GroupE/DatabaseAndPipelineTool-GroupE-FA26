import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getThumbnailUrl } from "../api/routes";
import { listSegmentsForRoute, getFrameCount } from "../api/segments";
import type { Segment } from "../api/types";
import { SEGMENT_TERMINAL_STATUSES } from "../api/types";
import { useRouteStatus } from "../hooks/useRouteStatus";
import { CvatJobRunsList } from "../components/segment-viewer/CvatJobRunsList";
import { SegmentViewerSkeleton } from "../components/segment-viewer/SegmentViewerSkeleton";
import { SegmentHero } from "../components/segment-viewer/SegmentHero";
import { SegmentThumbnailPanel } from "../components/segment-viewer/SegmentThumbnailPanel";
import { SegmentStats } from "../components/segment-viewer/SegmentStats";
import { SegmentNavigation } from "../components/segment-viewer/SegmentNavigation";
import { IntersectionTimeline } from "../components/segment-viewer/IntersectionTimeline";

export default function SegmentViewer() {
  const { routeId, segmentId } = useParams<{ routeId: string; segmentId: string }>();
  const navigate = useNavigate();
  const decodedRouteId = routeId ? decodeURIComponent(routeId) : "";
  const segIdx = segmentId !== undefined ? parseInt(segmentId, 10) : NaN;

  const [imgErrored, setImgErrored] = useState(false);
  useEffect(() => { setImgErrored(false); }, [segIdx]);

  const { data: route, isLoading: routeLoading, error: routeError } = useRouteStatus(decodedRouteId || undefined);

  const { data: segments = [], isLoading: segsLoading } = useQuery({
    queryKey: ["segments", decodedRouteId],
    queryFn: () => listSegmentsForRoute(decodedRouteId),
    enabled: !!decodedRouteId,
    refetchInterval: (query) => {
      const segs = query.state.data ?? [];
      return segs.some((s) => !SEGMENT_TERMINAL_STATUSES.includes(s.status)) ? 3000 : false;
    },
  });

  const { data: frameCount } = useQuery({
    queryKey: ["frame-count", decodedRouteId, segIdx],
    queryFn: () => getFrameCount(decodedRouteId, segIdx),
    enabled: !!decodedRouteId && !isNaN(segIdx),
  });

  const loading = routeLoading || segsLoading;
  const error = routeError ? (routeError as Error).message ?? "Failed to load segment" : null;

  if (loading) return <SegmentViewerSkeleton />;

  const segment: Segment | null =
    !isNaN(segIdx) && segIdx >= 0 && segIdx < segments.length
      ? segments[segIdx]
      : null;

  if (error || !route || !segment) {
    return (
      <div style={{ padding: "var(--space-12)", textAlign: "center" }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)", color: "var(--text-muted)" }}>
          {error ?? "Segment not found."}
        </div>
        <button
          onClick={() => navigate(`/routes/${encodeURIComponent(decodedRouteId)}`)}
          style={{ marginTop: "var(--space-4)", padding: "var(--space-2) var(--space-4)", backgroundColor: "var(--bg-inverse)", color: "var(--text-on-inverse)", border: "none", cursor: "pointer", fontFamily: "var(--font-mono)", fontSize: "var(--text-sm)" }}
        >
          ← Back to Route
        </button>
      </div>
    );
  }

  const prevSeg = segIdx > 0 ? segments[segIdx - 1] : null;
  const nextSeg = segIdx < segments.length - 1 ? segments[segIdx + 1] : null;

  return (
    <div style={{ paddingBottom: "var(--space-12)" }}>
      <SegmentHero
        routeId={route.id}
        segIdx={segIdx}
        segmentsLength={segments.length}
        status={segment.status}
        startSeconds={segment.startSeconds}
        durationSeconds={segment.durationSeconds}
        frameCount={frameCount}
        createdAt={route.createdAt}
      />

      <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: "var(--space-6)", marginTop: "var(--space-6)", alignItems: "start" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)" }}>
          <SegmentThumbnailPanel
            src={getThumbnailUrl(route.id, segment.index)}
            segIdx={segIdx}
            imgErrored={imgErrored}
            onError={() => setImgErrored(true)}
          />
          <IntersectionTimeline routeId={route.id} segmentId={segment.segmentId} />
          <CvatJobRunsList routeId={route.id} segmentId={segIdx} />
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
          <SegmentStats
            segIdx={segIdx}
            segmentsLength={segments.length}
            segment={segment}
            frameCount={frameCount}
            createdAt={route.createdAt}
          />
          <SegmentNavigation
            routeId={route.id}
            prevSeg={prevSeg}
            nextSeg={nextSeg}
          />
        </div>
      </div>
    </div>
  );
}
