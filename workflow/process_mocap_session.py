#!/usr/bin/env python3
"""
One-command mocap session processor.

Processes a raw Motive session directory (AVI videos + CSV) into pipeline-ready outputs:
  1. Concat AVI segments → single MP4 (watermark removed)
  2. CSV → skeleton_h36m.npy (17-joint H36M format)
  3. CSV → body_markers.npy (27 Plug-in Gait markers) + leg_markers.npy
  4. CSV → blade polygon editor HTML (for manual edge ordering)

Usage:
    # Process single session
    python process_mocap_session.py /Volumes/KINGSTON/P7_mocap/P7_1 -o /Volumes/FastACIS/csl_output/P7_1

    # Process all sessions under a parent directory
    python process_mocap_session.py /Volumes/KINGSTON/P7_mocap -o /Volumes/FastACIS/csl_output --batch

After running, open blade_editor_*.html in browser to define blade edge ordering,
then run extract_blade_gt.py to generate blade_edges.npy.
"""

import os
import sys
import re
import json
import csv
import argparse
import subprocess
import shutil
import glob
import tempfile
from pathlib import Path

# Add csl_pipeline paths for imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSL_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(CSL_ROOT, "scripts"))

import numpy as np
from motive_csv_utils import load_motive_csv, detect_skeleton_prefix
from csv2h36m import convert_csv_to_h36m, detect_amputation_mode
from extract_markers import extract_body_markers, extract_leg_markers

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

# Watermark cover region (bottom-left Motive frame counter)
# Generous box: 250x55 pixels from bottom-left
WM_X, WM_Y, WM_W, WM_H = 0, 1025, 250, 55


# ============================================================
# Step 1: AVI concat + watermark removal + MP4 conversion
# ============================================================

def find_avi_segments(session_dir):
    """
    Find and sort AVI segments in Motive naming order.

    Motive naming: "sessionN-Camera XX (CXXXX).avi" (first segment, no number)
                   "sessionN-Camera XX (CXXXX) (1).avi" (second segment)
                   "sessionN-Camera XX (CXXXX) (2).avi" ...

    Returns sorted list of AVI paths.
    """
    avis = sorted(glob.glob(os.path.join(session_dir, "*.avi")))
    if not avis:
        return []

    # Group by base name (without segment number)
    # Pattern: "(N).avi" at end = segment N, no number = first segment
    def sort_key(path):
        name = os.path.basename(path)
        m = re.search(r'\((\d+)\)\.avi$', name)
        if m:
            # Check if this is the camera ID or segment number
            # Camera ID pattern: "Camera XX (CXXXXX).avi" - always has "Camera" before
            # Segment pattern: "(CXXXXX) (N).avi" - segment number after camera ID
            # Simpler: count the parenthesized groups
            groups = re.findall(r'\(([^)]+)\)', name)
            if len(groups) >= 2:
                # Last group is segment number
                return int(groups[-1])
            else:
                # Only one group = camera ID, this is the first segment
                return 0
        return 0

    avis.sort(key=sort_key)
    return avis


def concat_avi_to_mp4(avi_files, output_path, remove_watermark=True):
    """
    Concat AVI segments into a single MP4 with watermark removed.

    Uses ffmpeg concat demuxer + drawbox filter to cover watermark.
    """
    if not avi_files:
        return False

    print(f"  AVI segments ({len(avi_files)}):")
    for f in avi_files:
        print(f"    {os.path.basename(f)}")

    # Build ffmpeg filter
    vfilters = []
    if remove_watermark:
        vfilters.append(f"drawbox=x={WM_X}:y={WM_Y}:w={WM_W}:h={WM_H}:color=black:t=fill")

    if len(avi_files) == 1:
        # Single file, direct conversion
        cmd = [FFMPEG, "-y", "-i", avi_files[0]]
        if vfilters:
            cmd.extend(["-vf", ",".join(vfilters)])
        cmd.extend(["-c:v", "libx264", "-crf", "18", "-preset", "fast",
                     "-pix_fmt", "yuv420p", "-an", output_path])
    else:
        # Multiple segments: use concat demuxer
        concat_list = tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                                   delete=False, prefix="concat_")
        try:
            for avi in avi_files:
                concat_list.write(f"file '{avi}'\n")
            concat_list.close()

            cmd = [FFMPEG, "-y", "-f", "concat", "-safe", "0",
                   "-i", concat_list.name]
            if vfilters:
                cmd.extend(["-vf", ",".join(vfilters)])
            cmd.extend(["-c:v", "libx264", "-crf", "18", "-preset", "fast",
                         "-pix_fmt", "yuv420p", "-an", output_path])
        finally:
            # Will be cleaned up after ffmpeg runs
            pass

    print(f"  Encoding MP4...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    # Clean up concat list
    if len(avi_files) > 1:
        try:
            os.unlink(concat_list.name)
        except OSError:
            pass

    if result.returncode != 0:
        print(f"  ERROR: ffmpeg failed")
        print(f"  {result.stderr[-500:]}" if result.stderr else "")
        return False

    # Verify output
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "stream=width,height,r_frame_rate,codec_name",
         "-show_entries", "format=duration", "-of", "json", output_path],
        capture_output=True, text=True
    )
    if probe.returncode == 0:
        info = json.loads(probe.stdout)
        stream = info.get("streams", [{}])[0]
        duration = float(info.get("format", {}).get("duration", 0))
        print(f"  OK: {stream.get('codec_name','?')} {stream.get('width','?')}x{stream.get('height','?')} "
              f"{stream.get('r_frame_rate','?')}fps {duration:.1f}s")

    return True


# ============================================================
# Step 2-3: CSV → skeleton + markers
# ============================================================

def process_csv_gt(csv_path, output_dir):
    """
    Process CSV to generate skeleton, body markers, and leg markers.

    Returns dict of generated files.
    """
    results = {}

    print(f"  Loading CSV: {os.path.basename(csv_path)}")
    df = load_motive_csv(csv_path)
    n_frames = len(df)
    print(f"  Frames: {n_frames}")

    # Detect skeleton prefix
    skeleton_prefix = detect_skeleton_prefix(df)
    if not skeleton_prefix:
        print(f"  ERROR: Cannot detect skeleton prefix")
        return results
    print(f"  Skeleton prefix: {skeleton_prefix}")

    # --- Skeleton ---
    skeleton_path = os.path.join(output_dir, "skeleton_h36m.npy")
    print(f"\n  [Skeleton] Extracting H36M joints...")
    joints = convert_csv_to_h36m(csv_path)
    if joints is not None:
        np.save(skeleton_path, joints)
        valid = np.isfinite(joints).all(axis=2).any(axis=1).sum()
        print(f"  [Skeleton] Saved: {skeleton_path} ({joints.shape}, {valid}/{n_frames} valid)")
        results["skeleton"] = skeleton_path
    else:
        print(f"  [Skeleton] FAILED")

    # --- Body markers ---
    body_path = os.path.join(output_dir, "body_markers.npy")
    print(f"\n  [Body Markers] Extracting 27 Plug-in Gait markers...")
    body_markers = extract_body_markers(df, skeleton_prefix)
    np.save(body_path, body_markers)
    valid = np.isfinite(body_markers).all(axis=2).any(axis=1).sum()
    print(f"  [Body Markers] Saved: {body_path} ({body_markers.shape}, {valid}/{n_frames} valid)")
    results["body_markers"] = body_path

    # --- Leg markers ---
    leg_path = os.path.join(output_dir, "leg_markers.npy")
    print(f"\n  [Leg Markers] Extracting L1-L4, R1-R4...")
    leg_markers, leg_names = extract_leg_markers(df)
    np.save(leg_path, leg_markers)
    leg_names_path = os.path.join(output_dir, "leg_marker_names.json")
    with open(leg_names_path, "w") as f:
        json.dump(leg_names, f, indent=2)
    print(f"  [Leg Markers] Saved: {leg_path} ({leg_markers.shape}, markers: {leg_names})")
    results["leg_markers"] = leg_path

    return results


# ============================================================
# Step 4: Blade polygon editor HTML
# ============================================================

def find_blade_rigid_bodies(csv_path):
    """Find blade rigid body names and their markers from CSV headers."""
    with open(csv_path, "r") as f:
        reader = csv.reader(f)
        rows = [next(reader) for _ in range(8)]

    types = rows[2]
    names = rows[3]

    # Find all rigid bodies
    rbs = {}
    for t, n in zip(types, names):
        if t == "Rigid Body Marker" and ":" in n:
            asset, marker = n.split(":", 1)
            rbs.setdefault(asset, set()).add(marker)

    # Filter for blade-related
    blades = {}
    for name, markers in rbs.items():
        if "blade" in name.lower():
            blades[name] = sorted(markers)

    return blades


def extract_blade_marker_positions(csv_path, rb_name, markers, sample_frame=None):
    """
    Extract 3D positions of blade markers from a representative frame.

    Returns dict: {marker_name: [x, y, z]}
    """
    with open(csv_path, "r") as f:
        reader = csv.reader(f)
        header_rows = [next(reader) for _ in range(8)]

    types = header_rows[2]
    names_row = header_rows[3]
    props = header_rows[6]
    axes = header_rows[7]

    # Find column indices for each marker
    marker_cols = {}
    for i, (t, n, p, a) in enumerate(zip(types, names_row, props, axes)):
        if t == "Rigid Body Marker" and n.startswith(rb_name + ":") and p == "Position":
            marker_name = n.split(":")[1]
            if marker_name in markers:
                marker_cols.setdefault(marker_name, {})[a] = i

    # Read a sample frame (skip header, find a frame with good data)
    import pandas as pd
    df = pd.read_csv(csv_path, header=None, skiprows=8, nrows=5000)

    # Try to find a frame where most markers are valid
    best_frame = 0
    best_valid = 0

    for frame_idx in range(min(len(df), 5000)):
        valid = 0
        for mk, cols in marker_cols.items():
            if "X" in cols and "Y" in cols and "Z" in cols:
                try:
                    x = float(df.iloc[frame_idx, cols["X"]])
                    y = float(df.iloc[frame_idx, cols["Y"]])
                    z = float(df.iloc[frame_idx, cols["Z"]])
                    if np.isfinite(x) and np.isfinite(y) and np.isfinite(z):
                        valid += 1
                except (ValueError, IndexError):
                    pass
        if valid > best_valid:
            best_valid = valid
            best_frame = frame_idx
            if valid == len(marker_cols):
                break

    if sample_frame is not None:
        best_frame = sample_frame

    # Extract positions at best frame
    positions = {}
    for mk, cols in marker_cols.items():
        if "X" in cols and "Y" in cols and "Z" in cols:
            try:
                x = float(df.iloc[best_frame, cols["X"]])
                y = float(df.iloc[best_frame, cols["Y"]])
                z = float(df.iloc[best_frame, cols["Z"]])
                if np.isfinite(x) and np.isfinite(y) and np.isfinite(z):
                    positions[mk] = [x, y, z]
            except (ValueError, IndexError):
                pass

    return positions, best_frame


def generate_blade_editor_html(blade_name, marker_positions, output_path):
    """
    Generate an interactive HTML page for defining blade edge ordering.

    Uses Plotly.js for 3D visualization. User clicks markers to define edge1/edge2,
    then exports blade_polygon_order.json.
    """
    markers_json = json.dumps(marker_positions)
    blade_name_safe = blade_name.replace("'", "\\'")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Blade Polygon Editor - {blade_name}</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 20px; background: #1a1a2e; color: #eee; }}
  h1 {{ color: #e94560; }}
  .container {{ display: flex; gap: 20px; }}
  #plot {{ flex: 1; height: 700px; border: 1px solid #444; border-radius: 8px; }}
  .panel {{ width: 300px; }}
  .edge-list {{ background: #16213e; border-radius: 8px; padding: 15px; margin-bottom: 15px; }}
  .edge-list h3 {{ margin-top: 0; }}
  .marker-item {{ padding: 4px 8px; margin: 2px 0; border-radius: 4px; cursor: pointer; display: flex; justify-content: space-between; }}
  .marker-item:hover {{ background: #333; }}
  .marker-item .remove {{ color: #e94560; cursor: pointer; font-weight: bold; }}
  .edge1 .marker-item {{ background: #0a3d62; }}
  .edge2 .marker-item {{ background: #6a0572; }}
  button {{ padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; margin: 5px; }}
  .btn-edge1 {{ background: #1e88e5; color: white; }}
  .btn-edge2 {{ background: #9c27b0; color: white; }}
  .btn-export {{ background: #4caf50; color: white; font-size: 16px; padding: 12px 30px; }}
  .btn-clear {{ background: #e94560; color: white; }}
  .btn-undo {{ background: #ff9800; color: white; }}
  .info {{ background: #16213e; padding: 10px; border-radius: 8px; margin-bottom: 15px; font-size: 13px; }}
  .selected-marker {{ font-weight: bold; color: #ffd700; }}
  #status {{ padding: 10px; background: #16213e; border-radius: 8px; margin-top: 10px; }}
</style>
</head>
<body>
<h1>Blade Polygon Editor: {blade_name}</h1>
<div class="info">
  Click a marker in the 3D plot, then assign it to Edge 1 or Edge 2.
  Markers are ordered by click sequence. Export when done.
</div>
<div class="container">
  <div id="plot"></div>
  <div class="panel">
    <div>
      <button class="btn-edge1" onclick="assignToEdge(1)">+ Edge 1 (blue)</button>
      <button class="btn-edge2" onclick="assignToEdge(2)">+ Edge 2 (purple)</button>
      <button class="btn-undo" onclick="undoLast()">Undo</button>
    </div>
    <div class="edge-list edge1">
      <h3 style="color:#1e88e5">Edge 1 (<span id="e1count">0</span> markers)</h3>
      <div id="edge1list"></div>
    </div>
    <div class="edge-list edge2">
      <h3 style="color:#9c27b0">Edge 2 (<span id="e2count">0</span> markers)</h3>
      <div id="edge2list"></div>
    </div>
    <div>
      <button class="btn-export" onclick="exportJSON()">Export JSON</button>
      <button class="btn-clear" onclick="clearAll()">Clear All</button>
    </div>
    <div id="status">Ready. Click a marker to select it.</div>
  </div>
</div>
<script>
const markerData = {markers_json};
const bladeName = '{blade_name_safe}';
const markerNames = Object.keys(markerData).sort((a,b) => {{
  const na = parseInt(a.replace(/\\D/g,'')) || 0;
  const nb = parseInt(b.replace(/\\D/g,'')) || 0;
  return na - nb;
}});

let selectedMarker = null;
let edge1 = [];
let edge2 = [];

// Colors
const COL_DEFAULT = '#aaaaaa';
const COL_SELECTED = '#ffd700';
const COL_EDGE1 = '#1e88e5';
const COL_EDGE2 = '#9c27b0';

function getMarkerColor(name) {{
  if (name === selectedMarker) return COL_SELECTED;
  if (edge1.includes(name)) return COL_EDGE1;
  if (edge2.includes(name)) return COL_EDGE2;
  return COL_DEFAULT;
}}

function buildTraces() {{
  // Unassigned markers
  const unassigned = markerNames.filter(n => !edge1.includes(n) && !edge2.includes(n));

  const traces = [];

  // Unassigned scatter
  if (unassigned.length > 0) {{
    traces.push({{
      x: unassigned.map(n => markerData[n][0]),
      y: unassigned.map(n => markerData[n][1]),
      z: unassigned.map(n => markerData[n][2]),
      text: unassigned,
      mode: 'markers+text',
      type: 'scatter3d',
      name: 'Unassigned',
      marker: {{
        size: 6,
        color: unassigned.map(n => n === selectedMarker ? COL_SELECTED : COL_DEFAULT),
        line: {{ width: 1, color: '#fff' }}
      }},
      textposition: 'top center',
      textfont: {{ size: 10, color: '#ccc' }}
    }});
  }}

  // Edge 1 markers + line
  if (edge1.length > 0) {{
    traces.push({{
      x: edge1.map(n => markerData[n][0]),
      y: edge1.map(n => markerData[n][1]),
      z: edge1.map(n => markerData[n][2]),
      text: edge1.map((n,i) => `E1[${{i}}] ${{n}}`),
      mode: 'markers+text+lines',
      type: 'scatter3d',
      name: 'Edge 1',
      marker: {{ size: 8, color: COL_EDGE1, symbol: 'diamond' }},
      line: {{ color: COL_EDGE1, width: 4 }},
      textposition: 'top center',
      textfont: {{ size: 10, color: COL_EDGE1 }}
    }});
  }}

  // Edge 2 markers + line
  if (edge2.length > 0) {{
    traces.push({{
      x: edge2.map(n => markerData[n][0]),
      y: edge2.map(n => markerData[n][1]),
      z: edge2.map(n => markerData[n][2]),
      text: edge2.map((n,i) => `E2[${{i}}] ${{n}}`),
      mode: 'markers+text+lines',
      type: 'scatter3d',
      name: 'Edge 2',
      marker: {{ size: 8, color: COL_EDGE2, symbol: 'diamond' }},
      line: {{ color: COL_EDGE2, width: 4 }},
      textposition: 'top center',
      textfont: {{ size: 10, color: COL_EDGE2 }}
    }});
  }}

  return traces;
}}

const layout = {{
  scene: {{
    xaxis: {{ title: 'X (mm)' }},
    yaxis: {{ title: 'Y (mm)' }},
    zaxis: {{ title: 'Z (mm)' }},
    aspectmode: 'data',
    bgcolor: '#0f3460'
  }},
  paper_bgcolor: '#1a1a2e',
  font: {{ color: '#eee' }},
  margin: {{ l: 0, r: 0, t: 0, b: 0 }},
  showlegend: true,
  legend: {{ x: 0, y: 1, bgcolor: 'rgba(0,0,0,0.5)' }}
}};

Plotly.newPlot('plot', buildTraces(), layout);

document.getElementById('plot').on('plotly_click', function(data) {{
  if (data.points.length > 0) {{
    const pt = data.points[0];
    const name = pt.text.replace(/^E[12]\\[\\d+\\] /, '');
    selectedMarker = name;
    document.getElementById('status').textContent = `Selected: ${{name}}`;
    Plotly.react('plot', buildTraces(), layout);
  }}
}});

function assignToEdge(edgeNum) {{
  if (!selectedMarker) {{
    document.getElementById('status').textContent = 'No marker selected. Click a marker first.';
    return;
  }}
  // Remove from other edge if present
  edge1 = edge1.filter(n => n !== selectedMarker);
  edge2 = edge2.filter(n => n !== selectedMarker);

  if (edgeNum === 1) edge1.push(selectedMarker);
  else edge2.push(selectedMarker);

  selectedMarker = null;
  updateUI();
}}

function undoLast() {{
  if (edge2.length > 0 && (edge1.length === 0 || edge2.length >= edge1.length)) {{
    edge2.pop();
  }} else if (edge1.length > 0) {{
    edge1.pop();
  }}
  updateUI();
}}

function clearAll() {{
  edge1 = [];
  edge2 = [];
  selectedMarker = null;
  updateUI();
}}

function updateUI() {{
  document.getElementById('e1count').textContent = edge1.length;
  document.getElementById('e2count').textContent = edge2.length;

  let html1 = edge1.map((n,i) => `<div class="marker-item"><span>[${{i}}] ${{n}}</span><span class="remove" onclick="removeFromEdge(1,${{i}})">&times;</span></div>`).join('');
  let html2 = edge2.map((n,i) => `<div class="marker-item"><span>[${{i}}] ${{n}}</span><span class="remove" onclick="removeFromEdge(2,${{i}})">&times;</span></div>`).join('');

  document.getElementById('edge1list').innerHTML = html1;
  document.getElementById('edge2list').innerHTML = html2;

  Plotly.react('plot', buildTraces(), layout);
  document.getElementById('status').textContent = `Edge1: ${{edge1.length}}, Edge2: ${{edge2.length}}`;
}}

function removeFromEdge(edgeNum, idx) {{
  if (edgeNum === 1) edge1.splice(idx, 1);
  else edge2.splice(idx, 1);
  updateUI();
}}

function exportJSON() {{
  if (edge1.length < 2 || edge2.length < 2) {{
    alert('Each edge needs at least 2 markers.');
    return;
  }}
  const data = {{ edge1: edge1, edge2: edge2 }};
  const blob = new Blob([JSON.stringify(data, null, 2)], {{ type: 'application/json' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'blade_polygon_order.json';
  a.click();
  URL.revokeObjectURL(url);
  document.getElementById('status').textContent = 'Exported blade_polygon_order.json! Move it to the session output folder.';
}}
</script>
</body>
</html>"""
    with open(output_path, "w") as f:
        f.write(html)
    return True


# ============================================================
# Main orchestration
# ============================================================

def process_session(session_dir, output_dir):
    """Process a single mocap session directory."""
    session_name = os.path.basename(session_dir)
    print(f"\n{'=' * 70}")
    print(f"  Processing: {session_name}")
    print(f"  Input:  {session_dir}")
    print(f"  Output: {output_dir}")
    print(f"{'=' * 70}")

    os.makedirs(output_dir, exist_ok=True)

    # Find files
    avi_files = find_avi_segments(session_dir)
    csv_files = sorted(glob.glob(os.path.join(session_dir, "*.csv")))
    # Exclude backup files
    csv_files = [c for c in csv_files if not c.endswith(".bak")]

    if not csv_files:
        print(f"  ERROR: No CSV files found in {session_dir}")
        return False

    csv_path = csv_files[0]  # Use the first CSV
    if len(csv_files) > 1:
        print(f"  WARNING: Multiple CSVs found, using {os.path.basename(csv_path)}")

    success = True

    # Step 1: AVI → MP4
    video_path = os.path.join(output_dir, "video.mp4")
    if avi_files:
        if os.path.exists(video_path):
            print(f"\n  [Step 1] Video already exists, skipping: {video_path}")
        else:
            print(f"\n  [Step 1] AVI → MP4 ({len(avi_files)} segments)")
            if not concat_avi_to_mp4(avi_files, video_path, remove_watermark=True):
                print(f"  [Step 1] FAILED")
                success = False
    else:
        print(f"\n  [Step 1] No AVI files found, skipping video processing")

    # Step 2-3: CSV → skeleton + markers
    skeleton_path = os.path.join(output_dir, "skeleton_h36m.npy")
    body_path = os.path.join(output_dir, "body_markers.npy")
    if os.path.exists(skeleton_path) and os.path.exists(body_path):
        print(f"\n  [Step 2-3] GT files already exist, skipping")
    else:
        print(f"\n  [Step 2-3] CSV → GT data")
        results = process_csv_gt(csv_path, output_dir)
        if "skeleton" not in results:
            success = False

    # Step 4: Blade editor HTML
    print(f"\n  [Step 4] Blade polygon editor")
    blades = find_blade_rigid_bodies(csv_path)
    if not blades:
        print(f"  No blade rigid bodies found")
    else:
        for blade_name, markers in blades.items():
            json_path = os.path.join(output_dir, "blade_polygon_order.json")
            if os.path.exists(json_path):
                print(f"  {blade_name}: blade_polygon_order.json already exists, skipping editor")
                continue

            html_name = f"blade_editor_{blade_name.replace(' ', '_')}.html"
            html_path = os.path.join(output_dir, html_name)

            positions, frame_idx = extract_blade_marker_positions(
                csv_path, blade_name, markers
            )
            print(f"  {blade_name}: {len(positions)}/{len(markers)} markers visible (frame {frame_idx})")

            if positions:
                generate_blade_editor_html(blade_name, positions, html_path)
                print(f"  Generated: {html_path}")
                print(f"  → Open in browser, define edges, export blade_polygon_order.json")

    # Summary
    print(f"\n{'=' * 70}")
    print(f"  [{session_name}] {'DONE' if success else 'DONE WITH ERRORS'}")
    print(f"{'=' * 70}")
    print(f"  Output files:")
    for f in sorted(os.listdir(output_dir)):
        fpath = os.path.join(output_dir, f)
        size = os.path.getsize(fpath)
        if size > 1024 * 1024:
            print(f"    {f:40s} {size / 1024 / 1024:.1f} MB")
        else:
            print(f"    {f:40s} {size / 1024:.1f} KB")

    return success


def main():
    parser = argparse.ArgumentParser(
        description="One-command mocap session processor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single session
  python process_mocap_session.py /Volumes/KINGSTON/P7_mocap/P7_1 -o /Volumes/FastACIS/csl_output/P7_1

  # Batch: all sessions under parent directory
  python process_mocap_session.py /Volumes/KINGSTON/P7_mocap -o /Volumes/FastACIS/csl_output --batch
        """,
    )
    parser.add_argument("input_dir", help="Session directory (or parent directory with --batch)")
    parser.add_argument("-o", "--output_dir", required=True, help="Output directory")
    parser.add_argument("--batch", action="store_true",
                        help="Process all P*_* subdirectories under input_dir")
    parser.add_argument("--no_video", action="store_true",
                        help="Skip AVI→MP4 conversion")

    args = parser.parse_args()

    if args.batch:
        # Find all session directories
        sessions = sorted(glob.glob(os.path.join(args.input_dir, "P*_*")))
        sessions = [s for s in sessions if os.path.isdir(s)]

        if not sessions:
            print(f"No session directories found in {args.input_dir}")
            return 1

        print(f"Batch processing {len(sessions)} sessions")
        results = {}
        for session_dir in sessions:
            session_name = os.path.basename(session_dir)
            out_dir = os.path.join(args.output_dir, session_name)
            ok = process_session(session_dir, out_dir)
            results[session_name] = ok

        print(f"\n{'=' * 70}")
        print("BATCH SUMMARY")
        print(f"{'=' * 70}")
        for name, ok in results.items():
            print(f"  {name}: {'OK' if ok else 'FAILED'}")
        failed = sum(1 for ok in results.values() if not ok)
        return 1 if failed else 0
    else:
        return 0 if process_session(args.input_dir, args.output_dir) else 1


if __name__ == "__main__":
    sys.exit(main())
