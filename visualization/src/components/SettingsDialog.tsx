import { useState, useEffect } from "react";
import { FolderOpen } from "lucide-react";

import { useAppStore } from "../store/appStore";

interface SettingsDialogProps {
  open: boolean;
  onClose: () => void;
}

export function SettingsDialog({ open, onClose }: SettingsDialogProps) {
  const projectRoot = useAppStore((s) => s.projectRoot);
  const setProjectRoot = useAppStore((s) => s.setProjectRoot);
  const [value, setValue] = useState(projectRoot);

  useEffect(() => {
    if (open) setValue(projectRoot);
  }, [open, projectRoot]);

  if (!open) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">Settings</div>
        <div className="modal-body">
          <label
            className="text-xs text-muted"
            style={{ display: "block", marginBottom: 6 }}
          >
            Project root directory
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              className="input"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="B:/WorkSpace/TinySoul-Agent"
            />
            <button
              className="btn btn-ghost btn-icon"
              onClick={() => {
                const fallback = prompt("Project root directory", value);
                if (fallback !== null) setValue(fallback);
              }}
              title="Browse"
            >
              <FolderOpen size={16} />
            </button>
          </div>
          <p className="text-xs text-muted mt-2">
            TinySoul connects to the running instance for this project root.
          </p>
        </div>
        <div className="modal-footer">
          <button className="btn btn-ghost btn-sm" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => {
              setProjectRoot(value.trim() || projectRoot);
              onClose();
            }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
