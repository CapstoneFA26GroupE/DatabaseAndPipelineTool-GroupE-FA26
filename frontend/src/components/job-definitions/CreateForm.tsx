import { useState } from "react";
import { createJobDefinition } from "../../api/job_definitions";
import type { JobDefinition, JobDefinitionCreate } from "../../api/types";
import { ConfigEditor } from "./ConfigEditor";

// ─── CreateForm ───────────────────────────────────────────────────────────────

export function CreateForm({ onCreated }: { onCreated: (def: JobDefinition) => void }) {
  const [name, setName] = useState("");
  const [implKey, setImplKey] = useState("");
  const [description, setDescription] = useState("");
  const [config, setConfig] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showInfo, setShowInfo] = useState(false);

  const canSubmit = Boolean(name.trim() && implKey.trim() && !submitting);

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);

    // Attempt to JSON-parse each value; fall back to string
    const parsedConfig: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(config)) {
      if (!k.trim()) continue;
      try { parsedConfig[k] = JSON.parse(v); }
      catch { parsedConfig[k] = v; }
    }

    const payload: JobDefinitionCreate = {
      type: "object_detection",
      implementation_key: implKey,
      name: name.trim(),
      config: parsedConfig,
      description: description.trim(),
    };

    try {
      const result = await createJobDefinition(payload);
      setName("");
      setImplKey("");
      setDescription("");
      setConfig({});
      onCreated(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create job definition");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="jd-create-card">
      <div className="jd-create-card__header">
        <div className="jd-create-card__title-row">
          <div className="jd-create-card__title">New Job Definition</div>
          <button
            type="button"
            className="jd-info-btn"
            aria-label="Show setup info"
            aria-expanded={showInfo}
            onClick={() => setShowInfo((v) => !v)}
          >
            i
          </button>
        </div>
        <div className="jd-create-card__subtitle">
          Define a new annotation job type for routes
        </div>
      </div>

      <div className="jd-create-card__body">
        {showInfo && (
          <div className="jd-info-panel">
            Implementation Key is the name of the Python class that runs the job, and Config holds the parameters passed to that class (e.g. detection transformers need a model name).
          </div>
        )}

        {/* Name */}
        <div>
          <label className="jd-label">Name *</label>
          <input
            className="jd-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. YOLOv8 Object Detection"
          />
        </div>

        {/* Implementation Key */}
        <div>
          <label className="jd-label">Implementation Key *</label>
          <input
            className="jd-input"
            value={implKey}
            onChange={(e) => setImplKey(e.target.value)}
            placeholder="e.g. YOLOv8Detector"
          />
        </div>

        {/* Description */}
        <div>
          <label className="jd-label">Description</label>
          <textarea
            className="jd-input jd-textarea"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe what this job definition does..."
          />
        </div>

        {/* Config */}
        <ConfigEditor config={config} onChange={setConfig} />

        {/* Error */}
        {error && <div className="jd-error">{error}</div>}

        {/* Submit */}
        <button
          className="jd-btn jd-btn--submit"
          onClick={handleSubmit}
          disabled={!canSubmit}
          data-submitting={submitting}
        >
          {submitting ? "Creating…" : "Create Definition"}
        </button>
      </div>
    </div>
  );
}
