import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { listIntersectionFrames } from "../../api/intersections";
import type { IntersectionFrame, IntersectionType } from "../../api/intersections";
import { INTERSECTION_STYLE, INTERSECTION_TYPES } from "../../utils/intersectionConfig";

interface Run {
  type: IntersectionType;
  firstFrame: number;
  lastFrame: number;
  frames: number;
  closest: IntersectionFrame;
}

// this groups consecutive frames with the same label into runs, e.g. frames 120-260 signalized
function toRuns(frames: IntersectionFrame[]): Run[] {
  const runs: Run[] = [];
  for (const frame of frames) {
    const last = runs[runs.length - 1];
    const sameIntersection = last && last.type === frame.type && last.closest.details?.intersection_id === frame.details?.intersection_id;
    if (last && sameIntersection) {
      last.lastFrame = frame.frameId;
      last.frames += 1;
      if ((frame.details?.distance_m ?? Infinity) < (last.closest.details?.distance_m ?? Infinity)) last.closest = frame;
    } else {
      runs.push({ type: frame.type, firstFrame: frame.frameId, lastFrame: frame.frameId, frames: 1, closest: frame });
    }
  }
  return runs;
}

// this shows where in the segment the car was at an intersection, as a colored timeline and a list
export function IntersectionTimeline({ routeId, segmentId }: { routeId: string; segmentId: number }) {
  const [shown, setShown] = useState<Set<IntersectionType>>(new Set(["signalized_intersection", "unsignalized_intersection"]));

  const { data: frames = [], isLoading } = useQuery({
    queryKey: ["intersection-frames", routeId, segmentId],
    queryFn: () => listIntersectionFrames(routeId, segmentId),
  });

  const runs = useMemo(() => toRuns(frames), [frames]);
  const listed = runs.filter((r) => shown.has(r.type));

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
          {/* timeline: one stripe per run of frames, width proportional to its length */}
          <div className="flex h-[14px] w-full overflow-hidden border border-[var(--border-subtle)]">
            {runs.map((run) => (
              <div
                key={`${run.firstFrame}-${run.type}`}
                title={`Frames ${run.firstFrame}–${run.lastFrame}: ${INTERSECTION_STYLE[run.type].label}`}
                style={{ width: `${(100 * run.frames) / frames.length}%`, backgroundColor: INTERSECTION_STYLE[run.type].color }}
              />
            ))}
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

          {/* list of runs with why each one got its label */}
          <div className="flex flex-col gap-[var(--space-2)] mt-[var(--space-3)]">
            {listed.length === 0 ? (
              <div className="[font-family:var(--font-mono)] text-[11px] text-[var(--text-muted)]">No frames with the selected labels in this segment.</div>
            ) : (
              listed.map((run) => {
                const d = run.closest.details ?? {};
                return (
                  <div key={`${run.firstFrame}-${run.type}`} className="flex flex-wrap items-center gap-[var(--space-3)] py-[var(--space-2)] px-[var(--space-3)] bg-[var(--bg-elevated)] border border-[var(--border-subtle)]">
                    <span className="w-[8px] h-[8px] shrink-0" style={{ backgroundColor: INTERSECTION_STYLE[run.type].color }} />
                    <span className="text-[11px] [font-family:var(--font-mono)] text-[var(--text-primary)] min-w-[150px]">
                      {INTERSECTION_STYLE[run.type].label}
                    </span>
                    <span className="text-[10px] [font-family:var(--font-mono)] text-[var(--text-secondary)]">
                      frames {run.firstFrame}–{run.lastFrame} ({run.frames})
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
