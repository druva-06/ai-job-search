#!/usr/bin/env python3
"""Interactive Web Dashboard & Manager for job_scraper/seen_jobs.json.

Provides a modern web interface to filter, inspect, manage, and delete records
from seen_jobs.json with:
  - Rich filtering: Date (Today, Yesterday, Past 7 Days, custom ranges), Company,
    Portal, Fit score/verdict, Status, Location, and full-text search.
  - Live Auto-Update: Detects file updates on disk and refreshes seamlessly.
  - Granular & Bulk Deletions: Delete selected, delete by date, delete by max cap,
    or delete all filtered items.
  - Data Safety: Automatic backups (job_scraper/seen_jobs.json.bak-*) and atomic
    file writes before any deletion, with 1-click Undo.
  - Standalone Static Export: Ability to generate an offline, self-contained HTML
    report.

Zero external dependencies - uses standard library Python only.
"""

import argparse
import csv
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATE_FILE = ROOT / "job_scraper" / "seen_jobs.json"
DEFAULT_PORT = 8765
DEFAULT_HOST = "127.0.0.1"


# ---------------------------------------------------------------------------
# Data Layer: Atomic Storage, Backups & Deletions
# ---------------------------------------------------------------------------

def file_signature(path: Path) -> str:
    """Return a change token that survives same-size and coarse-mtime writes."""
    if not path.exists():
        return "missing"
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}:{stat.st_ino}"


def load_data(path: Path) -> tuple[dict, dict]:
    """Load seen_jobs.json ensuring correct structure."""
    if not path.is_file():
        return {"seen": {}}, {}
    try:
        content = path.read_text(encoding="utf-8")
        doc = json.loads(content)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Failed to read {path}: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("seen"), dict):
        raise ValueError(f"{path}: expected JSON object with 'seen' dictionary")
    return doc, doc["seen"]


def save_data(path: Path, doc: dict) -> None:
    """Atomically save seen_jobs.json using tempfile + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".seen_jobs.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def create_backup(path: Path) -> Path | None:
    """Create timestamped backup in seen_jobs.json.bak-<timestamp> format."""
    if not path.is_file():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = path.parent / f"seen_jobs.json.bak-{timestamp}"
    shutil.copy2(path, backup_path)
    return backup_path


def list_backups(dir_path: Path) -> list[dict]:
    """List available backups ordered newest first."""
    backups = []
    prefix = "seen_jobs.json.bak-"
    for file in dir_path.glob(f"{prefix}*"):
        if file.is_file():
            stat = file.stat()
            backups.append({
                "filename": file.name,
                "path": str(file),
                "timestamp": stat.st_mtime,
                "date_str": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "size_bytes": stat.st_size,
            })
    backups.sort(key=lambda b: b["timestamp"], reverse=True)
    return backups


def restore_backup(path: Path, backup_file: str | None = None) -> tuple[int, str]:
    """Restore from latest or specified backup."""
    backups = list_backups(path.parent)
    if not backups:
        raise ValueError("No backups found to restore.")
    target = None
    if backup_file:
        for b in backups:
            if b["filename"] == backup_file or b["path"] == backup_file:
                target = Path(b["path"])
                break
        if not target:
            raise ValueError(f"Backup {backup_file} not found.")
    else:
        target = Path(backups[0]["path"])

    doc, seen = load_data(target)
    save_data(path, doc)
    return len(seen), target.name


def parse_date_str(value) -> date | None:
    """Defensively parse YYYY-MM-DD or return None."""
    if not isinstance(value, str):
        return None
    val = value.strip()
    if len(val) >= 10:
        val = val[:10]
    try:
        return date.fromisoformat(val)
    except ValueError:
        return None


def delete_keys(doc: dict, keys: list[str]) -> tuple[dict, int]:
    """Delete a specific set of keys from doc['seen']."""
    seen = doc.get("seen", {})
    initial = len(seen)
    for k in keys:
        seen.pop(k, None)
    return doc, initial - len(seen)


def delete_by_date(
    doc: dict,
    field: str = "first_seen",
    op: str = "before",
    target_date: date | str = None,
) -> tuple[dict, int]:
    """Delete jobs where `field` is before/on/after `target_date`."""
    if isinstance(target_date, str):
        target_date = parse_date_str(target_date)
    if not target_date:
        raise ValueError("Valid target date required")

    seen = doc.get("seen", {})
    to_delete = []
    for key, item in seen.items():
        item_date = parse_date_str(item.get(field))
        if not item_date:
            continue
        if op == "before" and item_date < target_date:
            to_delete.append(key)
        elif op == "on" and item_date == target_date:
            to_delete.append(key)
        elif op == "after" and item_date > target_date:
            to_delete.append(key)
        elif op == "on_or_before" and item_date <= target_date:
            to_delete.append(key)

    for k in to_delete:
        seen.pop(k, None)
    return doc, len(to_delete)


def delete_older_than(
    doc: dict,
    days: int,
    field: str = "first_seen",
    reference_date: date | None = None,
) -> tuple[dict, int]:
    """Delete jobs older than N days relative to reference_date (defaults to today)."""
    if reference_date is None:
        reference_date = datetime.now(timezone.utc).date()
    cutoff = reference_date - timedelta(days=days)
    return delete_by_date(doc, field=field, op="before", target_date=cutoff)


def delete_max_cap(
    doc: dict,
    keep_count: int,
    sort_by: str = "first_seen",
) -> tuple[dict, int]:
    """Keep newest `keep_count` jobs based on date field, delete the remainder."""
    seen = doc.get("seen", {})
    if len(seen) <= keep_count:
        return doc, 0

    def sort_key(item_pair):
        key, item = item_pair
        d = parse_date_str(item.get(sort_by)) or date.min
        # Secondary key is rank_score if available
        score = item.get("rank_score") or 0
        return (d, score)

    sorted_items = sorted(seen.items(), key=sort_key, reverse=True)
    kept_items = dict(sorted_items[:keep_count])
    deleted_count = len(seen) - len(kept_items)
    doc["seen"] = kept_items
    return doc, deleted_count


# ---------------------------------------------------------------------------
# HTML, CSS & JavaScript Single Page Application Template
# ---------------------------------------------------------------------------

FRONTEND_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Seen Jobs Explorer & Manager</title>
  <style>
    :root {
      --bg: #0f172a;
      --bg-surface: #1e293b;
      --bg-card: #243248;
      --bg-input: #0f172a;
      --border: #334155;
      --border-focus: #38bdf8;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-hover: #0ea5e9;
      --success: #10b981;
      --warning: #f59e0b;
      --danger: #ef4444;
      --danger-hover: #dc2626;
      --badge-bg: #334155;
      --radius: 8px;
      --radius-lg: 12px;
      --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }

    [data-theme="light"] {
      --bg: #f8fafc;
      --bg-surface: #ffffff;
      --bg-card: #f1f5f9;
      --bg-input: #ffffff;
      --border: #cbd5e1;
      --border-focus: #0284c7;
      --text: #0f172a;
      --text-muted: #64748b;
      --accent: #0284c7;
      --accent-hover: #0369a1;
      --success: #059669;
      --warning: #d97706;
      --danger: #dc2626;
      --danger-hover: #b91c1c;
      --badge-bg: #e2e8f0;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: var(--font);
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.5;
      min-height: 100vh;
      padding-bottom: 80px;
    }

    /* Header */
    header {
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border);
      padding: 1rem 1.5rem;
      position: sticky;
      top: 0;
      z-index: 40;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 0.75rem;
    }
    .brand-icon {
      background: linear-gradient(135deg, #38bdf8, #818cf8);
      color: #0f172a;
      font-weight: 800;
      width: 38px;
      height: 38px;
      border-radius: var(--radius);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.25rem;
    }
    .brand h1 {
      font-size: 1.25rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }
    .brand-sub {
      font-size: 0.75rem;
      color: var(--text-muted);
    }
    .header-actions {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      flex-wrap: wrap;
    }
    .live-pill {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      background: rgba(16, 185, 129, 0.15);
      color: var(--success);
      padding: 0.3rem 0.75rem;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
      border: 1px solid rgba(16, 185, 129, 0.3);
    }
    .pulse-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--success);
      box-shadow: 0 0 0 rgba(16, 185, 129, 0.5);
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
      70% { box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
      100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
    }

    /* Buttons */
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.45rem 0.85rem;
      border-radius: var(--radius);
      font-size: 0.85rem;
      font-weight: 500;
      cursor: pointer;
      border: 1px solid var(--border);
      background: var(--bg-surface);
      color: var(--text);
      transition: all 0.15s ease;
      text-decoration: none;
    }
    .btn:hover { background: var(--bg-card); border-color: var(--border-focus); }
    .btn-primary { background: var(--accent); color: #0f172a; border-color: var(--accent); font-weight: 600; }
    .btn-primary:hover { background: var(--accent-hover); color: #0f172a; }
    .btn-danger { background: rgba(239, 68, 68, 0.15); color: var(--danger); border-color: rgba(239, 68, 68, 0.3); }
    .btn-danger:hover { background: var(--danger); color: #ffffff; }
    .btn-sm { padding: 0.25rem 0.5rem; font-size: 0.75rem; }

    /* Main Container */
    .container {
      max-width: 1440px;
      margin: 0 auto;
      padding: 1.5rem;
    }

    /* Stats Banner */
    .stats-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 1rem;
      margin-bottom: 1.5rem;
    }
    .stat-card {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 1rem 1.25rem;
      display: flex;
      flex-direction: column;
    }
    .stat-label {
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      font-weight: 600;
      margin-bottom: 0.25rem;
    }
    .stat-value {
      font-size: 1.75rem;
      font-weight: 800;
      line-height: 1.2;
    }
    .stat-desc {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 0.25rem;
    }

    /* Filter Panel */
    .filter-panel {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 1.25rem;
      margin-bottom: 1.5rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }
    .search-row {
      display: flex;
      gap: 0.75rem;
      align-items: center;
      flex-wrap: wrap;
    }
    .search-input-wrap {
      flex: 1;
      min-width: 260px;
      position: relative;
    }
    .search-input {
      width: 100%;
      background: var(--bg-input);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 0.6rem 0.85rem 0.6rem 2.25rem;
      border-radius: var(--radius);
      font-size: 0.9rem;
      outline: none;
    }
    .search-input:focus { border-color: var(--border-focus); box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2); }
    .search-icon {
      position: absolute;
      left: 0.75rem;
      top: 50%;
      transform: translateY(-50%);
      color: var(--text-muted);
      pointer-events: none;
    }

    /* Filter Controls Grid */
    .filters-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 1rem;
      padding-top: 0.5rem;
      border-top: 1px solid var(--border);
    }
    .filter-group {
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      min-width: 0;
    }
    .filter-group label {
      font-size: 0.75rem;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .filter-select, .filter-input {
      background: var(--bg-input);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 0.45rem 0.65rem;
      border-radius: var(--radius);
      font-size: 0.85rem;
      outline: none;
      width: 100%;
      box-sizing: border-box;
    }
    .filter-select:focus, .filter-input:focus { border-color: var(--border-focus); }

    /* Custom Date Filter Component */
    .date-filter-group {
      min-width: 0;
    }
    .date-header-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.5rem;
    }
    .date-field-select {
      background: var(--bg-input);
      border: 1px solid var(--border);
      color: var(--accent);
      padding: 0.15rem 0.45rem;
      border-radius: var(--radius);
      font-size: 0.75rem;
      font-weight: 600;
      outline: none;
      cursor: pointer;
    }
    .date-field-select:focus { border-color: var(--border-focus); }
    .date-inputs-row {
      display: flex;
      gap: 0.35rem;
      align-items: center;
      width: 100%;
    }
    .date-picker-input {
      flex: 1;
      min-width: 0;
      width: 100%;
      font-size: 0.78rem;
      padding: 0.35rem 0.4rem;
    }
    .date-sep {
      font-size: 0.75rem;
      color: var(--text-muted);
      flex-shrink: 0;
    }

    /* Date Preset Pills */
    .chips-group {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
    }
    .chip {
      background: var(--badge-bg);
      border: 1px solid var(--border);
      color: var(--text-muted);
      padding: 0.25rem 0.65rem;
      border-radius: 9999px;
      font-size: 0.75rem;
      cursor: pointer;
      user-select: none;
      transition: all 0.15s ease;
    }
    .chip:hover { color: var(--text); border-color: var(--border-focus); }
    .chip.active {
      background: var(--accent);
      color: #0f172a;
      border-color: var(--accent);
      font-weight: 700;
    }

    /* Active Filters Bar */
    .active-filters-bar {
      display: flex;
      align-items: center;
      gap: 0.5rem;
      flex-wrap: wrap;
      font-size: 0.8rem;
      padding-top: 0.5rem;
    }
    .tag-badge {
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      background: rgba(56, 189, 248, 0.15);
      border: 1px solid rgba(56, 189, 248, 0.3);
      color: var(--accent);
      padding: 0.2rem 0.5rem;
      border-radius: var(--radius);
      font-size: 0.75rem;
    }
    .tag-badge button {
      background: none;
      border: none;
      color: inherit;
      cursor: pointer;
      font-size: 0.85rem;
      display: flex;
      align-items: center;
    }

    /* View Switcher & Counter Bar */
    .controls-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1rem;
      flex-wrap: wrap;
      gap: 0.75rem;
    }
    .results-count {
      font-size: 0.9rem;
      color: var(--text-muted);
    }
    .results-count strong { color: var(--text); }
    .view-actions {
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    /* Data Table */
    .table-card {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      overflow: hidden;
      margin-bottom: 2rem;
    }
    .table-container {
      width: 100%;
      overflow-x: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.85rem;
    }
    thead {
      background: var(--bg-card);
      border-bottom: 1px solid var(--border);
    }
    th {
      padding: 0.75rem 1rem;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      font-weight: 600;
      white-space: nowrap;
      user-select: none;
    }
    th.sortable { cursor: pointer; }
    th.sortable:hover { color: var(--text); }
    td {
      padding: 0.75rem 1rem;
      border-bottom: 1px solid var(--border);
      vertical-align: middle;
    }
    tr:last-child td { border-bottom: none; }
    tbody tr:hover { background: rgba(255, 255, 255, 0.02); }
    tr.selected { background: rgba(56, 189, 248, 0.08) !important; }

    /* Score Badges */
    .score-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 0.75rem;
      padding: 0.2rem 0.55rem;
      border-radius: 9999px;
      min-width: 36px;
    }
    .score-high { background: rgba(16, 185, 129, 0.2); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.4); }
    .score-med { background: rgba(245, 158, 11, 0.2); color: var(--warning); border: 1px solid rgba(245, 158, 11, 0.4); }
    .score-low { background: rgba(148, 163, 184, 0.2); color: var(--text-muted); border: 1px solid var(--border); }

    /* Portal Badge */
    .portal-badge {
      display: inline-block;
      font-size: 0.7rem;
      padding: 0.15rem 0.45rem;
      border-radius: var(--radius);
      background: var(--badge-bg);
      color: var(--text-muted);
      border: 1px solid var(--border);
      text-transform: uppercase;
      font-weight: 600;
    }

    /* Strengths & Gaps Pills */
    .strengths-gaps {
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
      max-width: 380px;
      font-size: 0.75rem;
    }
    .strength-item {
      color: #6ee7b7;
      display: flex;
      align-items: flex-start;
      gap: 0.3rem;
    }
    .gap-item {
      color: #fca5a5;
      display: flex;
      align-items: flex-start;
      gap: 0.3rem;
    }

    /* Card View */
    .cards-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
      gap: 1.25rem;
      margin-bottom: 2rem;
    }
    .job-card {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 1.25rem;
      display: flex;
      flex-direction: column;
      gap: 0.85rem;
      position: relative;
      transition: transform 0.15s ease, border-color 0.15s ease;
    }
    .job-card:hover {
      border-color: var(--border-focus);
      transform: translateY(-2px);
    }
    .job-card.selected {
      border-color: var(--accent);
      background: rgba(56, 189, 248, 0.05);
    }
    .job-card-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 0.75rem;
    }
    .card-title {
      font-size: 1.05rem;
      font-weight: 700;
      color: var(--text);
      line-height: 1.3;
    }
    .card-company {
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--accent);
      margin-top: 0.15rem;
    }
    .card-meta-row {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      align-items: center;
      font-size: 0.75rem;
      color: var(--text-muted);
    }

    /* Floating Bulk Bar */
    .bulk-bar {
      position: fixed;
      bottom: 1.5rem;
      left: 50%;
      transform: translateX(-50%) translateY(120px);
      background: var(--bg-surface);
      border: 1px solid var(--accent);
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5), 0 0 15px rgba(56, 189, 248, 0.3);
      border-radius: 9999px;
      padding: 0.75rem 1.5rem;
      display: flex;
      align-items: center;
      gap: 1rem;
      z-index: 50;
      transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .bulk-bar.visible {
      transform: translateX(-50%) translateY(0);
    }
    .bulk-count {
      font-weight: 700;
      font-size: 0.9rem;
    }

    /* Modals */
    .modal-overlay {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(0, 0, 0, 0.7);
      backdrop-filter: blur(4px);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 100;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.2s ease;
      padding: 1rem;
    }
    .modal-overlay.open {
      opacity: 1;
      pointer-events: auto;
    }
    .modal {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      width: 100%;
      max-width: 580px;
      max-height: 90vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
    }
    .modal-header {
      padding: 1.25rem 1.5rem;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .modal-header h3 { font-size: 1.15rem; font-weight: 700; }
    .modal-close {
      background: none;
      border: none;
      color: var(--text-muted);
      cursor: pointer;
      font-size: 1.25rem;
    }
    .modal-body {
      padding: 1.5rem;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 1.25rem;
    }
    .modal-footer {
      padding: 1rem 1.5rem;
      border-top: 1px solid var(--border);
      display: flex;
      justify-content: flex-end;
      gap: 0.75rem;
      background: var(--bg-card);
    }

    /* Modal Tabs */
    .tabs-nav {
      display: flex;
      border-bottom: 1px solid var(--border);
      gap: 0.5rem;
    }
    .tab-btn {
      background: none;
      border: none;
      color: var(--text-muted);
      padding: 0.6rem 0.85rem;
      font-size: 0.85rem;
      font-weight: 600;
      cursor: pointer;
      border-bottom: 2px solid transparent;
      margin-bottom: -1px;
    }
    .tab-btn.active {
      color: var(--accent);
      border-bottom-color: var(--accent);
    }
    .tab-pane { display: none; }
    .tab-pane.active { display: flex; flex-direction: column; gap: 1rem; }

    /* Toast Notification */
    .toast-container {
      position: fixed;
      top: 5rem;
      right: 1.5rem;
      z-index: 110;
      display: flex;
      flex-direction: column;
      gap: 0.5rem;
      pointer-events: none;
    }
    .toast {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      padding: 0.75rem 1.25rem;
      border-radius: var(--radius);
      box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
      display: flex;
      align-items: center;
      gap: 0.75rem;
      font-size: 0.85rem;
      pointer-events: auto;
      animation: slideIn 0.2s ease;
      max-width: 420px;
    }
    .toast-success { border-color: var(--success); }
    .toast-danger { border-color: var(--danger); }
    @keyframes slideIn {
      from { transform: translateX(100%); opacity: 0; }
      to { transform: translateX(0); opacity: 1; }
    }

    /* Utilities */
    .truncate {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .link-icon {
      color: var(--accent);
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 0.2rem;
    }
    .link-icon:hover { text-decoration: underline; }
    .empty-state {
      text-align: center;
      padding: 3rem 1.5rem;
      color: var(--text-muted);
    }
  </style>
</head>
<body data-theme="dark">

  <!-- Header -->
  <header>
    <div class="brand">
      <div class="brand-icon">&#x26A1;</div>
      <div>
        <h1>Seen Jobs Explorer</h1>
        <div class="brand-sub">Real-Time Search, Filtering & State Management</div>
      </div>
    </div>
    <div class="header-actions">
      <div class="live-pill" id="livePill" title="Watching job_scraper/seen_jobs.json">
        <span class="pulse-dot"></span>
        <span id="liveText">Live Synced</span>
      </div>
      <button class="btn btn-sm" id="btnRefresh" title="Force Refresh">&#x21BB; Refresh</button>
      <button class="btn btn-sm" id="btnRestore" title="Restore previous state">&#x21BA; Undo / Restore</button>
      <button class="btn btn-sm btn-danger" id="btnOpenDeleteModal">&#x1F5D1; Delete Options</button>
      <button class="btn btn-sm" id="btnExportStatic" title="Export as static HTML">&#x1F4BE; Export</button>
      <button class="btn btn-sm" id="btnToggleTheme" title="Toggle Theme">&#x2600;</button>
    </div>
  </header>

  <div class="container">
    <!-- Top Stats Banner -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-label">Total Jobs</div>
        <div class="stat-value" id="statTotal">0</div>
        <div class="stat-desc" id="statTotalDesc">in seen_jobs.json</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Seen Today</div>
        <div class="stat-value" style="color: var(--accent)" id="statToday">0</div>
        <div class="stat-desc">discovered on today's date</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Strong Fits</div>
        <div class="stat-value" style="color: var(--success)" id="statStrongFit">0</div>
        <div class="stat-desc">score &ge; 75 / 100</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Average Score</div>
        <div class="stat-value" id="statAvgScore">0</div>
        <div class="stat-desc">across ranked jobs</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Active Portals</div>
        <div class="stat-value" id="statPortals">0</div>
        <div class="stat-desc" id="statPortalsList">LinkedIn, Freehire</div>
      </div>
    </div>

    <!-- Filter Control Panel -->
    <div class="filter-panel">
      <!-- Search Input Row -->
      <div class="search-row">
        <div class="search-input-wrap">
          <span class="search-icon">&#x1F50D;</span>
          <input type="text" id="searchInput" class="search-input" placeholder="Search by title, company, skills, strengths, gaps, or location...">
        </div>
        <div class="chips-group" id="datePresetChips">
          <span class="chip active" data-preset="all">All Dates</span>
          <span class="chip" data-preset="today">Today</span>
          <span class="chip" data-preset="yesterday">Yesterday</span>
          <span class="chip" data-preset="3days">Past 3 Days</span>
          <span class="chip" data-preset="7days">Past 7 Days</span>
          <span class="chip" data-preset="30days">Past 30 Days</span>
        </div>
      </div>

      <!-- Advanced Filters Grid -->
      <div class="filters-grid">
        <!-- Company Filter -->
        <div class="filter-group">
          <label>Company</label>
          <select id="companySelect" class="filter-select">
            <option value="">All Companies</option>
          </select>
        </div>

        <!-- Portal Filter -->
        <div class="filter-group">
          <label>Portal / Source</label>
          <select id="portalSelect" class="filter-select">
            <option value="">All Portals</option>
          </select>
        </div>

        <!-- Fit / Score Filter -->
        <div class="filter-group">
          <label>Fit Level</label>
          <select id="fitSelect" class="filter-select">
            <option value="">All Fits</option>
            <option value="Strong Fit">Strong Fit (&ge;75)</option>
            <option value="Good Fit">Good Fit (60-74)</option>
            <option value="Moderate Fit">Moderate Fit (45-59)</option>
            <option value="high">High Fit</option>
            <option value="medium">Medium Fit</option>
          </select>
        </div>

        <!-- Status Filter -->
        <div class="filter-group">
          <label>Status</label>
          <select id="statusSelect" class="filter-select">
            <option value="">All Statuses</option>
            <option value="ranked">Ranked</option>
            <option value="new">New</option>
            <option value="skipped">Skipped</option>
          </select>
        </div>

        <!-- Date Range: From / To -->
        <div class="filter-group date-filter-group">
          <div class="date-header-row">
            <label>Custom Date Filter</label>
            <select id="dateFieldSelect" class="date-field-select" title="Target date field">
              <option value="first_seen">First Seen</option>
              <option value="posted_date">Posted</option>
            </select>
          </div>
          <div class="date-inputs-row">
            <input type="date" id="dateFrom" class="filter-input date-picker-input" title="From Date">
            <span class="date-sep">&rarr;</span>
            <input type="date" id="dateTo" class="filter-input date-picker-input" title="To Date">
          </div>
        </div>

        <!-- Minimum Score Slider -->
        <div class="filter-group">
          <div style="display: flex; justify-content: space-between;">
            <label>Min Score</label>
            <span id="scoreVal" style="font-size: 0.75rem; font-weight: 700; color: var(--accent);">0</span>
          </div>
          <input type="range" id="scoreRange" min="0" max="100" value="0" style="accent-color: var(--accent); margin-top: 0.4rem;">
        </div>
      </div>

      <!-- Active Filters Display -->
      <div class="active-filters-bar" id="activeFiltersBar">
        <span style="color: var(--text-muted); font-size: 0.75rem;">Active filters:</span>
        <span id="activeFilterTags"></span>
        <button class="btn btn-sm" id="btnClearAllFilters" style="padding: 0.15rem 0.45rem; font-size: 0.7rem;">Clear All</button>
      </div>
    </div>

    <!-- Controls Bar: View mode, Sort, Result count -->
    <div class="controls-bar">
      <div class="results-count">
        Showing <strong id="visibleCount">0</strong> of <strong id="totalCount">0</strong> jobs
      </div>
      <div class="view-actions">
        <label style="font-size: 0.75rem; color: var(--text-muted);">Sort by:</label>
        <select id="sortSelect" class="filter-select">
          <option value="date_desc">Posted Date (Newest first)</option>
          <option value="date_asc">Posted Date (Oldest first)</option>
          <option value="first_seen_desc">First Seen (Newest first)</option>
          <option value="score_desc">Fit Score (Highest first)</option>
          <option value="score_asc">Fit Score (Lowest first)</option>
          <option value="company_asc">Company (A &rarr; Z)</option>
          <option value="title_asc">Job Title (A &rarr; Z)</option>
        </select>
        <button class="btn btn-sm" id="btnToggleView">&#x229E; Switch View</button>
      </div>
    </div>

    <!-- Table View -->
    <div class="table-card" id="tableView">
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th style="width: 38px;">
                <input type="checkbox" id="selectAllCheckbox" title="Select all filtered jobs">
              </th>
              <th>Score</th>
              <th>Job Title & Company</th>
              <th>Portal</th>
              <th>Location</th>
              <th>Posted Date</th>
              <th>First Seen</th>
              <th>Status</th>
              <th>Strengths & Gaps</th>
              <th style="text-align: right;">Action</th>
            </tr>
          </thead>
          <tbody id="jobsTableBody">
            <!-- Rendered dynamically -->
          </tbody>
        </table>
      </div>
    </div>

    <!-- Card View (Hidden by default, toggled via Switch View) -->
    <div class="cards-grid" id="cardsView" style="display: none;">
      <!-- Rendered dynamically -->
    </div>

    <!-- Empty State -->
    <div class="empty-state" id="emptyState" style="display: none;">
      <h3>No jobs match your active filters</h3>
      <p style="margin-top: 0.5rem;">Try adjusting your date range, search query, or score threshold.</p>
      <button class="btn btn-primary" id="btnResetFilters" style="margin-top: 1rem;">Reset All Filters</button>
    </div>
  </div>

  <!-- Floating Bulk Actions Bar -->
  <div class="bulk-bar" id="bulkBar">
    <div class="bulk-count"><span id="selectedCount">0</span> selected</div>
    <button class="btn btn-sm" id="btnSelectAllFiltered">Select All Filtered</button>
    <button class="btn btn-sm" id="btnClearSelection">Clear</button>
    <button class="btn btn-sm btn-danger" id="btnDeleteSelected">&#x1F5D1; Delete Selected</button>
    <button class="btn btn-sm" id="btnExportSelected">&#x1F4E5; Export JSON</button>
  </div>

  <!-- Advanced Deletion Modal -->
  <div class="modal-overlay" id="deleteModalOverlay">
    <div class="modal">
      <div class="modal-header">
        <h3>Delete Jobs from seen_jobs.json</h3>
        <button class="modal-close" id="btnCloseDeleteModal">&times;</button>
      </div>
      <div class="modal-body">
        <div class="tabs-nav">
          <button class="tab-btn active" data-tab="tabSelected">Selected (<span id="tabSelectedCount">0</span>)</button>
          <button class="tab-btn" data-tab="tabByDate">By Date</button>
          <button class="tab-btn" data-tab="tabMaxCap">By Max Cap</button>
          <button class="tab-btn" data-tab="tabFiltered">All Filtered (<span id="tabFilteredCount">0</span>)</button>
        </div>

        <!-- Tab 1: Delete Selected -->
        <div class="tab-pane active" id="tabSelected">
          <p style="font-size: 0.85rem; color: var(--text-muted);">
            Delete the jobs you explicitly selected via checkboxes. An automatic backup will be preserved.
          </p>
          <div id="selectedPreviewList" style="max-height: 180px; overflow-y: auto; background: var(--bg-card); padding: 0.75rem; border-radius: var(--radius); font-size: 0.8rem;">
            No items selected.
          </div>
          <button class="btn btn-danger" id="btnConfirmDeleteSelected" style="align-self: flex-start;">Confirm Delete Selected</button>
        </div>

        <!-- Tab 2: Delete By Date -->
        <div class="tab-pane" id="tabByDate">
          <p style="font-size: 0.85rem; color: var(--text-muted);">
            Delete jobs older than a certain age or posted before a specific date.
          </p>
          <div style="display: flex; flex-direction: column; gap: 0.75rem;">
            <label style="font-size: 0.8rem; font-weight: 600;">Option A: Delete older than N days</label>
            <div style="display: flex; gap: 0.5rem; align-items: center;">
              <span>Older than</span>
              <input type="number" id="deleteOlderDaysInput" class="filter-input" value="30" min="1" style="width: 80px;">
              <span>days</span>
              <button class="btn btn-danger btn-sm" id="btnDeleteOlderThan">Delete Older</button>
            </div>

            <hr style="border: 0; border-top: 1px solid var(--border); margin: 0.5rem 0;">

            <label style="font-size: 0.8rem; font-weight: 600;">Option B: Delete before specific date</label>
            <div style="display: flex; gap: 0.5rem; align-items: center;">
              <select id="deleteDateTargetField" class="filter-select">
                <option value="first_seen">First Seen</option>
                <option value="posted_date">Posted Date</option>
              </select>
              <span>before</span>
              <input type="date" id="deleteBeforeDateInput" class="filter-input">
              <button class="btn btn-danger btn-sm" id="btnDeleteBeforeDate">Delete Before</button>
            </div>
          </div>
        </div>

        <!-- Tab 3: Delete By Max Cap -->
        <div class="tab-pane" id="tabMaxCap">
          <p style="font-size: 0.85rem; color: var(--text-muted);">
            Keep only the newest N jobs in your history and prune all older records to keep seen_jobs.json lightweight.
          </p>
          <div style="display: flex; gap: 0.5rem; align-items: center;">
            <span>Keep newest</span>
            <input type="number" id="keepMaxCountInput" class="filter-input" value="100" min="10" style="width: 90px;">
            <span>jobs</span>
            <button class="btn btn-danger btn-sm" id="btnApplyMaxCap">Prune Remainder</button>
          </div>
        </div>

        <!-- Tab 4: Delete Filtered -->
        <div class="tab-pane" id="tabFiltered">
          <p style="font-size: 0.85rem; color: var(--text-muted);">
            Delete all jobs currently matching your active filter criteria (e.g. wipe all low scores, or wipe a specific company or date).
          </p>
          <div style="background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); padding: 0.75rem; border-radius: var(--radius); font-size: 0.85rem;">
            This will permanently remove <strong><span id="filteredDeleteCountDisplay">0</span></strong> matching jobs from seen_jobs.json (a backup will be made).
          </div>
          <button class="btn btn-danger" id="btnConfirmDeleteFiltered" style="align-self: flex-start;">Confirm Delete All Matching</button>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn" id="btnDismissDeleteModal">Close</button>
      </div>
    </div>
  </div>

  <!-- Toast Container -->
  <div class="toast-container" id="toastContainer"></div>

  <script>
    // Embedded Data Placeholder for offline export mode:
    // __EMBEDDED_DATA_PLACEHOLDER__

    // State Management
    let allJobs = [];
    let visibleJobs = [];
    let selectedKeys = new Set();
    let currentMtime = 0;
    let currentSignature = "";
    let isOffline = false;
    let currentViewMode = "table"; // 'table' or 'cards'

    const state = {
      search: "",
      datePreset: "all",
      company: "",
      portal: "",
      fit: "",
      status: "",
      dateField: "first_seen",
      dateFrom: "",
      dateTo: "",
      minScore: 0,
      sortBy: "date_desc",
    };

    // DOM Elements
    const jobsTableBody = document.getElementById("jobsTableBody");
    const cardsView = document.getElementById("cardsView");
    const tableView = document.getElementById("tableView");
    const emptyState = document.getElementById("emptyState");
    const selectAllCheckbox = document.getElementById("selectAllCheckbox");
    const bulkBar = document.getElementById("bulkBar");
    const selectedCountSpan = document.getElementById("selectedCount");
    const livePill = document.getElementById("livePill");
    const liveText = document.getElementById("liveText");

    // Initialize
    async function init() {
      setupEventListeners();
      setupTheme();

      if (window.EMBEDDED_SEEN_DATA) {
        // Offline standalone export mode
        isOffline = true;
        livePill.style.display = "none";
        document.getElementById("btnRestore").style.display = "none";
        document.getElementById("btnRefresh").style.display = "none";
        document.getElementById("btnOpenDeleteModal").style.display = "none";
        loadPayload(window.EMBEDDED_SEEN_DATA);
      } else {
        // Connected live server mode
        await fetchJobs();
        startLiveSync();
      }
    }

    function setupTheme() {
      const saved = localStorage.getItem("seen_jobs_theme") || "dark";
      document.body.setAttribute("data-theme", saved);
      document.getElementById("btnToggleTheme").innerHTML = saved === "dark" ? "&#x2600;" : "&#x1F319;";
    }

    function toggleTheme() {
      const cur = document.body.getAttribute("data-theme") || "dark";
      const next = cur === "dark" ? "light" : "dark";
      document.body.setAttribute("data-theme", next);
      localStorage.setItem("seen_jobs_theme", next);
      document.getElementById("btnToggleTheme").innerHTML = next === "dark" ? "&#x2600;" : "&#x1F319;";
    }

    // Fetch jobs from server
    async function fetchJobs() {
      try {
        const resp = await fetch("/api/jobs?ts=" + Date.now(), { cache: "no-store" });
        if (!resp.ok) throw new Error("Failed to load jobs");
        const data = await resp.json();
        currentMtime = data.mtime || 0;
        currentSignature = data.signature || "";
        loadPayload(data);
      } catch (err) {
        console.error("fetchJobs error:", err);
        showToast("Error loading jobs: " + err.message, "danger");
      }
    }

    function loadPayload(data) {
      const seenDict = data.seen || {};
      allJobs = Object.entries(seenDict).map(([key, item]) => ({
        key,
        title: item.title || "Untitled",
        company: item.company || "Unknown Company",
        url: item.url || "#",
        location: item.location || "",
        portal: item.portal || "unknown",
        posted_date: item.posted_date || "",
        first_seen: item.first_seen || "",
        status: item.status || "new",
        fit: item.fit || "",
        rank_score: typeof item.rank_score === "number" ? item.rank_score : null,
        rank_verdict: item.rank_verdict || "",
        strengths: Array.isArray(item.strengths) ? item.strengths : [],
        gaps: Array.isArray(item.gaps) ? item.gaps : [],
        raw: item,
      }));

      populateDropdowns();
      updateStats();
      applyFiltersAndRender();
    }

    // Live background polling
    function startLiveSync() {
      setInterval(async () => {
        if (isOffline) return;
        try {
          const resp = await fetch("/api/status?ts=" + Date.now(), { cache: "no-store" });
          if (!resp.ok) return;
          const status = await resp.json();
          const changed = status.signature
            ? status.signature !== currentSignature
            : status.mtime !== currentMtime;
          if (changed) {
            currentMtime = status.mtime || 0;
            currentSignature = status.signature || "";
            await fetchJobs();
            showToast("Detected new jobs on disk. Refreshed view!", "success");
          }
        } catch (e) {
          // Silent catch on network blip
        }
      }, 3000);
    }

    // Populate Company & Portal selects
    function populateDropdowns() {
      const compSelect = document.getElementById("companySelect");
      const currentComp = state.company;
      const companies = [...new Set(allJobs.map(j => j.company).filter(Boolean))].sort();
      compSelect.innerHTML = '<option value="">All Companies (' + companies.length + ')</option>';
      companies.forEach(c => {
        const count = allJobs.filter(j => j.company === c).length;
        const opt = document.createElement("option");
        opt.value = c;
        opt.textContent = `${c} (${count})`;
        if (c === currentComp) opt.selected = true;
        compSelect.appendChild(opt);
      });

      const portSelect = document.getElementById("portalSelect");
      const currentPort = state.portal;
      const portals = [...new Set(allJobs.map(j => j.portal).filter(Boolean))].sort();
      portSelect.innerHTML = '<option value="">All Portals (' + portals.length + ')</option>';
      portals.forEach(p => {
        const count = allJobs.filter(j => j.portal === p).length;
        const opt = document.createElement("option");
        opt.value = p;
        opt.textContent = `${p} (${count})`;
        if (p === currentPort) opt.selected = true;
        portSelect.appendChild(opt);
      });
    }

    // Update Top Metric Cards
    function updateStats() {
      document.getElementById("statTotal").textContent = allJobs.length;
      document.getElementById("totalCount").textContent = allJobs.length;

      const today = new Date();
      const todayStr = [
        today.getFullYear(),
        String(today.getMonth() + 1).padStart(2, "0"),
        String(today.getDate()).padStart(2, "0"),
      ].join("-");
      const seenToday = allJobs.filter(j => j.first_seen === todayStr).length;
      document.getElementById("statToday").textContent = seenToday;

      const strongFits = allJobs.filter(j => (j.rank_score && j.rank_score >= 75) || j.rank_verdict === "Strong Fit").length;
      document.getElementById("statStrongFit").textContent = strongFits;

      const rankedJobs = allJobs.filter(j => typeof j.rank_score === "number");
      if (rankedJobs.length > 0) {
        const avg = Math.round(rankedJobs.reduce((acc, j) => acc + j.rank_score, 0) / rankedJobs.length);
        document.getElementById("statAvgScore").textContent = avg + "%";
      } else {
        document.getElementById("statAvgScore").textContent = "N/A";
      }

      const portals = [...new Set(allJobs.map(j => j.portal).filter(Boolean))];
      document.getElementById("statPortals").textContent = portals.length;
      document.getElementById("statPortalsList").textContent = portals.slice(0, 3).join(", ") || "None";
    }

    // Filter & Sort Logic
    function applyFiltersAndRender() {
      const today = new Date();
      const todayStr = [
        today.getFullYear(),
        String(today.getMonth() + 1).padStart(2, "0"),
        String(today.getDate()).padStart(2, "0"),
      ].join("-");

      visibleJobs = allJobs.filter(job => {
        // Global text search
        if (state.search) {
          const q = state.search.toLowerCase();
          const matchTitle = job.title.toLowerCase().includes(q);
          const matchCompany = job.company.toLowerCase().includes(q);
          const matchLoc = job.location.toLowerCase().includes(q);
          const matchStrengths = job.strengths.some(s => s.toLowerCase().includes(q));
          const matchGaps = job.gaps.some(g => g.toLowerCase().includes(q));
          if (!matchTitle && !matchCompany && !matchLoc && !matchStrengths && !matchGaps) {
            return false;
          }
        }

        // Company
        if (state.company && job.company !== state.company) return false;

        // Portal
        if (state.portal && job.portal !== state.portal) return false;

        // Status
        if (state.status && job.status !== state.status) return false;

        // Fit
        if (state.fit) {
          if (state.fit === "high" || state.fit === "medium") {
            if (job.fit !== state.fit) return false;
          } else {
            if (job.rank_verdict !== state.fit) return false;
          }
        }

        // Min Score
        if (state.minScore > 0) {
          if (!job.rank_score || job.rank_score < state.minScore) return false;
        }

        // Date Preset
        if (state.datePreset !== "all") {
          const checkDate = job.first_seen || job.posted_date;
          if (!checkDate) return false;
          const diffDays = Math.floor((new Date(todayStr) - new Date(checkDate)) / (86400000));
          if (state.datePreset === "today" && checkDate !== todayStr) return false;
          if (state.datePreset === "yesterday" && diffDays !== 1) return false;
          if (state.datePreset === "3days" && (diffDays < 0 || diffDays > 3)) return false;
          if (state.datePreset === "7days" && (diffDays < 0 || diffDays > 7)) return false;
          if (state.datePreset === "30days" && (diffDays < 0 || diffDays > 30)) return false;
        }

        // Custom Date Range
        const targetDate = state.dateField === "first_seen" ? job.first_seen : job.posted_date;
        if (state.dateFrom && targetDate && targetDate < state.dateFrom) return false;
        if (state.dateTo && targetDate && targetDate > state.dateTo) return false;

        return true;
      });

      // Sorting
      visibleJobs.sort((a, b) => {
        if (state.sortBy === "date_desc") return (b.posted_date || "").localeCompare(a.posted_date || "");
        if (state.sortBy === "date_asc") return (a.posted_date || "").localeCompare(b.posted_date || "");
        if (state.sortBy === "first_seen_desc") return (b.first_seen || "").localeCompare(a.first_seen || "");
        if (state.sortBy === "score_desc") return (b.rank_score || 0) - (a.rank_score || 0);
        if (state.sortBy === "score_asc") return (a.rank_score || 0) - (b.rank_score || 0);
        if (state.sortBy === "company_asc") return a.company.localeCompare(b.company);
        if (state.sortBy === "title_asc") return a.title.localeCompare(b.title);
        return 0;
      });

      // Update counters
      document.getElementById("visibleCount").textContent = visibleJobs.length;
      document.getElementById("tabFilteredCount").textContent = visibleJobs.length;
      document.getElementById("filteredDeleteCountDisplay").textContent = visibleJobs.length;

      renderActiveFilters();
      renderJobs();
      updateBulkBar();
    }

    // Render Active Filter Chips
    function renderActiveFilters() {
      const container = document.getElementById("activeFilterTags");
      container.innerHTML = "";
      const badges = [];

      if (state.search) badges.push({ label: `Search: "${state.search}"`, clear: () => { state.search = ""; document.getElementById("searchInput").value = ""; } });
      if (state.datePreset !== "all") badges.push({ label: `Date: ${state.datePreset}`, clear: () => setDatePreset("all") });
      if (state.company) badges.push({ label: `Company: ${state.company}`, clear: () => { state.company = ""; document.getElementById("companySelect").value = ""; } });
      if (state.portal) badges.push({ label: `Portal: ${state.portal}`, clear: () => { state.portal = ""; document.getElementById("portalSelect").value = ""; } });
      if (state.fit) badges.push({ label: `Fit: ${state.fit}`, clear: () => { state.fit = ""; document.getElementById("fitSelect").value = ""; } });
      if (state.status) badges.push({ label: `Status: ${state.status}`, clear: () => { state.status = ""; document.getElementById("statusSelect").value = ""; } });
      if (state.minScore > 0) badges.push({ label: `Score &ge; ${state.minScore}`, clear: () => { state.minScore = 0; document.getElementById("scoreRange").value = 0; document.getElementById("scoreVal").textContent = "0"; } });
      if (state.dateFrom || state.dateTo) badges.push({ label: `${state.dateField}: ${state.dateFrom || 'start'} to ${state.dateTo || 'end'}`, clear: () => { state.dateFrom = ""; state.dateTo = ""; document.getElementById("dateFrom").value = ""; document.getElementById("dateTo").value = ""; } });

      badges.forEach(b => {
        const span = document.createElement("span");
        span.className = "tag-badge";
        span.innerHTML = `${b.label} <button>&times;</button>`;
        span.querySelector("button").onclick = () => { b.clear(); applyFiltersAndRender(); };
        container.appendChild(span);
      });
    }

    // Render Table and Cards
    function renderJobs() {
      if (visibleJobs.length === 0) {
        tableView.style.display = "none";
        cardsView.style.display = "none";
        emptyState.style.display = "block";
        return;
      }

      emptyState.style.display = "none";
      if (currentViewMode === "table") {
        tableView.style.display = "block";
        cardsView.style.display = "none";
        renderTable();
      } else {
        tableView.style.display = "none";
        cardsView.style.display = "grid";
        renderCards();
      }
    }

    function renderTable() {
      jobsTableBody.innerHTML = "";
      visibleJobs.forEach(job => {
        const isSelected = selectedKeys.has(job.key);
        const tr = document.createElement("tr");
        if (isSelected) tr.className = "selected";

        let scoreHtml = '<span class="score-badge score-low">N/A</span>';
        if (typeof job.rank_score === "number") {
          const cls = job.rank_score >= 75 ? "score-high" : job.rank_score >= 60 ? "score-med" : "score-low";
          scoreHtml = `<span class="score-badge ${cls}">${job.rank_score}%</span>`;
        }

        let strengthsHtml = "";
        if (job.strengths && job.strengths.length > 0) {
          strengthsHtml += `<div class="strength-item"><span>&#x2714;</span> <span>${escapeHtml(job.strengths[0])}</span></div>`;
        }
        if (job.gaps && job.gaps.length > 0) {
          strengthsHtml += `<div class="gap-item"><span>&#x26A0;</span> <span>${escapeHtml(job.gaps[0])}</span></div>`;
        }
        if (!strengthsHtml) strengthsHtml = '<span style="color: var(--text-muted); font-size: 0.75rem;">-</span>';

        tr.innerHTML = `
          <td>
            <input type="checkbox" class="job-checkbox" data-key="${job.key}" ${isSelected ? "checked" : ""}>
          </td>
          <td>${scoreHtml}</td>
          <td>
            <div style="font-weight: 700; color: var(--text); font-size: 0.9rem;">${escapeHtml(job.title)}</div>
            <div style="font-size: 0.8rem; color: var(--accent); font-weight: 500;">${escapeHtml(job.company)}</div>
          </td>
          <td><span class="portal-badge">${escapeHtml(job.portal)}</span></td>
          <td style="color: var(--text-muted); font-size: 0.8rem;">${escapeHtml(job.location || "Not specified")}</td>
          <td style="white-space: nowrap; font-size: 0.8rem;">${job.posted_date || "-"}</td>
          <td style="white-space: nowrap; font-size: 0.8rem;">${job.first_seen || "-"}</td>
          <td><span style="font-size: 0.75rem; text-transform: uppercase; font-weight: 600; color: var(--text-muted);">${escapeHtml(job.status)}</span></td>
          <td><div class="strengths-gaps">${strengthsHtml}</div></td>
          <td style="text-align: right; white-space: nowrap;">
            <a href="${job.url}" target="_blank" rel="noopener noreferrer" class="btn btn-sm btn-primary" title="Open Job Posting" style="margin-right: 0.35rem;">
              Link &#x2197;
            </a>
            ${!isOffline ? `<button class="btn btn-sm btn-danger btn-delete-one" data-key="${job.key}" title="Delete this job">&#x1F5D1;</button>` : ''}
          </td>
        `;

        const chk = tr.querySelector(".job-checkbox");
        chk.addEventListener("change", (e) => {
          toggleSelectKey(job.key, e.target.checked);
          tr.classList.toggle("selected", e.target.checked);
        });

        const btnDel = tr.querySelector(".btn-delete-one");
        if (btnDel) {
          btnDel.addEventListener("click", () => confirmDeleteSingle(job));
        }

        jobsTableBody.appendChild(tr);
      });

      updateSelectAllCheckboxState();
    }

    function renderCards() {
      cardsView.innerHTML = "";
      visibleJobs.forEach(job => {
        const isSelected = selectedKeys.has(job.key);
        const card = document.createElement("div");
        card.className = "job-card" + (isSelected ? " selected" : "");

        let scoreHtml = '<span class="score-badge score-low">N/A</span>';
        if (typeof job.rank_score === "number") {
          const cls = job.rank_score >= 75 ? "score-high" : job.rank_score >= 60 ? "score-med" : "score-low";
          scoreHtml = `<span class="score-badge ${cls}">${job.rank_score}% Score</span>`;
        }

        card.innerHTML = `
          <div class="job-card-header">
            <div>
              <div class="card-title">${escapeHtml(job.title)}</div>
              <div class="card-company">${escapeHtml(job.company)}</div>
            </div>
            <div>${scoreHtml}</div>
          </div>
          <div class="card-meta-row">
            <span class="portal-badge">${escapeHtml(job.portal)}</span>
            <span>&#x1F4CD; ${escapeHtml(job.location || "Remote/Unspecified")}</span>
            <span>&#x1F4C5; Posted: ${job.posted_date || "Unknown"}</span>
          </div>
          <div class="strengths-gaps" style="flex: 1;">
            ${(job.strengths || []).slice(0, 2).map(s => `<div class="strength-item"><span>&#x2714;</span> <span>${escapeHtml(s)}</span></div>`).join("")}
            ${(job.gaps || []).slice(0, 2).map(g => `<div class="gap-item"><span>&#x26A0;</span> <span>${escapeHtml(g)}</span></div>`).join("")}
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; padding-top: 0.5rem; border-top: 1px solid var(--border);">
            <label style="display: flex; align-items: center; gap: 0.4rem; font-size: 0.8rem; cursor: pointer;">
              <input type="checkbox" class="job-checkbox" data-key="${job.key}" ${isSelected ? "checked" : ""}>
              <span>Select</span>
            </label>
            <div style="display: flex; gap: 0.5rem;">
              <a href="${job.url}" target="_blank" rel="noopener noreferrer" class="btn btn-sm btn-primary">Open Posting &#x2197;</a>
              ${!isOffline ? `<button class="btn btn-sm btn-danger btn-delete-one" data-key="${job.key}">&#x1F5D1;</button>` : ''}
            </div>
          </div>
        `;

        const chk = card.querySelector(".job-checkbox");
        chk.addEventListener("change", (e) => {
          toggleSelectKey(job.key, e.target.checked);
          card.classList.toggle("selected", e.target.checked);
        });

        const btnDel = card.querySelector(".btn-delete-one");
        if (btnDel) {
          btnDel.addEventListener("click", () => confirmDeleteSingle(job));
        }

        cardsView.appendChild(card);
      });
    }

    // Selection Handling
    function toggleSelectKey(key, selected) {
      if (selected) selectedKeys.add(key);
      else selectedKeys.delete(key);
      updateBulkBar();
      updateSelectAllCheckboxState();
    }

    function updateSelectAllCheckboxState() {
      if (visibleJobs.length === 0) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
        return;
      }
      const visibleSelected = visibleJobs.filter(j => selectedKeys.has(j.key)).length;
      if (visibleSelected === 0) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
      } else if (visibleSelected === visibleJobs.length) {
        selectAllCheckbox.checked = true;
        selectAllCheckbox.indeterminate = false;
      } else {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = true;
      }
    }

    function updateBulkBar() {
      const count = selectedKeys.size;
      selectedCountSpan.textContent = count;
      document.getElementById("tabSelectedCount").textContent = count;
      if (count > 0) {
        bulkBar.classList.add("visible");
      } else {
        bulkBar.classList.remove("visible");
      }
      updateSelectedPreviewList();
    }

    function updateSelectedPreviewList() {
      const list = document.getElementById("selectedPreviewList");
      if (selectedKeys.size === 0) {
        list.innerHTML = "No items selected.";
        return;
      }
      const items = allJobs.filter(j => selectedKeys.has(j.key));
      list.innerHTML = items.map(j => `
        <div style="display: flex; justify-content: space-between; margin-bottom: 0.25rem;">
          <span class="truncate"><strong>${escapeHtml(j.company)}</strong> - ${escapeHtml(j.title)}</span>
          <span style="color: var(--text-muted); font-size: 0.75rem;">${j.posted_date}</span>
        </div>
      `).join("");
    }

    // Date Presets
    function setDatePreset(preset) {
      state.datePreset = preset;
      document.querySelectorAll("#datePresetChips .chip").forEach(c => {
        c.classList.toggle("active", c.getAttribute("data-preset") === preset);
      });
      applyFiltersAndRender();
    }

    // Event Listeners Setup
    function setupEventListeners() {
      // Search input debounce
      let searchTimeout;
      document.getElementById("searchInput").addEventListener("input", (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
          state.search = e.target.value.trim();
          applyFiltersAndRender();
        }, 200);
      });

      // Date Chips
      document.getElementById("datePresetChips").addEventListener("click", (e) => {
        const chip = e.target.closest(".chip");
        if (chip) {
          setDatePreset(chip.getAttribute("data-preset"));
        }
      });

      // Select Dropdowns
      document.getElementById("companySelect").addEventListener("change", (e) => {
        state.company = e.target.value;
        applyFiltersAndRender();
      });

      document.getElementById("portalSelect").addEventListener("change", (e) => {
        state.portal = e.target.value;
        applyFiltersAndRender();
      });

      document.getElementById("fitSelect").addEventListener("change", (e) => {
        state.fit = e.target.value;
        applyFiltersAndRender();
      });

      document.getElementById("statusSelect").addEventListener("change", (e) => {
        state.status = e.target.value;
        applyFiltersAndRender();
      });

      document.getElementById("dateFieldSelect").addEventListener("change", (e) => {
        state.dateField = e.target.value;
        applyFiltersAndRender();
      });

      document.getElementById("dateFrom").addEventListener("change", (e) => {
        state.dateFrom = e.target.value;
        applyFiltersAndRender();
      });

      document.getElementById("dateTo").addEventListener("change", (e) => {
        state.dateTo = e.target.value;
        applyFiltersAndRender();
      });

      // Score Slider
      const scoreRange = document.getElementById("scoreRange");
      const scoreVal = document.getElementById("scoreVal");
      scoreRange.addEventListener("input", (e) => {
        scoreVal.textContent = e.target.value;
        state.minScore = parseInt(e.target.value, 10);
        applyFiltersAndRender();
      });

      // Sort Select
      document.getElementById("sortSelect").addEventListener("change", (e) => {
        state.sortBy = e.target.value;
        applyFiltersAndRender();
      });

      // Clear all filters
      document.getElementById("btnClearAllFilters").addEventListener("click", resetAllFilters);
      document.getElementById("btnResetFilters").addEventListener("click", resetAllFilters);

      // View toggle
      document.getElementById("btnToggleView").addEventListener("click", () => {
        currentViewMode = currentViewMode === "table" ? "cards" : "table";
        renderJobs();
      });

      // Theme toggle
      document.getElementById("btnToggleTheme").addEventListener("click", toggleTheme);

      // Select All Checkbox
      selectAllCheckbox.addEventListener("change", (e) => {
        const check = e.target.checked;
        visibleJobs.forEach(j => {
          if (check) selectedKeys.add(j.key);
          else selectedKeys.delete(j.key);
        });
        renderJobs();
        updateBulkBar();
      });

      // Bulk Bar Buttons
      document.getElementById("btnSelectAllFiltered").addEventListener("click", () => {
        visibleJobs.forEach(j => selectedKeys.add(j.key));
        renderJobs();
        updateBulkBar();
      });

      document.getElementById("btnClearSelection").addEventListener("click", () => {
        selectedKeys.clear();
        renderJobs();
        updateBulkBar();
      });

      document.getElementById("btnDeleteSelected").addEventListener("click", () => {
        openDeleteModal("tabSelected");
      });

      document.getElementById("btnExportSelected").addEventListener("click", exportSelectedJSON);

      // Refresh Button
      document.getElementById("btnRefresh").addEventListener("click", async () => {
        await fetchJobs();
        showToast("Refreshed from seen_jobs.json", "success");
      });

      // Restore / Undo Button
      document.getElementById("btnRestore").addEventListener("click", restoreLatestBackup);

      // Static Export
      document.getElementById("btnExportStatic").addEventListener("click", exportStaticReport);

      // Deletion Modal
      document.getElementById("btnOpenDeleteModal").addEventListener("click", () => openDeleteModal());
      document.getElementById("btnCloseDeleteModal").addEventListener("click", closeDeleteModal);
      document.getElementById("btnDismissDeleteModal").addEventListener("click", closeDeleteModal);

      // Modal Tabs
      document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
          document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
          document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
          btn.classList.add("active");
          document.getElementById(btn.getAttribute("data-tab")).classList.add("active");
        });
      });

      // Deletion Action Handlers
      document.getElementById("btnConfirmDeleteSelected").addEventListener("click", executeDeleteSelected);
      document.getElementById("btnDeleteOlderThan").addEventListener("click", executeDeleteOlderThan);
      document.getElementById("btnDeleteBeforeDate").addEventListener("click", executeDeleteBeforeDate);
      document.getElementById("btnApplyMaxCap").addEventListener("click", executeApplyMaxCap);
      document.getElementById("btnConfirmDeleteFiltered").addEventListener("click", executeDeleteFiltered);
    }

    function resetAllFilters() {
      state.search = "";
      state.datePreset = "all";
      state.company = "";
      state.portal = "";
      state.fit = "";
      state.status = "";
      state.dateField = "first_seen";
      state.dateFrom = "";
      state.dateTo = "";
      state.minScore = 0;
      state.sortBy = "date_desc";

      document.getElementById("searchInput").value = "";
      document.getElementById("companySelect").value = "";
      document.getElementById("portalSelect").value = "";
      document.getElementById("fitSelect").value = "";
      document.getElementById("statusSelect").value = "";
      document.getElementById("dateFieldSelect").value = "first_seen";
      document.getElementById("dateFrom").value = "";
      document.getElementById("dateTo").value = "";
      document.getElementById("scoreRange").value = 0;
      document.getElementById("scoreVal").textContent = "0";
      document.getElementById("sortSelect").value = "date_desc";

      setDatePreset("all");
      applyFiltersAndRender();
    }

    // Modal Operations
    function openDeleteModal(activeTabId = "tabSelected") {
      document.getElementById("deleteModalOverlay").classList.add("open");
      document.querySelectorAll(".tab-btn").forEach(b => {
        b.classList.toggle("active", b.getAttribute("data-tab") === activeTabId);
      });
      document.querySelectorAll(".tab-pane").forEach(p => {
        p.classList.toggle("active", p.id === activeTabId);
      });
      updateBulkBar();
    }

    function closeDeleteModal() {
      document.getElementById("deleteModalOverlay").classList.remove("open");
    }

    // Deletion API Calls
    async function postDelete(payload) {
      if (isOffline) {
        showToast("Deletion is disabled in offline export mode.", "danger");
        return;
      }
      try {
        const resp = await fetch("/api/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const result = await resp.json();
        if (!resp.ok) throw new Error(result.error || "Failed to delete");

        closeDeleteModal();
        selectedKeys.clear();
        await fetchJobs();
        showToast(`Deleted ${result.deleted_count} jobs. Backup saved! Click 'Undo' if needed.`, "success");
      } catch (err) {
        console.error("Delete error:", err);
        showToast("Error deleting: " + err.message, "danger");
      }
    }

    async function executeDeleteSelected() {
      if (selectedKeys.size === 0) {
        alert("Please select at least one job first.");
        return;
      }
      if (!confirm(`Are you sure you want to delete ${selectedKeys.size} selected jobs? An automatic backup will be saved.`)) return;
      await postDelete({ action: "keys", keys: Array.from(selectedKeys) });
    }

    async function executeDeleteOlderThan() {
      const days = parseInt(document.getElementById("deleteOlderDaysInput").value, 10);
      if (isNaN(days) || days < 1) {
        alert("Please enter a valid number of days");
        return;
      }
      if (!confirm(`Are you sure you want to delete all jobs older than ${days} days?`)) return;
      await postDelete({ action: "older_than", days: days, date_field: "first_seen" });
    }

    async function executeDeleteBeforeDate() {
      const d = document.getElementById("deleteBeforeDateInput").value;
      const field = document.getElementById("deleteDateTargetField").value;
      if (!d) {
        alert("Please pick a target date.");
        return;
      }
      if (!confirm(`Are you sure you want to delete jobs where ${field} is before ${d}?`)) return;
      await postDelete({ action: "date", field: field, op: "before", target_date: d });
    }

    async function executeApplyMaxCap() {
      const keep = parseInt(document.getElementById("keepMaxCountInput").value, 10);
      if (isNaN(keep) || keep < 1) {
        alert("Please enter a valid number of jobs to keep.");
        return;
      }
      if (!confirm(`Keep newest ${keep} jobs and delete all remaining older jobs?`)) return;
      await postDelete({ action: "max_cap", keep_count: keep, sort_by: "first_seen" });
    }

    async function executeDeleteFiltered() {
      if (visibleJobs.length === 0) {
        alert("No jobs match current filters to delete.");
        return;
      }
      if (!confirm(`Are you sure you want to permanently delete all ${visibleJobs.length} currently filtered jobs?`)) return;
      const keys = visibleJobs.map(j => j.key);
      await postDelete({ action: "keys", keys });
    }

    async function confirmDeleteSingle(job) {
      if (!confirm(`Delete "${job.title}" at ${job.company}? An automatic backup will be made.`)) return;
      await postDelete({ action: "keys", keys: [job.key] });
    }

    // Restore Backup API Call
    async function restoreLatestBackup() {
      if (isOffline) return;
      if (!confirm("Restore seen_jobs.json from the most recent backup?")) return;
      try {
        const resp = await fetch("/api/restore", { method: "POST" });
        const res = await resp.json();
        if (!resp.ok) throw new Error(res.error || "Restore failed");
        selectedKeys.clear();
        await fetchJobs();
        showToast(`Restored ${res.restored_count} jobs from ${res.backup_file}!`, "success");
      } catch (err) {
        showToast("Restore failed: " + err.message, "danger");
      }
    }

    // Export Handlers
    function exportSelectedJSON() {
      const exportList = allJobs.filter(j => selectedKeys.has(j.key));
      const blob = new Blob([JSON.stringify(exportList.map(j => j.raw), null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `seen_jobs_selected_${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    }

    function exportStaticReport() {
      window.open("/api/export-html", "_blank");
    }

    // Toast Notifications
    function showToast(msg, type = "info") {
      const container = document.getElementById("toastContainer");
      const toast = document.createElement("div");
      toast.className = `toast toast-${type}`;
      toast.innerHTML = `<span>${msg}</span>`;
      container.appendChild(toast);
      setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => toast.remove(), 300);
      }, 4000);
    }

    // Utility: HTML Escaping
    function escapeHtml(str) {
      if (!str) return "";
      return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }

    // Start
    window.addEventListener("DOMContentLoaded", init);
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTTP Request Handler
# ---------------------------------------------------------------------------

class SeenJobsHTTPRequestHandler(BaseHTTPRequestHandler):
    state_file: Path = DEFAULT_STATE_FILE

    def log_message(self, format, *args):
        # Mute normal request logs to keep terminal clean unless error
        if args and str(args[1]) in ("404", "500"):
            super().log_message(format, *args)

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            body = FRONTEND_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/api/jobs":
            try:
                doc, seen = load_data(self.state_file)
                mtime = self.state_file.stat().st_mtime if self.state_file.exists() else 0
                self.send_json({
                    "seen": seen,
                    "count": len(seen),
                    "mtime": mtime,
                    "signature": file_signature(self.state_file),
                    "path": str(self.state_file),
                })
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return

        if path == "/api/status":
            try:
                mtime = self.state_file.stat().st_mtime if self.state_file.exists() else 0
                count = 0
                if self.state_file.exists():
                    doc, seen = load_data(self.state_file)
                    count = len(seen)
                self.send_json({
                    "mtime": mtime,
                    "signature": file_signature(self.state_file),
                    "count": count,
                })
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return

        if path == "/api/backups":
            try:
                backups = list_backups(self.state_file.parent)
                self.send_json({"backups": backups})
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return

        if path == "/api/export-html":
            try:
                doc, seen = load_data(self.state_file)
                embedded_json = json.dumps({"seen": seen}, ensure_ascii=False)
                script_injection = f"window.EMBEDDED_SEEN_DATA = {embedded_json};"
                html_out = FRONTEND_HTML.replace(
                    "// __EMBEDDED_DATA_PLACEHOLDER__",
                    script_injection
                )
                body = html_out.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="seen_jobs_dashboard.html"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return

        self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/delete":
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(content_len).decode("utf-8"))
                action = payload.get("action")

                doc, seen = load_data(self.state_file)
                # Create backup before mutation
                backup_path = create_backup(self.state_file)

                deleted_count = 0
                if action == "keys":
                    keys = payload.get("keys", [])
                    doc, deleted_count = delete_keys(doc, keys)
                elif action == "date":
                    field = payload.get("field", "first_seen")
                    op = payload.get("op", "before")
                    target_date = payload.get("target_date")
                    doc, deleted_count = delete_by_date(doc, field=field, op=op, target_date=target_date)
                elif action == "older_than":
                    days = int(payload.get("days", 30))
                    field = payload.get("date_field", "first_seen")
                    doc, deleted_count = delete_older_than(doc, days=days, field=field)
                elif action == "max_cap":
                    keep = int(payload.get("keep_count", 100))
                    sort_by = payload.get("sort_by", "first_seen")
                    doc, deleted_count = delete_max_cap(doc, keep_count=keep, sort_by=sort_by)
                else:
                    self.send_json({"error": f"Unknown deletion action: {action}"}, status=400)
                    return

                save_data(self.state_file, doc)
                self.send_json({
                    "success": True,
                    "deleted_count": deleted_count,
                    "remaining_count": len(doc.get("seen", {})),
                    "backup_file": backup_path.name if backup_path else None,
                })
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return

        if path == "/api/restore":
            try:
                restored_count, backup_name = restore_backup(self.state_file)
                self.send_json({
                    "success": True,
                    "restored_count": restored_count,
                    "backup_file": backup_name,
                })
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return

        self.send_error(404, "Not Found")


# ---------------------------------------------------------------------------
# CLI & Server Runner
# ---------------------------------------------------------------------------

def export_standalone_html(state_path: Path, output_path: Path) -> None:
    """Generate self-contained offline HTML file."""
    doc, seen = load_data(state_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    embedded_json = json.dumps({"seen": seen}, ensure_ascii=False)
    script_injection = f"window.EMBEDDED_SEEN_DATA = {embedded_json};"
    html_out = FRONTEND_HTML.replace("// __EMBEDDED_DATA_PLACEHOLDER__", script_injection)
    output_path.write_text(html_out, encoding="utf-8")
    print(f"Exported standalone HTML dashboard ({len(seen)} jobs) to:\n  file://{output_path.resolve()}")


def run_server(state_file: Path, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, auto_open: bool = True) -> None:
    """Start local web server and optionally open browser."""
    SeenJobsHTTPRequestHandler.state_file = state_file

    server = None
    actual_port = port
    # Try preferred port, or fall back to incrementing
    for p in range(port, port + 50):
        try:
            server = HTTPServer((host, p), SeenJobsHTTPRequestHandler)
            actual_port = p
            break
        except OSError:
            continue

    if not server:
        print(f"Error: Could not bind to {host}:{port} or subsequent 50 ports.", file=sys.stderr)
        sys.exit(1)

    url = f"http://{host}:{actual_port}"
    print("=" * 65)
    print("  Seen Jobs Explorer & Manager")
    print("=" * 65)
    print(f"  Live UI:        {url}")
    print(f"  Database File:  {state_file.resolve()}")
    print("  Controls:       Press Ctrl+C to stop server")
    print("=" * 65)

    if auto_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Seen Jobs server.")
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(
        description="Launch the interactive Seen Jobs Explorer web dashboard or export static HTML."
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help=f"Path to seen_jobs.json (default: {DEFAULT_STATE_FILE})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Server port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help=f"Server host binding (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open browser automatically",
    )
    parser.add_argument(
        "--export",
        type=Path,
        help="Export a standalone offline HTML dashboard file and exit",
    )

    args = parser.parse_args()

    if args.export:
        export_standalone_html(args.file, args.export)
        return

    run_server(args.file, host=args.host, port=args.port, auto_open=not args.no_open)


if __name__ == "__main__":
    main()
