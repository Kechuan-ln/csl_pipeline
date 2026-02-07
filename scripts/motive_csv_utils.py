#!/usr/bin/env python3
"""
Shared utilities for loading OptiTrack Motive CSV files.

Used by csv2h36m.py, extract_markers.py, and extract_blade_edges.py.

Column name format: {Name}_{Type1}_{Type2}_{Axis}
Example: Skeleton 001:Head_Bone_Position_X
"""

import numpy as np
import pandas as pd


def load_motive_csv(csv_file):
    """
    Load OptiTrack Motive CSV with proper column naming.

    Motive CSV header layout:
        Row 0: Format version
        Row 1: Type (Bone, Bone Marker, Rigid Body, Rigid Body Marker, Marker)
        Row 2: (unused)
        Row 3: Names
        Row 4-5: (unused)
        Row 6: Rotation/Position
        Row 7: X/Y/Z/W axis
        Row 8+: Data
    """
    # Row 1: Type (Bone, Bone Marker, Rigid Body, Rigid Body Marker, Marker)
    df_type1 = pd.read_csv(csv_file, header=None, skiprows=1, nrows=1)
    raw_type1 = df_type1.iloc[0].values

    # Row 3: Names
    df_names = pd.read_csv(csv_file, header=None, skiprows=3, nrows=1)
    raw_names = df_names.iloc[0].values

    # Row 6: Rotation/Position
    df_types = pd.read_csv(csv_file, header=None, skiprows=6, nrows=1)
    raw_types = df_types.iloc[0].values

    # Row 7: X/Y/Z/W axis
    df_axes = pd.read_csv(csv_file, header=None, skiprows=7, nrows=1)
    raw_axes = df_axes.iloc[0].values

    # Build unique column names
    new_columns = []
    for i in range(len(raw_names)):
        name = str(raw_names[i]).strip()
        axis = str(raw_axes[i]).strip() if i < len(raw_axes) else ''
        dtype = str(raw_types[i]).strip() if i < len(raw_types) else ''
        type1 = str(raw_type1[i]).strip() if i < len(raw_type1) else ''

        if i == 0:
            new_columns.append("Frame")
        elif i == 1:
            new_columns.append("Time")
        else:
            if name == 'nan' or not name:
                new_columns.append(f"Unknown_{type1}_{dtype}_{axis}")
            else:
                new_columns.append(f"{name}_{type1}_{dtype}_{axis}")

    # Load data (skip header rows 0-7)
    df = pd.read_csv(csv_file, header=None, skiprows=8)
    df.columns = new_columns[:len(df.columns)]

    return df


def detect_skeleton_prefix(df):
    """
    Auto-detect skeleton prefix from DataFrame columns.

    Supports: body, Skeleton 001, P2, P3
    """
    patterns = {
        'body': 'body:',
        'Skeleton 001': 'Skeleton 001:',
        'P2': 'P2:',
        'P3': 'P3:',
    }

    for col in df.columns:
        for name, pattern in patterns.items():
            if pattern in col and '_Bone_Position_' in col:
                return name

    return None
