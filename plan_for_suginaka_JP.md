# CSL Pipeline 残作業計画

**担当: 杉中さん**
**作成日: 2026-02-09**
**参考: `workflow/P7_complete_workflow_JP.md`（ツールの詳細な使い方）**

---

## 概要

| 参加者 | 状態 | 残作業 |
|--------|------|--------|
| P4_1 ~ P5_2 | 完了 | なし |
| P5_3, P5_4, P5_5 | カメラパラメータ + GT生成済み | キャリブレーション＆同期の検証 |
| P6_1 ~ P6_5 | カメラパラメータ + GT生成済み | キャリブレーション＆同期の検証 |
| P7_1 ~ P7_5 | パイプライン完了 | 個別GoProパラメータのrefine + 同期チェック |
| P8_1 ~ P8_? | 未着手 | フルパイプライン処理 |

## データ配置

| ボリューム | 内容 | パスパターン |
|-----------|------|-------------|
| **T7** | P4-P6 Mocap出力（スケルトン、マーカー、ブレードエッジ、cam19_refined.yaml） | `/Volumes/T7/csl/PX_Y/` |
| **T7** | P7 Mocap出力（P7_output） | `/Volumes/T7/P7_output/P7_X/` |
| **HumanDATA** | 同期済みGoProビデオ、キャリブレーション、個別カメラパラメータ、GTフォルダ | `/Volumes/HumanDATA/Prohuman/synced/PX_Y_sync/cameras_synced/` |

---

## タスク1: P5_3, P5_4, P5_5 および P6_1~P6_5 の検証

これらのセッションにはカメラパラメータとGTデータが既に配置されています。以下を検証する必要があります：
1. **キャリブレーション（投影）**: スケルトン関節がビデオ内の人体と一致しているか
2. **同期（タイミング）**: 時間的な遅延や進みがないか

### 手順

各セッション（P5_3, P5_4, P5_5, P6_1, P6_2, P6_3, P6_4, P6_5）について：

#### 1. 同期チェック

```bash
python post_calibration/verify_gt_offset.py \
    --session_dir /Volumes/HumanDATA/Prohuman/synced/PX_Y_sync/cameras_synced \
    --camera cam1 \
    --start 60 \
    --duration 10
```

- ビデオを再生し、スケルトンオーバーレイが時間的に整列しているか確認
- タイミングがずれている場合：`[` / `]` でオフセット調整後、`e` で保存してGT自動再分配
- 複数のカメラ（cam1, cam5, cam10など）をチェック

#### 2. キャリブレーションチェック（投影品質）

同期検証ツール使用中に、スケルトンが人体と空間的にも一致しているか確認（タイミングだけでなく）。

**特定のカメラのキャリブレーションがおかしい場合：**

以下のトラブルシューティング手順に従ってください：

1. **前のセッションからパラメータをコピー**: 例えばP5_3/cam3がおかしい場合、P5_2の`individual_cam_params/`から`cam3.yaml`をP5_3にコピー
2. **まだおかしい場合、次のセッションを試す**: P5_4の`individual_cam_params/`から`cam3.yaml`をコピー
3. **まだおかしい場合、再refine**: インタラクティブリファインメントツールを実行：
   ```bash
   python post_calibration/refine_extrinsics.py \
       --session PX_Y --cam camN \
       --markers-base /Volumes/T7/csl \
       --synced-base /Volumes/HumanDATA/Prohuman/synced
   ```
4. カメラYAMLを更新した後、そのセッションのGTを再分配

### P5_4に関する注意

P5_4には**body_markers.npyがありません**。そのため`refine_extrinsics.py`を実行できません。P5_4でキャリブレーションに問題がある場合：
- **P5_3**または**P5_5**の対応するカメラYAMLを使用してください
- YAMLファイルをコピーし、投影を目視確認すれば完了

### カメラ修正のワークフロー

```
PX_Y / camN で問題を検出
    ↓
PX_(Y-1) から camN.yaml を PX_Y/individual_cam_params/ にコピー
    ↓
再可視化 → 投影OK？
    ├── はい → 完了
    └── いいえ → PX_(Y+1) から camN.yaml をコピー
                  ↓
                  再可視化 → OK？
                  ├── はい → 完了
                  └── いいえ → refine_extrinsics.py を実行（body_markers.npyがある場合）
                                ↓
                                GTを再分配
```

---

## タスク2: P7 個別GoProリファインメント

P7パイプラインは完了済み（同期ビデオ、キャリブレーション、GT分配）。ただし、個別GoProカメラパラメータは**未refine**で、共同キャリブレーションからの直接出力です。

### 手順

#### 1. P7_4で全GoProカメラをrefine

P7_4は動作範囲が広く、body_markers.npyがあります。各GoProカメラ（cam1~cam18、cam19はスキップ）をrefine：

```bash
# 各カメラについて（cam1, cam2, cam3, ..., cam18、cam13/cam14はスキップ）：
python post_calibration/refine_extrinsics.py \
    --session P7_4 --cam camN \
    --markers-base /Volumes/T7/P7_output \
    --synced-base /Volumes/HumanDATA/Prohuman/synced
```

各カメラについて：
1. `f` を押してマーカーが見えるクリアなフレームを検索
2. 3Dマーカーを左クリック、ビデオ内の対応位置を右クリック
3. 最低6-8個のマーカーペアをアノテーション
4. `O` を押して最適化（scipy、推奨）
5. `[`/`]` でフレーム間を確認
6. `e` を押してエクスポート

#### 2. refine済みパラメータを他のP7セッションにコピー

P7_4で全カメラをrefineした後、YAMLを他のセッションにコピー：

```bash
# P7_4のindividual_cam_paramsをP7_1, P7_2, P7_3, P7_5にコピー
for session in P7_1 P7_2 P7_3 P7_5; do
    cp /Volumes/HumanDATA/Prohuman/synced/P7_4_sync/cameras_synced/individual_cam_params/cam*.yaml \
       /Volumes/HumanDATA/Prohuman/synced/${session}_sync/cameras_synced/individual_cam_params/
done
```

#### 3. 全P7セッションのGTを再分配

カメラパラメータ更新後、GTの再分配が必要：

```bash
for session in P7_1 P7_2 P7_3 P7_4 P7_5; do
    python scripts/distribute_gt.py \
        --session_dir /Volumes/HumanDATA/Prohuman/synced/${session}_sync/cameras_synced
done
```

#### 4. 同期を検証

```bash
python post_calibration/verify_gt_offset.py \
    --session_dir /Volumes/HumanDATA/Prohuman/synced/P7_1_sync/cameras_synced \
    --camera cam1
```

複数のセッションの複数のカメラをチェック。タイミングがずれている場合は調整して`e`。

#### 5. 個別問題カメラの修正（必要に応じて）

P7_4のパラメータをコピーした後、特定のセッションの特定のカメラがおかしい場合：
- そのセッションでそのカメラを個別にrefine
- または隣接セッションのパラメータを試す

---

## タスク3: P8 フルパイプライン処理

P8は新しい参加者で、ゼロからの完全処理が必要です。Mocapデータはエクスポート済みです。

### 前提条件

1. **P8 mocapデータを確認**: KINGSTONまたはT7でエクスポート済みMotiveデータ（AVI + CSV + .mcal）を見つける
2. **P8 GoProデータを確認**: 生GoProビデオ（カメラごと構造）を見つける

### 手順

`workflow/P7_complete_workflow_JP.md`の完全ワークフローに従い、P7をP8に置き換えてください：

#### フェーズ0: データ準備

1. **mocapデータを標準構造に整理**:
   ```
   P8_mocap/
   ├── P8_1/
   │   ├── *.avi          (PrimeColorビデオセグメント)
   │   └── *.csv          (Motiveエクスポート)
   ├── P8_2/, P8_3/, ...
   └── *.mcal             (OptiTrackキャリブレーション、親ディレクトリ)
   ```

2. **GoProデータをカメラごとからセッションごとに整理**:
   ```bash
   python workflow/organize_gopro_videos.py \
       --input /path/to/P8_gopro \
       --output /Volumes/FastACIS/csl_11_5/organized \
       --participant P8 \
       --dry-run
   # 確認後、--dry-runなしで実行
   ```

#### フェーズ1: Mocap処理

```bash
python workflow/process_mocap_session.py \
    /path/to/P8_mocap \
    -o /path/to/P8_output \
    --batch
```

その後：ブレードHTMLエディタを開き、エッジをアノテーション、JSONをエクスポート（詳細はワークフローのドキュメント参照）。

#### フェーズ2: ブレード抽出 + cam19リファインメント

```bash
python workflow/process_blade_session.py \
    /path/to/P8_mocap \
    -o /path/to/P8_output \
    --batch \
    --share_json P8_1
```

その後：`refine_extrinsics.py`をcam19に対して実行（動作範囲が最も広いセッションを選択）。

#### フェーズ3: GoPro完全パイプライン

```bash
python workflow/process_p7_complete.py \
    --organized_dir /Volumes/FastACIS/csl_11_5/organized \
    --mocap_dir /path/to/P8_output \
    --output_dir /Volumes/FastACIS/csl_11_5/synced \
    --anchor_video /Volumes/FastACIS/csl_11_5/organized/qr_sync.mp4 \
    --calibration_session P8_2 \
    --start_time <charuco開始秒数> \
    --duration <charuco持続秒数> \
    --sessions P8_1 P8_2 P8_3 P8_4 P8_5
```

`--calibration_session`、`--start_time`、`--duration`の決め方：GoProビデオを開いてChArucoボードが静止している時間帯を見つけてください。ワークフローのドキュメントの「決め方」セクションを参照。

#### フェーズ4: 検証

上記タスク1・2と同様：全セッション・全カメラのキャリブレーション + 同期を検証。

---

## ヒントとコツ

### インタラクティブツール キーリファレンス

| キー | 機能 |
|------|------|
| `f` | 安定フレーム自動検索（refine_extrinsics） |
| `Space` | 再生/一時停止 |
| `[` / `]` | 前/次のフレーム |
| `,` / `.` | オフセット調整 または 10フレームジャンプ |
| `O` | scipy最適化（推奨） |
| `P` | solvePnP最適化 |
| `e` | エクスポート / 保存 |
| `u` | 最後のマーカーペアを取り消し |
| `c` | 全ペアクリア |
| `q` | 終了 |

### AIに質問するべき場合

- `refine_extrinsics.py`が収束しない場合（8+マーカーペアでもエラーが大きい）
- P8キャリブレーションの`--start_time`/`--duration`が分からない場合
- GT分配が失敗したり予期しない結果になった場合
- コマンドの構文について不明な点がある場合は `workflow/P7_complete_workflow_JP.md` を参照

---

## チェックリスト

### P5 + P6 検証
- [ ] P5_3: 同期チェック + キャリブレーションチェック
- [ ] P5_4: 同期チェック + キャリブレーションチェック（refine不可、必要ならP5_3/P5_5のパラメータ使用）
- [ ] P5_5: 同期チェック + キャリブレーションチェック
- [ ] P6_1: 同期チェック + キャリブレーションチェック
- [ ] P6_2: 同期チェック + キャリブレーションチェック
- [ ] P6_3: 同期チェック + キャリブレーションチェック
- [ ] P6_4: 同期チェック + キャリブレーションチェック
- [ ] P6_5: 同期チェック + キャリブレーションチェック

### P7 リファインメント
- [ ] P7_4で全GoProカメラをrefine（cam1~cam18、cam13/14/19はスキップ）
- [ ] refine済みパラメータをP7_1, P7_2, P7_3, P7_5にコピー
- [ ] 全P7セッションのGTを再分配
- [ ] P7セッションの同期を検証
- [ ] 個別問題カメラを修正

### P8 フル処理
- [ ] P8 mocapデータの確認と整理
- [ ] P8 GoProデータの確認と整理
- [ ] フェーズ1: Mocap処理 + ブレードアノテーション
- [ ] フェーズ2: ブレード抽出 + cam19リファインメント
- [ ] フェーズ3: GoProパイプライン（同期 + キャリブレーション + GT）
- [ ] 全P8セッションのキャリブレーション + 同期を検証
