#!/usr/bin/env python3
"""
One-command mocap session processor.

Processes a raw Motive session directory (AVI videos + CSV) into pipeline-ready outputs:
  0. .mcal → cam19_initial.yaml (OptiTrack calibration → OpenCV extrinsics, shared across sessions)
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
from mcal_to_cam19_yaml import load_mcal, find_primecolor_camera, extract_cam19_params, save_cam19_yaml

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

    # Use VideoToolbox hardware encoder on macOS if available, else libx264
    import platform
    if platform.system() == "Darwin":
        enc_args = ["-c:v", "h264_videotoolbox", "-q:v", "65", "-pix_fmt", "yuv420p"]
    else:
        enc_args = ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p"]

    if len(avi_files) == 1:
        # Single file, direct conversion
        cmd = [FFMPEG, "-y", "-i", avi_files[0]]
        if vfilters:
            cmd.extend(["-vf", ",".join(vfilters)])
        cmd.extend(enc_args + ["-an", output_path])
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
            cmd.extend(enc_args + ["-an", output_path])
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

    Uses Three.js for 3D visualization with raycasting, ruling lines,
    keyboard shortcuts, and direct marker clicking.
    """
    markers_json = json.dumps(marker_positions)
    blade_name_safe = blade_name.replace("'", "\\'").replace(" ", "_")
    n_markers = len(marker_positions)
    export_filename = f"blade_polygon_order_{blade_name_safe}.json"

    # No f-string double-brace issues: we use a raw template with explicit substitution
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BLADE_TITLE Edge Editor</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: 'Segoe UI', Arial, sans-serif; overflow: hidden; background: #1a1a2e; color: #fff; }
  #container { width: 100vw; height: 100vh; }
  #loading-overlay {
    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    background: #1a1a2e; z-index: 9999; display: flex;
    justify-content: center; align-items: center; flex-direction: column;
  }
  .spinner {
    width: 50px; height: 50px; border: 5px solid #333;
    border-top: 5px solid #4fc3f7; border-radius: 50%;
    animation: spin 1s linear infinite; margin-bottom: 20px;
  }
  @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
  #ui-panel {
    position: absolute; top: 10px; left: 10px;
    background: rgba(30, 30, 50, 0.95); padding: 15px;
    border-radius: 10px; color: #fff; min-width: 320px; max-width: 380px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.3);
  }
  #ui-panel h2 { margin-bottom: 10px; color: #4fc3f7; font-size: 16px; }
  #ui-panel p { font-size: 11px; color: #aaa; margin-bottom: 10px; line-height: 1.4; }
  .edge-toggle { display: flex; margin: 10px 0; gap: 5px; }
  .edge-btn {
    flex: 1; padding: 10px; border: 2px solid; border-radius: 8px;
    font-weight: bold; cursor: pointer; text-align: center;
    transition: all 0.2s; user-select: none;
  }
  .edge-btn.edge1 { border-color: #4fc3f7; background: transparent; color: #4fc3f7; }
  .edge-btn.edge1.active { background: #4fc3f7; color: #1a1a2e; }
  .edge-btn.edge2 { border-color: #ff7043; background: transparent; color: #ff7043; }
  .edge-btn.edge2.active { background: #ff7043; color: #1a1a2e; }
  .edge-section {
    background: rgba(0,0,0,0.3); padding: 8px; border-radius: 5px;
    margin: 8px 0; max-height: 150px; overflow-y: auto;
  }
  .edge-section h3 { font-size: 12px; margin-bottom: 5px; display: flex; justify-content: space-between; }
  .edge-section.edge1 h3 { color: #4fc3f7; }
  .edge-section.edge2 h3 { color: #ff7043; }
  .edge-item {
    display: inline-block; padding: 2px 6px; margin: 2px;
    border-radius: 3px; font-size: 10px; font-family: monospace;
  }
  .edge-item.edge1 { background: rgba(79, 195, 247, 0.3); color: #4fc3f7; }
  .edge-item.edge2 { background: rgba(255, 112, 67, 0.3); color: #ff7043; }
  button {
    background: #555; color: #fff; border: none;
    padding: 8px 12px; border-radius: 5px; cursor: pointer;
    font-weight: bold; margin: 3px;
  }
  button:hover { background: #666; }
  button:disabled { background: #333; color: #666; cursor: not-allowed; }
  #export-btn { background: #66bb6a; color: #1a1a2e; }
  #export-btn:hover { background: #81c784; }
  #export-btn:disabled { background: #333; color: #666; }
  #status {
    margin-top: 10px; padding: 8px; background: rgba(0,0,0,0.3);
    border-radius: 5px; font-size: 11px;
  }
  #help-panel {
    position: absolute; bottom: 10px; left: 10px;
    background: rgba(30, 30, 50, 0.9); padding: 10px 15px;
    border-radius: 8px; color: #888; font-size: 11px; pointer-events: none;
  }
  #help-panel kbd { background: #333; padding: 2px 6px; border-radius: 3px; margin: 0 2px; }
  #ruling-toggle { margin-top: 10px; display: flex; align-items: center; gap: 10px; }
  #ruling-toggle label { font-size: 12px; color: #aaa; }
</style>
</head>
<body>
<div id="loading-overlay">
  <div class="spinner"></div>
  <div id="loading-text">Loading 3D Engine...</div>
</div>
<div id="container"></div>
<div id="ui-panel">
  <h2>BLADE_TITLE Edge Editor (NUM_MARKERS markers)</h2>
  <p>1. Select <b>Edge 1</b> and click markers along one blade edge<br>
     2. Switch to <b>Edge 2</b> and click markers along the other edge<br>
     3. Edges should have same direction (both tip-to-base or both base-to-tip)</p>
  <div class="edge-toggle">
    <div class="edge-btn edge1 active" id="btn-edge1">Edge 1 (Blue)</div>
    <div class="edge-btn edge2" id="btn-edge2">Edge 2 (Orange)</div>
  </div>
  <div class="edge-section edge1">
    <h3><span>Edge 1</span><span id="edge1-count">0 markers</span></h3>
    <div class="edge-list" id="edge1-list">-</div>
  </div>
  <div class="edge-section edge2">
    <h3><span>Edge 2</span><span id="edge2-count">0 markers</span></h3>
    <div class="edge-list" id="edge2-list">-</div>
  </div>
  <div id="ruling-toggle">
    <input type="checkbox" id="show-rulings" checked>
    <label for="show-rulings">Show ruling lines (edge connections)</label>
  </div>
  <div style="margin-top: 10px;">
    <button id="undo-btn">Undo</button>
    <button id="reset-btn">Reset All</button>
    <button id="export-btn" disabled>Export JSON</button>
  </div>
  <div id="status">Click markers to define edges</div>
</div>
<div id="help-panel">
  <kbd>Left drag</kbd> Rotate | <kbd>Right drag</kbd> Pan | <kbd>Scroll</kbd> Zoom |
  <kbd>1</kbd> Edge1 | <kbd>2</kbd> Edge2 | <kbd>Z</kbd> Undo | <kbd>R</kbd> Reset view
</div>

<script>
  window.MARKER_DATA = MARKER_JSON;
  window.BLADE_NAME = 'BLADE_SAFE';
  window.EXPORT_FILENAME = 'EXPORT_FN';
</script>

<script type="importmap">
{ "imports": { "three": "https://unpkg.com/three@0.160.0/build/three.module.js", "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/" } }
</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const markerData = window.MARKER_DATA;
const bladeName = window.BLADE_NAME;
const exportFilename = window.EXPORT_FILENAME;
const loadingOverlay = document.getElementById('loading-overlay');

try { init(); loadingOverlay.style.display = 'none'; }
catch (e) {
  console.error(e);
  document.getElementById('loading-text').innerHTML = 'Error: ' + e.message;
  document.getElementById('loading-text').style.color = '#ff5555';
}

function init() {
  const container = document.getElementById('container');
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1a1a2e);
  const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 1, 10000);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(window.devicePixelRatio);
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.05;

  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
  dirLight.position.set(100, 200, 100);
  scene.add(dirLight);
  scene.add(new THREE.GridHelper(500, 20, 0x444444, 0x333333));
  scene.add(new THREE.AxesHelper(100));

  const COLORS = { unselected: 0x888888, edge1: 0x4fc3f7, edge2: 0xff7043, ruling: 0x66bb6a };
  const markerNames = Object.keys(markerData);
  let cx = 0, cy = 0, cz = 0;
  markerNames.forEach(n => { cx += markerData[n][0]; cy += markerData[n][1]; cz += markerData[n][2]; });
  cx /= markerNames.length; cy /= markerNames.length; cz /= markerNames.length;

  const markerMeshes = {};
  const markerLabels = {};
  const sphereRadius = 6;

  markerNames.forEach(name => {
    const pos = markerData[name];
    const x = pos[0] - cx, y = pos[1] - cy, z = pos[2] - cz;
    const sphere = new THREE.Mesh(
      new THREE.SphereGeometry(sphereRadius, 16, 16),
      new THREE.MeshPhongMaterial({ color: COLORS.unselected, emissive: 0x222222 })
    );
    sphere.position.set(x, y, z);
    sphere.userData.markerName = name;
    scene.add(sphere);
    markerMeshes[name] = sphere;

    const nameLabel = createTextLabel(name.replace('Marker ', ''));
    nameLabel.position.set(x, y - sphereRadius - 10, z);
    scene.add(nameLabel);

    const label = createIndexLabel('');
    label.position.set(x, y + sphereRadius + 8, z);
    label.visible = false;
    scene.add(label);
    markerLabels[name] = label;
  });

  function createTextLabel(text) {
    const canvas = document.createElement('canvas');
    canvas.width = 64; canvas.height = 32;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#666'; ctx.font = '18px Arial';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(text, 32, 16);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas) }));
    sprite.scale.set(20, 10, 1);
    return sprite;
  }

  function createIndexLabel(text, color = '#4fc3f7') {
    const canvas = document.createElement('canvas');
    canvas.width = 64; canvas.height = 64;
    const ctx = canvas.getContext('2d');
    const texture = new THREE.CanvasTexture(canvas);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture }));
    sprite.scale.set(14, 14, 1);
    sprite.userData = { canvas, ctx, texture };
    updateIndexLabel(sprite, text, color);
    return sprite;
  }

  function updateIndexLabel(sprite, text, color = '#4fc3f7') {
    const { ctx, texture } = sprite.userData;
    ctx.clearRect(0, 0, 64, 64);
    ctx.fillStyle = color;
    ctx.beginPath(); ctx.arc(32, 32, 26, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#1a1a2e'; ctx.font = 'bold 24px Arial';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(text, 32, 32);
    texture.needsUpdate = true;
  }

  let currentEdge = 1;
  let edge1 = [], edge2 = [];
  let edge1Lines = [], edge2Lines = [];
  let rulingLines = [];
  let showRulings = true;

  camera.position.set(0, 200, 400);
  controls.target.set(0, 0, 0);
  controls.update();

  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();

  function onMouseClick(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects(Object.values(markerMeshes));
    if (intersects.length > 0) {
      const name = intersects[0].object.userData.markerName;
      if (!edge1.includes(name) && !edge2.includes(name)) selectMarker(name);
    }
  }

  function selectMarker(name) {
    const edge = currentEdge === 1 ? edge1 : edge2;
    const color = currentEdge === 1 ? COLORS.edge1 : COLORS.edge2;
    const colorHex = currentEdge === 1 ? '#4fc3f7' : '#ff7043';
    const lines = currentEdge === 1 ? edge1Lines : edge2Lines;

    markerMeshes[name].material.color.setHex(color);
    markerMeshes[name].material.emissive.setHex(currentEdge === 1 ? 0x112233 : 0x331111);

    updateIndexLabel(markerLabels[name], (edge.length + 1).toString(), colorHex);
    markerLabels[name].visible = true;

    if (edge.length > 0) {
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          markerMeshes[edge[edge.length - 1]].position.clone(),
          markerMeshes[name].position.clone()
        ]),
        new THREE.LineBasicMaterial({ color: color, linewidth: 2 })
      );
      scene.add(line);
      lines.push(line);
    }
    edge.push(name);
    updateRulingLines();
    updateUI();
  }

  function updateRulingLines() {
    rulingLines.forEach(l => scene.remove(l));
    rulingLines = [];
    if (!showRulings) return;
    const n = Math.min(edge1.length, edge2.length);
    for (let i = 0; i < n; i++) {
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          markerMeshes[edge1[i]].position.clone(),
          markerMeshes[edge2[i]].position.clone()
        ]),
        new THREE.LineDashedMaterial({ color: COLORS.ruling, dashSize: 5, gapSize: 5, opacity: 0.6, transparent: true })
      );
      line.computeLineDistances();
      scene.add(line);
      rulingLines.push(line);
    }
  }

  window.setCurrentEdge = function(edgeNum) {
    currentEdge = edgeNum;
    document.getElementById('btn-edge1').classList.toggle('active', edgeNum === 1);
    document.getElementById('btn-edge2').classList.toggle('active', edgeNum === 2);
  };

  window.undo = function() {
    const edge = currentEdge === 1 ? edge1 : edge2;
    const lines = currentEdge === 1 ? edge1Lines : edge2Lines;
    if (edge.length === 0) return;
    const name = edge.pop();
    markerMeshes[name].material.color.setHex(COLORS.unselected);
    markerMeshes[name].material.emissive.setHex(0x222222);
    markerLabels[name].visible = false;
    if (lines.length > 0) scene.remove(lines.pop());
    updateRulingLines();
    updateUI();
  };

  window.reset = function() {
    [edge1, edge2].forEach(edge => edge.forEach(n => {
      markerMeshes[n].material.color.setHex(COLORS.unselected);
      markerMeshes[n].material.emissive.setHex(0x222222);
      markerLabels[n].visible = false;
    }));
    edge1Lines.forEach(l => scene.remove(l));
    edge2Lines.forEach(l => scene.remove(l));
    rulingLines.forEach(l => scene.remove(l));
    edge1 = []; edge2 = [];
    edge1Lines = []; edge2Lines = [];
    rulingLines = [];
    window.setCurrentEdge(1);
    updateUI();
  };

  window.exportJSON = function() {
    const data = { edge1, edge2, rigid_body: bladeName };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = exportFilename;
    a.click();
    document.getElementById('status').textContent = 'Exported ' + exportFilename + '!';
    document.getElementById('status').style.color = '#66bb6a';
  };

  function updateUI() {
    document.getElementById('edge1-count').textContent = edge1.length + ' markers';
    document.getElementById('edge1-list').innerHTML = edge1.length > 0
      ? edge1.map((n, i) => '<span class="edge-item edge1">' + (i+1) + ':' + n.replace('Marker ','') + '</span>').join('')
      : '-';
    document.getElementById('edge2-count').textContent = edge2.length + ' markers';
    document.getElementById('edge2-list').innerHTML = edge2.length > 0
      ? edge2.map((n, i) => '<span class="edge-item edge2">' + (i+1) + ':' + n.replace('Marker ','') + '</span>').join('')
      : '-';
    const status = document.getElementById('status');
    if (edge1.length > 0 && edge2.length > 0) {
      if (edge1.length === edge2.length) {
        status.textContent = 'Ready! Both edges have ' + edge1.length + ' markers';
        status.style.color = '#66bb6a';
      } else {
        status.textContent = 'Edge lengths differ: ' + edge1.length + ' vs ' + edge2.length;
        status.style.color = '#ffb74d';
      }
    } else {
      status.textContent = 'Defining Edge ' + currentEdge + '... (click markers in order)';
      status.style.color = '#aaa';
    }
    document.getElementById('export-btn').disabled = !(edge1.length >= 2 && edge2.length >= 2);
  }

  document.getElementById('btn-edge1').onclick = () => window.setCurrentEdge(1);
  document.getElementById('btn-edge2').onclick = () => window.setCurrentEdge(2);
  document.getElementById('undo-btn').onclick = window.undo;
  document.getElementById('reset-btn').onclick = window.reset;
  document.getElementById('export-btn').onclick = window.exportJSON;
  renderer.domElement.addEventListener('click', onMouseClick);
  document.getElementById('show-rulings').addEventListener('change', e => {
    showRulings = e.target.checked;
    updateRulingLines();
  });
  document.addEventListener('keydown', e => {
    if (e.key === '1') window.setCurrentEdge(1);
    if (e.key === '2') window.setCurrentEdge(2);
    if (e.key === 'z' || e.key === 'Z') window.undo();
    if (e.key === 'r' || e.key === 'R') {
      camera.position.set(0, 200, 400);
      controls.target.set(0, 0, 0);
      controls.update();
    }
  });
  window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  function animate() { requestAnimationFrame(animate); controls.update(); renderer.render(scene, camera); }
  animate();
  updateUI();
}
</script>
</body>
</html>"""

    # Substitute template placeholders (avoids f-string double-brace issues with JS)
    html = html.replace("BLADE_TITLE", blade_name)
    html = html.replace("NUM_MARKERS", str(n_markers))
    html = html.replace("MARKER_JSON", markers_json)
    html = html.replace("BLADE_SAFE", blade_name_safe)
    html = html.replace("EXPORT_FN", export_filename)

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

    # Step 0: .mcal → cam19_initial.yaml
    cam19_path = os.path.join(output_dir, "cam19_initial.yaml")
    if os.path.exists(cam19_path):
        print(f"\n  [Step 0] cam19_initial.yaml already exists, skipping")
    else:
        # Search for .mcal in session dir, then parent dir
        mcal_files = glob.glob(os.path.join(session_dir, "*.mcal"))
        if not mcal_files:
            parent_dir = os.path.dirname(session_dir)
            mcal_files = glob.glob(os.path.join(parent_dir, "*.mcal"))
        if mcal_files:
            mcal_path = mcal_files[0]
            print(f"\n  [Step 0] mcal → cam19_initial.yaml")
            print(f"  mcal: {os.path.basename(mcal_path)}")
            try:
                mcal_root = load_mcal(mcal_path)
                cam_elem, cid = find_primecolor_camera(mcal_root)
                K, dist, rvec, tvec, R = extract_cam19_params(cam_elem)
                save_cam19_yaml(cam19_path, K, dist, rvec, tvec, R)
                print(f"  [Step 0] Saved: {cam19_path}")
                print(f"  K: fx={K[0,0]:.1f} fy={K[1,1]:.1f} cx={K[0,2]:.1f} cy={K[1,2]:.1f}")
            except Exception as e:
                print(f"  [Step 0] FAILED: {e}")
                success = False
        else:
            print(f"\n  [Step 0] No .mcal file found, skipping cam19 extraction")

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
            blade_safe = blade_name.replace(" ", "_")
            json_name = f"blade_polygon_order_{blade_safe}.json"
            json_path = os.path.join(output_dir, json_name)
            if os.path.exists(json_path):
                print(f"  {blade_name}: {json_name} already exists, skipping editor")
                continue

            html_name = f"blade_editor_{blade_safe}.html"
            html_path = os.path.join(output_dir, html_name)

            positions, frame_idx = extract_blade_marker_positions(
                csv_path, blade_name, markers
            )
            print(f"  {blade_name}: {len(positions)}/{len(markers)} markers visible (frame {frame_idx})")

            if positions:
                generate_blade_editor_html(blade_name, positions, html_path)
                print(f"  Generated: {html_path}")
                print(f"  → Open in browser, define edges, export {json_name}")

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
