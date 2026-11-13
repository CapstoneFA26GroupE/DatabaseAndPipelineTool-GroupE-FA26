import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listIntersectionFrames } from "../../api/intersections";
import type { IntersectionFrame, IntersectionType } from "../../api/intersections";
import { INTERSECTION_STYLE, INTERSECTION_TYPES } from "../../utils/intersectionConfig";

interface Run {
  type: IntersectionType;
  firstFrame: number;
  lastFrame: number;
}

interface Pass {
  type: IntersectionType;
  intersectionId: string;
  firstFrame: number;
  lastFrame: number;
  frames: number;
  closest: IntersectionFrame;
}

// frames of the same intersection more than this many frame ids apart (20 fps -> 3 s) count as separate passes
const PASS_GAP_FRAMES = 60;

// this groups consecutive frames with the same label into runs for the colored timeline
function toRuns(frames: IntersectionFrame[]): Run[] {
  const runs: Run[] = [];
  for (const frame of frames) {
    const last = runs[runs.length - 1];
    if (last && last.type === frame.type) last.lastFrame = frame.frameId;
    else runs.push({ type: frame.type, firstFrame: frame.frameId, lastFrame: frame.frameId });
  }
  return runs;
}

// this turns intersection frames into one row per time the car went through an intersection,
// so a few unlabeled frames in the middle don't split one pass into many rows
function toPasses(frames: IntersectionFrame[]): Pass[] {
  const passes: Pass[] = [];
  const open = new Map<string, Pass>();
  for (const frame of frames) {
    const id = frame.details?.intersection_id;
    if (!id) continue;
    const key = `${id}|${frame.type}`;
    const current = open.get(key);
    if (current && frame.frameId - current.lastFrame <= PASS_GAP_FRAMES) {
      current.lastFrame = frame.frameId;
      current.frames += 1;
      if ((frame.details?.distance_m ?? Infinity) < (current.closest.details?.distance_m ?? Infinity)) current.closest = frame;
    } else {
      const pass = { type: frame.type, intersectionId: id, firstFrame: frame.frameId, lastFrame: frame.frameId, frames: 1, closest: frame };
      passes.push(pass);
      open.set(key, pass);
    }
  }
  return passes;
}

// this shows where in the segment the car was at an intersection, as a colored timeline and a list
export function IntersectionTimeline({ routeId, segmentId }: { routeId: string; segmentId: number }) {
  const [shown, setShown] = useState<Set<IntersectionType>>(new Set(["signalized_intersection", "unsignalized_intersection"]));

  const { data: frames = [], isLoading } = useQuery({
    queryKey: ["intersection-frames", routeId, segmentId],
    queryFn: () => listIntersectionFrames(routeId, segmentId),
  });

  const runs = useMemo(() => toRuns(frames), [frames]);
  const passes = useMemo(() => toPasses(frames), [frames]);
  const listed = passes.filter((p) => shown.has(p.type));
  const firstId = frames[0]?.frameId ?? 0;
  const span = Math.max(1, (frames[frames.length - 1]?.frameId ?? 0) - firstId + 1);

  const toggle = (type: IntersectionType) => {
    const next = new Set(shown);
    if (next.has(type)) next.delete(type);
    else next.add(type);
    setShown(next);
  };

  return (
    <div className="border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-[var(--space-5)]">
      <div className="text-[10px] [font-family:var(--font-mono)] uppercase tracking-[0.09em] text-[var(--text-muted)] font-semibold mb-[var(--space-3)]">
        Intersections
      </div>

      {isLoading ? (
        <div className="[font-family:var(--font-mono)] text-[11px] text-[var(--text-muted)]">Loading…</div>
      ) : frames.length === 0 ? (
        <div className="[font-family:var(--font-mono)] text-[11px] text-[var(--text-muted)]">
          This segment's frames haven't been labeled yet. Labels appear automatically after the route uploads.
        </div>
      ) : (
        <>
          {/* timeline: one stripe per run of frames, placed by frame number so gaps keep their real length */}
          <div className="relative h-[14px] w-full overflow-hidden border border-[var(--border-subtle)]">
            {runs.map((run, i) => {
              // each run reaches to where the next one starts, so the bar has no holes
              const end = i + 1 < runs.length ? runs[i + 1].firstFrame : run.lastFrame + 1;
              return (
                <div
                  key={`${run.firstFrame}-${run.type}`}
                  title={`Frames ${run.firstFrame}–${run.lastFrame}: ${INTERSECTION_STYLE[run.type].label}`}
                  className="absolute top-0 h-full"
                  style={{ left: `${(100 * (run.firstFrame - firstId)) / span}%`, width: `${(100 * (end - run.firstFrame)) / span}%`, backgroundColor: INTERSECTION_STYLE[run.type].color }}
                />
              );
            })}
          </div>
          <div className="flex justify-between [font-family:var(--font-mono)] text-[9px] text-[var(--text-muted)] mt-[2px]">
            <span>frame {frames[0].frameId}</span>
            <span>frame {frames[frames.length - 1].frameId}</span>
          </div>

          {/* filter chips: which labels to list below */}
          <div className="flex flex-wrap gap-[var(--space-2)] mt-[var(--space-3)]">
            {INTERSECTION_TYPES.map((type) => {
              const active = shown.has(type);
              const count = frames.filter((f) => f.type === type).length;
              return (
                <button
                  key={type}
                  type="button"
                  onClick={() => toggle(type)}
                  aria-pressed={active}
                  className="flex items-center gap-[5px] px-[var(--space-2)] py-[2px] border [font-family:var(--font-mono)] text-[10px] cursor-pointer"
                  style={{ borderColor: active ? INTERSECTION_STYLE[type].color : "var(--border-subtle)", color: active ? "var(--text-primary)" : "var(--text-muted)", backgroundColor: "transparent" }}
                >
                  <span className="w-[8px] h-[8px]" style={{ backgroundColor: INTERSECTION_STYLE[type].color }} />
                  {INTERSECTION_STYLE[type].short} ({count})
                </button>
              );
            })}
          </div>

          {/* one row per intersection the car went through, with why it got its label */}
          <div className="flex flex-col gap-[var(--space-2)] mt-[var(--space-3)]">
            {listed.length === 0 ? (
              <div className="[font-family:var(--font-mono)] text-[11px] text-[var(--text-muted)]">No frames with the selected labels in this segment.</div>
            ) : (
              listed.map((run) => {
                const d = run.closest.details ?? {};
                return (
                  <div key={`${run.intersectionId}-${run.firstFrame}`} className="flex flex-wrap items-center gap-[var(--space-3)] py-[var(--space-2)] px-[var(--space-3)] bg-[var(--bg-elevated)] border border-[var(--border-subtle)]">
                    <span className="w-[8px] h-[8px] shrink-0" style={{ backgroundColor: INTERSECTION_STYLE[run.type].color }} />
                    <span className="text-[11px] [font-family:var(--font-mono)] text-[var(--text-primary)] min-w-[150px]">
                      {INTERSECTION_STYLE[run.type].label}
                    </span>
                    <span className="text-[10px] [font-family:var(--font-mono)] text-[var(--text-secondary)]">
                      frames {run.firstFrame}–{run.lastFrame} ({run.frames} labeled)
                    </span>
                    {d.distance_m !== undefined && (
                      <span className="text-[10px] [font-family:var(--font-mono)] text-[var(--text-muted)]">closest {d.distance_m} m</span>
                    )}
                    {d.confidence && (
                      <span className="text-[10px] [font-family:var(--font-mono)] text-[var(--text-muted)]">
                        {d.confidence} confidence · {d.source}
                      </span>
                    )}
                    {d.reason && <span className="basis-full text-[10px] [font-family:var(--font-mono)] text-[var(--text-muted)]">{d.reason}</span>}
                  </div>
                );
              })
            )}
          </div>
        </>
      )}
    </div>
  );
}
