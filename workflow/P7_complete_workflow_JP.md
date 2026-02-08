# CSL Pipeline 完全ワークフローガイド（P7）

1人のパーティシパントのマルチカメラキャリブレーションとGT分配を、生データから最終出力まで完全に処理します。

---

## 目次

1. [前提条件](#前提条件)
2. [データ準備](#データ準備)
3. [Pipeline 3つのフェーズ](#pipeline-3つのフェーズ)
4. [検証と最適化ツール](#検証と最適化ツール)
5. [出力ディレクトリ構造](#出力ディレクトリ構造)
6. [トラブルシューティング](#トラブルシューティング)

---

## 前提条件

### ソフトウェア環境

```bash
# Conda環境
conda activate camcalib

# pyzbar高速化が利用可能か確認
python -c "from pyzbar import pyzbar; print('✅ pyzbarインストール済み')"
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/zbar/lib:$DYLD_LIBRARY_PATH"
```

### ハードウェアリソース

- **ストレージ容量**：1セッションあたり約30-50 GB（GoPro 4Kビデオ + 処理出力）
- **メモリ**：32 GB以上推奨（マルチカメラ並列処理）
- **外部ストレージ**：
  - FastACIS：GoPro生データ + 同期出力 + キャリブレーション結果
  - T7/KINGSTON：Mocap生データ + GT出力

---

## データ準備

### 1. Mocap生データ配置

**配置場所**：`/Volumes/KINGSTON/P7_mocap/`

**ディレクトリ構造**：
```
P7_mocap/
├── P7_1/
│   ├── session1-Camera 13 (C11764).avi       # PrimeColorビデオ（複数セグメントの可能性あり）
│   ├── session1-Camera 13 (C11764) (1).avi   # 続きのセグメント
│   └── Take 2024-11-05 03.50.49 PM.csv       # MotiveエクスポートCSV
├── P7_2/
│   ├── session2-Camera 13 (C11764).avi
│   └── Take 2024-11-05 04.10.22 PM.csv
├── P7_3/, P7_4/, P7_5/
└── Cal_2026-02-01.mcal                        # OptiTrackキャリブレーションファイル（オプション、親ディレクトリ）
```

**重要ファイル**：
- **AVIビデオ**：PrimeColorカメラ生録画（120fps、1920x1080）
- **CSVファイル**：Motiveエクスポートスケルトンとマーカーデータ
- **.mcalファイル**：OptiTrackシステムキャリブレーション（cam19初期外部パラメータ含む）

---

### 2. GoPro生データ配置

**配置場所**：`/Volumes/FastACIS/csl_11_5/P7_gopro/`

**生構造**（カメラごと）：
```
P7_gopro/
├── cam1/
│   ├── GX010279.MP4  # セッション1
│   ├── GX010280.MP4  # セッション2
│   ├── GX010281.MP4  # セッション3
│   └── ...
├── cam2/
│   ├── GX010276.MP4  # セッション1
│   ├── GX010277.MP4  # セッション2
│   └── ...
├── cam3/, ..., cam18/
└── qr_sync.mp4        # QRアンカービデオ（同期用）
```

**注意**：
- GoProファイル名は**録画時間順**に自動採番されるため、実際のセッションとの対応付けが必要
- カメラごとのビデオ数が一致していることを確認（通常5セッション = 5ビデオ）

---

### 3. GoProデータ整理（セッションごと構造）

**必要な理由**：生データはカメラごと構造、パイプラインはセッションごと構造が必要。

```bash
# プレビュー（dry-run）
python workflow/organize_gopro_videos.py \
    --input /Volumes/FastACIS/csl_11_5/P7_gopro \
    --output /Volumes/FastACIS/csl_11_5/organized \
    --participant P7 \
    --dry-run

# 確認後、実際に実行
python workflow/organize_gopro_videos.py \
    --input /Volumes/FastACIS/csl_11_5/P7_gopro \
    --output /Volumes/FastACIS/csl_11_5/organized \
    --participant P7
```

**出力構造**：
```
organized/
├── qr_sync.mp4           # コピーされたQRアンカービデオ
├── P7_1/
│   ├── cam1/GX010279.MP4
│   ├── cam2/GX010276.MP4
│   └── ... (16カメラ)
├── P7_2/, P7_3/, P7_4/, P7_5/
```

---

## Pipeline 3つのフェーズ

### フェーズ1：Mocapデータ処理

**目的**：AVIビデオ結合 + CSV→GT変換 + ブレードアノテーションツール生成

#### コマンド

```bash
# 全セッションをバッチ処理
python workflow/process_mocap_session.py \
    /Volumes/KINGSTON/P7_mocap \
    -o /Volumes/KINGSTON/P7_output \
    --batch
```

#### 出力（セッションごと）

```
P7_output/P7_1/
├── video.mp4                      # 120fps PrimeColorビデオ（透かし除去済み）
├── cam19_initial.yaml             # .mcalから抽出した初期外部パラメータ
├── skeleton_h36m.npy              # (N, 17, 3) H36M形式スケルトン
├── body_markers.npy               # (N, 27, 3) Plug-in Gaitマーカー
├── body_marker_names.json
├── leg_markers.npy                # (N, 8, 3) L1-L4, R1-R4
├── leg_marker_names.json
├── blade_editor_Rblade.html       # インタラクティブブレードアノテーションツール
├── blade_editor_lblade2.html
└── ...
```

#### 🔧 インタラクティブステップ：ブレードエッジアノテーション

**手動で完了必須**（各ブレードは一度だけアノテーション、全セッションで共有）

1. **HTMLエディタを開く**：
   ```bash
   open /Volumes/KINGSTON/P7_output/P7_1/blade_editor_Rblade.html
   ```

2. **エッジ順序をアノテーション**：
   - **Edge 1**を選択、ブレード第1エッジのマーカーを順番にクリック（先端→根元、または逆）
   - **Edge 2**に切り替え、ブレード第2エッジのマーカーを**同じ方向**でクリック
   - 両エッジの方向が一致していることを確認（両方tip→baseまたは両方base→tip）

3. **JSONをエクスポート**：
   - **Export JSON**をクリック
   - `blade_polygon_order_Rblade.json`として保存
   - `/Volumes/KINGSTON/P7_output/P7_1/`ディレクトリに配置

4. **他のブレードを繰り返し**：
   - lblade2が存在する場合、上記手順を繰り返して`blade_polygon_order_lblade2.json`を生成

**キーボードショートカット**：
- `1` / `2`：Edge 1/2切り替え
- `Z`：取り消し
- `R`：ビューリセット
- 左ドラッグ：回転、右ドラッグ：パン、スクロール：ズーム

---

### フェーズ2：ブレードエッジ抽出 + cam19リファインメント

**目的**：CSVからブレード3D軌跡を抽出 + cam19外部パラメータ最適化

#### コマンド

```bash
# P7_1のJSONを他セッションに共有してからバッチ抽出
python workflow/process_blade_session.py \
    /Volumes/KINGSTON/P7_mocap \
    -o /Volumes/KINGSTON/P7_output \
    --batch \
    --share_json P7_1
```

#### 出力（セッションごと）

```
P7_output/P7_1/
├── Rblade_edge1.npy               # (N, M, 3) Edge 1生軌跡
├── Rblade_edge2.npy               # (N, M, 3) Edge 2生軌跡
├── Rblade_edges.npy               # (N, K, 2, 3) リサンプル整列済みエッジ
├── Rblade_marker_names.json
├── lblade2_edge1.npy
├── lblade2_edge2.npy
├── lblade2_edges.npy
└── lblade2_marker_names.json
```

**重要**：`*_edges.npy`はGT分配用の最終データ（均等間隔ポイントペアにリサンプル済み）

#### 🔧 インタラクティブステップ：cam19外部パラメータ最適化

**目的**：PrimeColorカメラの外部パラメータ（内部パラメータ + 外部パラメータ）を最適化し、mocapマーカー投影をビデオフレームに正確に整列

**セッション選択**：**最大モーション範囲**のセッション（例：P7_4）を選択、一度最適化して全セッションに適用

```bash
python post_calibration/refine_extrinsics.py \
    --markers /Volumes/KINGSTON/P7_output/P7_4/body_markers.npy \
    --names /Volumes/KINGSTON/P7_output/P7_4/body_marker_names.json \
    --video /Volumes/KINGSTON/P7_output/P7_4/video.mp4 \
    --camera /Volumes/KINGSTON/P7_output/P7_4/cam19_initial.yaml \
    --output /Volumes/KINGSTON/P7_output/P7_4/cam19_refined.yaml \
    --no-sync
```

**操作手順**：
1. **クリアフレームを見つける**：`f`を押してマーカーがクリアで安定したフレームを自動検索
2. **マーカーペアをアノテーション**：
   - 3Dマーカー（左リスト）を左クリック
   - ビデオ内の対応する実際の位置を右クリック
   - 最低**6マーカーペア**繰り返し（8-10推奨）
3. **パラメータ最適化**：
   - `O`を押す：scipy最適化使用（14パラメータ：内部パラメータfx,fy,cx,cy + 歪みk1-k6 + 外部パラメータrvec,tvec）
   - `P`を押す：solvePnP使用（外部パラメータのみ、4+ペア必要）
4. **投影検証**：
   - `[` / `]`でフレーム切り替え、投影が常に整列しているか確認
   - エラーが大きい場合、マーカーペアを追加するか再最適化
5. **エクスポート**：`e`を押して`cam19_refined.yaml`を保存

**キーボードショートカット要約**：
- `f`：安定フレーム自動検索
- `Space`：再生/一時停止
- `[` / `]`：前/次のフレーム
- `,` / `.`：前/次の10フレーム
- `O`：scipy最適化（推奨）
- `P`：solvePnP最適化
- `u`：最後のマーカーペアを取り消し
- `c`：全ペアクリア
- `e`：YAMLエクスポート
- `q`：終了

**目標**：再投影誤差 < 2.0ピクセル（理想的 < 1.5ピクセル）

---

### フェーズ3：GoPro完全パイプライン

**目的**：GoPro同期 + PrimeColor同期 + 17カメラ共同キャリブレーション + YAML生成 + GT分配

**全P7セッションをワンコマンド実行**：

```bash
python workflow/process_p7_complete.py \
    --organized_dir /Volumes/FastACIS/csl_11_5/organized \
    --mocap_dir /Volumes/KINGSTON/P7_output \
    --output_dir /Volumes/FastACIS/csl_11_5/synced \
    --anchor_video /Volumes/FastACIS/csl_11_5/organized/qr_sync.mp4 \
    --calibration_session P7_1 \
    --start_time 707 \
    --duration 264 \
    --sessions P7_1 P7_2 P7_3 P7_4 P7_5
```

**注意**：
- ✅ `--cam19_refined`パラメータはオプション（`P7_output/*/cam19_refined.yaml`を自動検索）
- ✅ `--calibration_session`：ChArucoボードが**安定してクリア**なセッションをキャリブレーション用に選択
- ✅ `--start_time` / `--duration`：キャリブレーション用時間範囲（秒）、ボードが安定したセグメントを選択

#### パイプライン自動実行ステップ

**フェーズ3.1：GoPro QR同期**（~5分/セッション）
- QRアンカービデオを使用して全16台のGoProを時間同期
- 出力：`P7_X_sync/cameras_synced/cam1-18/*.MP4`（同期済み、60fps）
- スキップロジック：`meta_info.json`が存在する場合スキップ

**フェーズ3.2：PrimeColor同期**（~2分/セッション）
- GoProタイムラインに基づいてPrimeColor 120fpsビデオを60fpsにリサンプル
- 出力：
  - `cam19/primecolor_synced.mp4`（60fps）
  - `cam19/sync_mapping.json`（時間マッピング）
- スキップロジック：出力ファイルが存在する場合スキップ

**フェーズ3.3：17カメラ共同キャリブレーション**（~15分、calibration_sessionのみ）
- フレーム抽出（5 fps、指定時間範囲）
- ChArucoボード安定フレーム検出
- `multical`共同最適化実行、`calibration.json`生成
- **目標RMS**：< 1.6ピクセル（優秀）、< 2.5ピクセル（許容）
- スキップロジック：`calibration.json`が存在する場合スキップ

**フェーズ3.4：個別YAML生成**（~1分）
- 組み合わせ：
  - `calibration.json`（GoProカメラ間外部パラメータ、全セッション共有）
  - `cam19_refined.yaml`（Mocap → cam19、パーティシパント全体）
- 17カメラYAML生成：`cam1.yaml`, ..., `cam18.yaml`, `cam19.yaml`
- 出力場所：`individual_cam_params/`

**フェーズ3.5：GT分配**（~1分/セッション）
- シンボリックリンク作成：
  - `cam19/skeleton_h36m.npy` → `/Volumes/KINGSTON/P7_output/P7_X/skeleton_h36m.npy`
  - `cam19/Rblade_edges.npy` → `/Volumes/KINGSTON/P7_output/P7_X/Rblade_edges.npy`
  - `cam19/lblade2_edges.npy` → `/Volumes/KINGSTON/P7_output/P7_X/lblade2_edges.npy`
  - `cam19/aligned_edges.npy` → プライマリブレード（Rblade優先）
- `distribute_gt.py`呼び出し、120fps mocapデータを各GoPro 60fpsタイムラインにリサンプル
- 出力：`cam*/gt/skeleton.npy`、`cam*/gt/blade_edges.npy`、`cam*/gt/valid_mask.npy`

---

## 検証と最適化ツール

### 1. GT時間整列検証

**目的**：スケルトン投影がビデオフレームと正確に整列しているか確認（時間同期の正確性）

```bash
python post_calibration/verify_gt_offset.py \
    --session_dir /Volumes/FastACIS/csl_11_5/synced/P7_1_sync/cameras_synced \
    --camera cam1 \
    --start 60 \
    --duration 10
```

**操作**：
- `Space`：再生/リプレイ
- `[` / `]`：オフセット調整±1フレーム
- `,` / `.`：オフセット調整±0.5フレーム
- `e`：オフセットを`camera_offsets.json`に保存してGT自動再分配
- `q`：終了

**目標**：スケルトン関節が常にアスリートの体に重なり、明らかな遅延や進みがない

---

### 2. cam19可視化検証

**目的**：cam19リファインメント効果を検証、スケルトン + ブレードエッジ投影品質を表示

```bash
python post_calibration/verify_cam19_gt.py \
    --video /Volumes/KINGSTON/P7_output/P7_1/video.mp4 \
    --camera_yaml /Volumes/KINGSTON/P7_output/P7_4/cam19_refined.yaml \
    --gt_dir /Volumes/KINGSTON/P7_output/P7_1/ \
    --start 30 \
    --duration 10 \
    --scale 0.5 \
    --output cam19_P7_1_vis.mp4
```

**出力**：スケルトン + ブレード投影オーバーレイ付きビデオ（全ブレード自動検出）

**特徴**：
- `Rblade_edges.npy`、`lblade2_edges.npy`などを自動検出
- 異なるブレードは異なる色を使用
- 120fps元ビデオ、完全フレームレート出力

---

### 3. 個別GoPro外部パラメータ最適化（オプション）

**目的**：特定のGoProの投影品質が悪い場合、個別に外部パラメータを最適化

```bash
python post_calibration/refine_extrinsics.py \
    --markers /Volumes/KINGSTON/P7_output/P7_1/body_markers.npy \
    --names /Volumes/KINGSTON/P7_output/P7_1/body_marker_names.json \
    --video /Volumes/FastACIS/csl_11_5/synced/P7_1_sync/cameras_synced/cam3/GX010281.MP4 \
    --camera /Volumes/FastACIS/csl_11_5/synced/P7_1_sync/cameras_synced/individual_cam_params/cam3.yaml \
    --output /Volumes/FastACIS/csl_11_5/synced/P7_1_sync/cameras_synced/individual_cam_params/cam3_refined.yaml \
    --sync /Volumes/FastACIS/csl_11_5/synced/P7_1_sync/cameras_synced/cam19/sync_mapping.json
```

**操作手順はcam19リファインメントと同じ**

---

## 出力ディレクトリ構造

### Mocap出力

```
/Volumes/KINGSTON/P7_output/
├── P7_1/
│   ├── video.mp4                      # 120fps PrimeColor
│   ├── cam19_initial.yaml
│   ├── skeleton_h36m.npy
│   ├── body_markers.npy
│   ├── leg_markers.npy
│   ├── Rblade_edges.npy               # (N, K, 2, 3)
│   ├── lblade2_edges.npy
│   └── blade_polygon_order_*.json
├── P7_2/, P7_3/, P7_4/, P7_5/
└── P7_4/
    └── cam19_refined.yaml             # リファイン済みcam19（全セッションに適用）
```

### GoPro + キャリブレーション出力

```
/Volumes/FastACIS/csl_11_5/
├── organized/                         # フェーズ0：整理済み生データ
│   ├── qr_sync.mp4
│   └── P7_X/cam*/video.MP4
└── synced/
    └── P7_X_sync/cameras_synced/
        ├── meta_info.json             # GoPro同期メタデータ
        ├── cam1/, ..., cam18/         # 同期済みGoProビデオ
        ├── cam19/
        │   ├── primecolor_synced.mp4  # 60fps
        │   ├── sync_mapping.json
        │   ├── skeleton_h36m.npy      # シンボリックリンク
        │   ├── Rblade_edges.npy       # シンボリックリンク
        │   ├── lblade2_edges.npy      # シンボリックリンク
        │   └── aligned_edges.npy      # シンボリックリンク → プライマリブレード
        ├── original/                  # 抽出フレーム（キャリブレーション用）
        ├── original_stable/           # 安定フレーム
        │   └── calibration.json       # calibration_session（P7_1）のみ
        ├── individual_cam_params/     # カメラごとYAML
        │   ├── cam1.yaml
        │   ├── ...
        │   └── cam19.yaml
        ├── camera_offsets.json        # カメラごと時間オフセット（オプション）
        └── cam*/gt/                   # 分配GTデータ
            ├── skeleton.npy           # (N_gopro, 17, 3)
            ├── blade_edges.npy        # (N_gopro, K, 2, 3)
            ├── valid_mask.npy         # (N_gopro,) bool
            └── gt_info.json
```

---

## トラブルシューティング

### 1. pyzbar警告

**問題**：`⚠️ pyzbar高速化のインストール推奨`

**解決方法**：
```bash
pip install pyzbar
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/zbar/lib:$DYLD_LIBRARY_PATH"
```

### 2. 高RMSエラー

**問題**：`calibration.json` RMS > 2.5ピクセル

**原因**：
- ChArucoボード検出品質が悪い
- 安定フレーム数不足（< 100フレーム）
- 選択した時間範囲のボード動きが速い

**解決方法**：
1. 時間範囲を再選択（`--start_time` / `--duration`）、ボードが長時間安定していることを確認
2. `original_stable/`内のフレーム数を確認
3. `find_stable_boards.py`の`--movement_threshold`を下げる（デフォルト5.0）

### 3. GT時間ミスアライメント

**問題**：スケルトン投影がずれている、遅延または進んでいる

**解決方法**：
```bash
python post_calibration/verify_gt_offset.py \
    --session_dir /path/to/cameras_synced \
    --camera camX
```
オフセット調整後`e`を押して保存しGT再分配

### 4. cam19リファインメント失敗

**問題**：投影誤差が常に大きい

**原因**：
- body_markers.npyが存在しない（一部セッションで欠落）
- 選択したフレームのマーカーが不鮮明または遮蔽
- アノテーションしたマーカーペアが少なすぎる（< 6個）

**解決方法**：
1. `body_markers.npy`が存在することを確認
2. `f`を複数回押して異なるクリアフレームを検索
3. 8-10個のクリアなマーカーペアをアノテーション
4. `P`（solvePnP）ではなく`O`（scipy）を使用

### 5. cam19_refined.yaml未検出

**問題**：`process_p7_complete.py`がcam19_refined.yamlが見つからないと報告

**原因**：フェーズ2が実行されていない、またはリファインメントがエクスポートされていない

**解決方法**：
1. `/Volumes/KINGSTON/P7_output/`下の少なくとも1つのセッションに`cam19_refined.yaml`が含まれていることを確認
2. 存在しない場合、フェーズ2のインタラクティブリファインメントステップを実行
3. 手動でパスを指定：`--cam19_refined /path/to/cam19_refined.yaml`

---

## 完全時間見積もり

| フェーズ | 時間 | 備考 |
|---------|------|------|
| **データ準備** | | |
| GoProビデオ整理 | ~5分 | ファイルコピー/移動 |
| **フェーズ1：Mocap処理** | | |
| AVI→MP4 + CSV→GT | ~30分 | 5セッション直列 |
| ブレードHTMLアノテーション | ~10分 | ブレードごとに1回（手動） |
| **フェーズ2：ブレード抽出 + cam19リファイン** | | |
| ブレードエッジ抽出 | ~5分 | バッチ自動 |
| cam19リファインメント | ~10分 | 1回（手動） |
| **フェーズ3：GoProパイプライン** | | |
| GoPro QR同期 | ~25分 | 5セッション × 5分 |
| PrimeColor同期 | ~10分 | 5セッション × 2分 |
| キャリブレーション（P7_1） | ~15分 | 1回 |
| YAML生成 | ~5分 | 全セッション |
| GT分配 | ~5分 | 全セッション |
| **合計** | **~2時間** | インタラクティブ時間含む |

---

## 次のステップ

パイプライン完了後：

1. ✅ **投影品質検証**：`verify_gt_offset.py`を使用して各カメラの時間整列を確認
2. ✅ **可視化チェック**：`verify_cam19_gt.py`を使用してスケルトン + ブレード投影効果を表示
3. ✅ **トレーニング/推論開始**：`cam*/gt/`内のデータをモデルトレーニングに使用

頑張ってください！🚀
