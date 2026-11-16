"""冒頭の無録音部分を除去し、全ファイルの立ち上がりを揃えて同じ長さで切り出す。

- 音量（ゲイン）は変更しない（録音時に dB で揃えてある前提）
- 立ち上がりは単音のアタックを基準にする。エンベロープがピーク比 -12dB を最初に超えた点から
  さかのぼり、ピーク比 -30dB を下回る点（最大 50ms 前まで）をアタック開始とする。
  音源のループ（Ditto 2）には本番の音の約1秒前に小さなノイズがあり、録音開始の早さによって入っていないファイルもあるため、
  最初に音が出た点ではなくアタックで揃える。
  検出範囲は、Raw.wav のアタック位置とエンベロープ相互相関から求めた概略位置の ±SEARCH 秒に限定する
- 立ち上がりの PRE 秒前から、全ファイル共通の長さで切り出し、先頭に短いフェードインを掛ける
- 切り出し前の区間でノイズフロアを測り、レポートに出力する（50ms ごとの RMS の中央値。
  本番の音の前にある小さなノイズのような短い音の影響を受けにくい）

使い方: uv run --with numpy --with scipy --with soundfile python tools/align_trim.py [入力dir] [出力dir]
  入力dir の既定値は wav/、出力dir の既定値は wav/aligned/（いずれもプロジェクト直下からの相対位置）
"""
import sys
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfiltfilt, correlate

PRE = 0.05          # 立ち上がり前に残す秒数
FADE = 0.005        # フェードイン秒数
ATTACK_DB = -12.0   # アタック検出用のピーク比閾値
ONSET_DB = -30.0    # アタック開始とみなすピーク比閾値
BACK = 0.05         # アタック検出点からさかのぼる最大秒数
SEARCH = 0.15       # 相互相関による概略位置からの検出範囲（±秒）
REF = "Raw.wav"


def envelope(mono, sr):
    bp = butter(4, [80, 5000], "bp", fs=sr, output="sos")
    lp = butter(2, 50, "lp", fs=sr, output="sos")
    return sosfiltfilt(lp, np.abs(sosfiltfilt(bp, mono)))


def detect_onset(env, sr, lo_lim=0, hi_lim=None):
    peak = env.max()
    win = env[lo_lim:hi_lim]
    hit = lo_lim + int(np.argmax(win > peak * 10 ** (ATTACK_DB / 20)))
    lo = max(hit - int(BACK * sr), 0)
    below = np.where(env[lo:hit] < peak * 10 ** (ONSET_DB / 20))[0]
    return lo + int(below[-1]) + 1 if len(below) else lo


def main():
    root = Path(__file__).resolve().parent.parent
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "wav"
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src / "aligned"
    files = sorted(p for p in src.glob("*.wav"))
    data = {}
    for p in files:
        x, sr = sf.read(p, always_2d=True)
        info = sf.info(p)
        env = envelope(x.mean(1), sr)
        data[p.name] = dict(x=x, sr=sr, env=env, subtype=info.subtype)

    sr = data[REF]["sr"]
    assert all(d["sr"] == sr for d in data.values()), "サンプルレートが揃っていない"
    ref = data[REF]
    ref["onset"] = detect_onset(ref["env"], sr)
    a = ref["env"] - ref["env"].mean()
    for d in data.values():
        b = d["env"] - d["env"].mean()
        d["lag"] = int(np.argmax(correlate(b, a, "full", method="fft")) - (len(a) - 1))
        guess = ref["onset"] + d["lag"]
        w = int(SEARCH * sr)
        d["onset"] = detect_onset(d["env"], sr, max(guess - w, 0), guess + w)
    pre = int(PRE * sr)
    length = min(len(d["x"]) - d["onset"] for d in data.values()) + pre
    fade = np.linspace(0, 1, int(FADE * sr))[:, None]

    dst.mkdir(parents=True, exist_ok=True)
    print(f"共通の切り出し長: {length / sr:.3f} 秒（立ち上がり前 {PRE * 1000:.0f}ms を含む）\n")
    print(f"{'file':28s} {'onset[s]':>9s} {'xcorr差[ms]':>11s} {'noise[dBFS]':>11s}")
    for name, d in data.items():
        # 検出した立ち上がりと、相互相関による概略位置との差
        diff_ms = ((d["onset"] - ref["onset"]) - d["lag"]) / sr * 1000
        # ノイズフロア: 立ち上がり 0.1 秒前までを 50ms ごとに区切った RMS の中央値
        seg = d["x"][: max(d["onset"] - int(0.1 * sr), 0)].mean(1)
        n = int(0.05 * sr)
        blocks = seg[: len(seg) // n * n].reshape(-1, n) if len(seg) >= n else seg[None, :]
        noise = 20 * np.log10(np.median(np.sqrt(np.mean(blocks ** 2, axis=1))) + 1e-12)

        start = d["onset"] - pre
        y = d["x"][max(start, 0): start + length].copy()
        if start < 0:  # 立ち上がりが PRE より手前にある場合は先頭を無音で埋める
            y = np.vstack([np.zeros((-start, y.shape[1])), y])
        y[: len(fade)] *= fade
        sf.write(dst / name, y, sr, subtype=d["subtype"])
        flag = "  ← 要確認" if abs(diff_ms) > 20 else ""
        print(f"{name:28s} {d['onset'] / sr:9.3f} {diff_ms:11.1f} {noise:11.1f}{flag}")
    print(f"\n出力先: {dst}")


if __name__ == "__main__":
    main()
