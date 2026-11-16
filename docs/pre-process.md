# 前処理（pre-process）

Updated: 2026-11-16

ドライブペダル比較用の WAV ファイルについて、比較の前に行った処理を記録する。

## 目的

各ファイルの冒頭には、手動で録音を始めたことによる無録音部分がある。その長さは 0〜2.5 秒とファイルごとに違う。このままでは次の問題がある。

- RMS やスペクトルの平均に無音区間が含まれ、無音の長さによって値がずれる
- 対応する時刻同士を比べられないため、減衰カーブや時間変化を重ねて比較できない

そこで、全ファイルの立ち上がり時刻を揃え、同じ長さで切り出す。

## 入力ファイル

| 項目 | 内容 |
|---|---|
| 場所 | `wav/*.wav`（11 ファイル） |
| 形式 | 48kHz / 24bit / 2ch（全ファイル共通） |
| 長さ | 10.0〜14.3 秒（ファイルごとに違う） |
| 中身 | ギターの演奏を Ditto 2 にループとして録音し、それを毎回再生して各ペダルを掛けたもの。音源は全ファイルで同じ。演奏は、単音（基音約 221Hz、A3 付近）を 1 回鳴らして減衰させたもの。`Raw.wav` はペダルなし |
| 音量 | 録音後、ペダルごとに音の大きさが違ったため、Logic Pro で Gain プラグインを挿し、ピークが同程度になるように調整してある。前処理では変更しない |
| ペダルの設定 | 全ペダルとも、ゲインと EQ のつまみは 12 時。Riverside は Mid Push と High/Low のトグルを切り替えて 3 通り録音した（下表） |

### 録音経路

全ファイルとも、次の経路で録音した。Raw は 3 の歪みエフェクターを通していない。

| 順 | 機材 | 設定 |
|---:|---|---|
| 1 | Ditto 2（ルーパー） | ギターの演奏を録音したループを再生する。全ファイルで同じループを使った |
| 2 | Strymon Compadre | オフ（バッファーのみ通す） |
| 3 | 歪みエフェクター（比較対象） | ゲインと EQ のつまみは 12 時 |
| 4 | DSM & Humboldt Simplifier MK-II | Preamp、Power Amp ともに MS-Brit。Cabinet は Stack、Blue |
| 5 | UAFX Orion Tape Echo（Simplifier MK-II の Send/Return に接続） | エコーはオフ（バイパス）。Preamp オン、Bypass は Trail |

録音後、Logic Pro でピークを揃えるゲイン調整をした（上の表の「音量」）。

Raw を含む全ファイルに、Simplifier MK-II（アンプとキャビネットのシミュレーション）と Orion のプリアンプによる色付けが入っている。解析で「Raw との差」を見るのは、この共通の色付けを差し引いて、歪みエフェクターによる違いだけを見るためでもある。

### 対象ペダルと表記

ドキュメントでは、見出しと本文の初出に正式名を、図表とそれ以外の本文に短縮名を使う。

| ファイル | 正式名 | 短縮名 |
|---|---|---|
| `Raw.wav` | ペダルなし | Raw |
| `Broadcast-AP-II-Ge.wav` | Hudson Electronics Broadcast AP-II（Germanium） | Broadcast Ge |
| `Broadcast-AP-II-Silicon.wav` | Hudson Electronics Broadcast AP-II（Silicon） | Broadcast Si |
| `DS-1.wav` | BOSS DS-1W（S-mode） | DS-1W |
| `Distortion-plus.wav` | MXR Distortion+ | Distortion+ |
| `PPSE-Classic.wav` | Vin-Antique PPSE Classic | PPSE Classic |
| `Riverside-low.wav` | Strymon Riverside（Low） | Riverside low |
| `Riverside-low-mid.wav` | Strymon Riverside（Low + Mid Push） | Riverside low-mid |
| `Riverside-high.wav` | Strymon Riverside（High） | Riverside high |
| `SD-1.wav` | BOSS SD-1W（S-mode） | SD-1W |
| `Soul-Driven.wav` | Xotic Soul Driven | Soul Driven |

Riverside の 3 ファイルの設定は次のとおり。

| ファイル | High/Low | Mid Push |
|---|---|---|
| `Riverside-low.wav` | Low | オフ |
| `Riverside-low-mid.wav` | Low | オン |
| `Riverside-high.wav` | High | オフ（plain） |

入力ファイルを確認して、次のことが分かった。

- 全ファイルのエンベロープ（音量の時間変化）が `Raw.wav` と強く相関する（相関係数 0.83〜0.99）。Ditto 2 の同じループを音源にしたことと合っている
- ループには、音の約 1 秒前に小さなノイズ（ピッキング前の接触音と思われる）が録音されている。録音開始が遅かった `Broadcast-AP-II-Ge.wav`、`Riverside-high.wav`、`Soul-Driven.wav` には入っていない
- L/R の相関は 0.97〜0.98 で、ほぼモノラル
- 全ファイルで 5〜6kHz より上がほぼない。録音経路にある Simplifier MK-II のキャビネットシミュレーション（Stack、Blue）で高域がカットされていると考えられる

## 処理手順

スクリプト：`tools/align_trim.py`

```sh
uv run --with numpy --with scipy --with soundfile python tools/align_trim.py
```

引数を省略すると、`wav/` を読み込んで `wav/aligned/` に書き出す。

1. エンベロープの計算：L/R を平均してモノラルにし、80〜5000Hz のバンドパスフィルタを通す。その絶対値に 50Hz のローパスフィルタを掛けてエンベロープとする
2. Raw のアタック検出：エンベロープがピーク比 -12dB を最初に超えた点を探す。そこから最大 50ms さかのぼり、ピーク比 -30dB を下回っている最後の点の次をアタック開始とする
3. おおよその位置の推定：各ファイルと `Raw.wav` のエンベロープの相互相関から時間のずれを求め、Raw のアタック位置にそのずれを加えて、おおよその位置とする
4. 各ファイルのアタック検出：おおよその位置の前後 150ms に範囲を絞り、手順 2 と同じ方法でアタック開始を検出する
5. ノイズフロアの測定：アタック開始の 0.1 秒前までの区間を 50ms ごとに区切り、各区間の RMS の中央値を求める
6. 切り出し：アタック開始の 50ms 前から、全ファイル共通の長さで切り出す。長さは、最も短く取れるファイルに合わせる
7. フェードイン：クリックノイズを防ぐため、先頭に 5ms の線形フェードインを掛ける
8. 書き出し：`wav/aligned/` に元と同じファイル名・形式（24bit）で書き出す。ゲインは変更しない

### パラメータ

| 名前 | 値 | 意味 |
|---|---|---|
| `PRE` | 0.05 秒 | アタック開始の前に残す長さ |
| `FADE` | 0.005 秒 | フェードインの長さ |
| `ATTACK_DB` | -12dB | アタックを検出する閾値（ピーク比） |
| `ONSET_DB` | -30dB | アタック開始とみなす閾値（ピーク比） |
| `BACK` | 0.05 秒 | アタック検出点からさかのぼる最大の長さ |
| `SEARCH` | 0.15 秒 | おおよその位置から検出する範囲（前後） |

## 検討して採用しなかった方法

| 方法 | 採用しなかった理由 |
|---|---|
| 閾値による単純な無音トリム（`ffmpeg silenceremove` など） | ノイズフロアがファイルごとに違うため、開始点の判定がずれる。また、音の前の小さなノイズを開始点と誤判定する |
| 最初に音が出た点で揃える | 音の前の小さなノイズが入っているファイルと入っていないファイルで、約 1 秒ずれる |
| 範囲を絞らないアタック検出 | `SD-1.wav` は音の圧縮が強く、音の前の小さなノイズもピーク比 -12dB を超えるため、誤検出した |
| 相互相関だけで揃える | 歪みによってエンベロープの形が変わるため、数 ms〜十数 ms の誤差が出る |

## 結果

共通の切り出し長は 8.336 秒（アタック開始前の 50ms を含む）。

| ファイル | 元ファイルでのアタック開始 [秒] | 相互相関との差 [ms] | ノイズフロア [dBFS] |
|---|---:|---:|---:|
| Broadcast-AP-II-Ge.wav | 0.713 | -1.3 | -66.4 |
| Broadcast-AP-II-Silicon.wav | 1.714 | -0.8 | -65.8 |
| DS-1.wav | 2.054 | -7.6 | -59.1 |
| Distortion-plus.wav | 1.980 | -9.3 | -60.6 |
| PPSE-Classic.wav | 2.155 | -2.9 | -70.3 |
| Raw.wav | 2.108 | 0.0 | -61.5 |
| Riverside-high.wav | 0.385 | -3.3 | -66.5 |
| Riverside-low-mid.wav | 2.536 | -1.8 | -68.8 |
| Riverside-low.wav | 2.271 | -0.9 | -66.3 |
| SD-1.wav | 2.109 | -13.6 | -65.1 |
| Soul-Driven.wav | 0.705 | -18.9 | -55.1 |

「相互相関との差」は、検出したアタック開始と、相互相関から求めたおおよその位置との差。

### 検証

`wav/aligned/` の各ファイルについて、エンベロープ（200Hz ローパス）が各閾値を超える時刻を測った。

| ファイル | -30dB [ms] | -12dB [ms] | -6dB [ms] |
|---|---:|---:|---:|
| Broadcast-AP-II-Ge.wav | 53.6 | 56.9 | 57.6 |
| Broadcast-AP-II-Silicon.wav | 54.1 | 56.8 | 57.6 |
| DS-1.wav | 46.4 | 61.1 | 62.4 |
| Distortion-plus.wav | 46.4 | 62.3 | 63.4 |
| PPSE-Classic.wav | 44.6 | 57.5 | 58.4 |
| Raw.wav | 55.5 | 56.8 | 57.4 |
| Riverside-high.wav | 45.0 | 57.3 | 58.2 |
| Riverside-low-mid.wav | 53.7 | 56.7 | 57.4 |
| Riverside-low.wav | 55.2 | 56.6 | 57.2 |
| SD-1.wav | 51.9 | 66.6 | 68.0 |
| Soul-Driven.wav | 48.3 | 70.2 | 72.6 |

- アタックが始まる時刻（-30dB）は 45〜56ms に収まり、揃いの誤差は約 ±6ms
- ピークに近づく時刻（-6dB）は、`SD-1.wav`（68ms）と `Soul-Driven.wav`（73ms）だけ遅い。立ち上がりの始まりは揃っているので、ずれではなく「アタックがなだらか」というペダルの特性と考えられる。この点は解析で確認した（[analysis.md](analysis.md) の C2〜C4）

## 出力

| 場所 | 内容 |
|---|---|
| `wav/aligned/*.wav` | 前処理後のファイル（8.336 秒、48kHz / 24bit / 2ch）。スクリプトで作り直せるため、リポジトリーには含めない |
| `tools/align_trim.py` | 前処理スクリプト |

## 注意点

- 切り出し後のファイルには、音の前の小さなノイズは含まれない
- ノイズフロアは元ファイルの立ち上がり前の区間で測った。切り出し後のファイルでは測れない
- 録音を追加・差し替えた場合は、スクリプトを再実行する。共通の長さは最も短く取れるファイルで決まるため、全ファイルの長さが変わることがある
