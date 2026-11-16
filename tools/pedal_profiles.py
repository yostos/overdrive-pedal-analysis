"""ペダルごとの分析（docs/pedals.md 用）。

各ペダルについて、Raw とほかのペダル（灰色）を背景に、そのペダルだけを強調した図を 1 枚作る。
あわせて、指標ごとの順位（Raw を除く 10 台中）と、MFCC 距離で近いペダルを書き出す。

入力: wav/aligned/*.wav、wav/*.wav（analyze.py と同じ）
出力: docs/figures/pedals/*.png、docs/pedal_ranks.csv

使い方:
  uv run --with numpy --with scipy --with soundfile --with matplotlib --with librosa \
      python tools/pedal_profiles.py
"""
import csv
import tempfile
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import correlate

import analyze as A
import align_trim

OUT = A.ROOT / "docs" / "figures" / "pedals"
BG = "#c9c8c2"  # 背景に置くほかのペダルの線

# (キー, 表示名, 大きい方を 1 位にするか)
RANK_KEYS = [
    ("sustain10", "サステイン -10dB", True),
    ("crest_db", "圧縮の強さ（クレストファクタが小さい順）", False),
    ("attack_ms", "アタックのなだらかさ", True),
    ("centroid_1s", "スペクトル重心（1 秒間の平均）", True),
    ("hf_gain", "9〜20 次倍音の増加（Raw 比）", True),
    ("noise_dbfs", "ピークに対するノイズの大きさ", True),
]


def slug(label):
    return label.lower().replace(" ", "-").replace("+", "-plus")


def compute():
    data = A.load()
    sr = data[0]["sr"]
    src = {d["file"]: align_trim.envelope(A.sf.read(A.WAV / d["file"], always_2d=True)[0].mean(1), sr) for d in data}
    ref_on = align_trim.detect_onset(src["Raw.wav"], sr)
    a = src["Raw.wav"] - src["Raw.wav"].mean()
    for d in data:
        b = src[d["file"]] - src[d["file"]].mean()
        lag = int(np.argmax(correlate(b, a, "full", method="fft")) - (len(a) - 1))
        w = int(align_trim.SEARCH * sr)
        g = ref_on + lag
        d["onset_src"] = align_trim.detect_onset(src[d["file"]], sr, max(g - w, 0), g + w)
    # 指標の計算は analyze.py の関数をそのまま使う（図は一時フォルダに捨てる）
    with tempfile.TemporaryDirectory() as tmp:
        A.FIG = Path(tmp)
        A.analyze_spectrum(data)
        A.analyze_noise(data)
        A.analyze_time(data)
        A.analyze_dynamics(data)
        A.analyze_distortion(data)
        D = A.analyze_similarity(data)
    for d in data:
        d["hf_gain"] = float(np.mean(d["harm_rel"][8:] - data[0]["harm_rel"][8:]))  # 9〜20 次の平均
    return data, D


def figure(data, i):
    raw, me = data[0], data[i]
    others = [d for j, d in enumerate(data) if j not in (0, i)]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8.5))
    (a1, a2), (a3, a4) = axes

    for d in others:
        a1.plot(d["sm_f"], A.db(d["sm_n"]) - A.db(raw["sm_n"]), color=BG, lw=1)
    a1.axhline(0, color=raw["color"], ls=raw["ls"], lw=1.4, label="Raw")
    a1.plot(me["sm_f"], A.db(me["sm_n"]) - A.db(raw["sm_n"]), color=me["color"], lw=2.2, label=me["label"])
    a1.plot([], [], color=BG, lw=1, label="ほかのペダル")
    A.freq_axis(a1, 40, 6000)
    a1.set_ylabel("Raw とのレベル差 [dB]")
    a1.set_title("スペクトルの Raw との差（全体のパワーを揃えて比較）", loc="left", color=A.INK)
    a1.legend(loc="upper left", fontsize=9)

    for d in others:
        a2.plot(d["env_t"], d["env_db"], color=BG, lw=1)
    a2.plot(raw["env_t"], raw["env_db"], color=raw["color"], ls=raw["ls"], lw=1.4)
    a2.plot(me["env_t"], me["env_db"], color=me["color"], lw=2.2)
    a2.set_xlim(0, raw["env_t"][-1])
    a2.set_ylim(-60, 2)
    a2.set_xlabel("時間 [秒]")
    a2.set_ylabel("ピークからのレベル [dB]")
    a2.set_title("減衰カーブ", loc="left", color=A.INK)

    hn = np.arange(1, A.N_HARM + 1)
    for d in others:
        a3.plot(hn, d["harm_rel"] - raw["harm_rel"], color=BG, lw=1)
    a3.axhline(0, color=raw["color"], ls=raw["ls"], lw=1.4)
    a3.plot(hn, me["harm_rel"] - raw["harm_rel"], color=me["color"], lw=2.2, marker="o", ms=4)
    a3.set_xticks(hn)
    a3.set_xlabel("倍音の次数（1 = 基音）")
    a3.set_ylabel("Raw との差 [dB]")
    a3.set_title("倍音ごとのレベルの Raw との差", loc="left", color=A.INK)

    for d in others:
        a4.plot(d["centroid_t"], d["centroid"], color=BG, lw=1)
    a4.plot(raw["centroid_t"], raw["centroid"], color=raw["color"], ls=raw["ls"], lw=1.4)
    a4.plot(me["centroid_t"], me["centroid"], color=me["color"], lw=2.2)
    a4.set_yscale("log")
    a4.set_yticks([300, 500, 1000, 2000], ["300", "500", "1k", "2k"])
    a4.minorticks_off()
    a4.set_xlim(0, raw["centroid_t"][-1])
    a4.set_xlabel("時間 [秒]")
    a4.set_ylabel("スペクトル重心 [Hz]")
    a4.set_title("スペクトル重心の時間変化", loc="left", color=A.INK)

    fig.suptitle(f"{me['label']}（色）と Raw（黒の破線）、ほかのペダル（灰色）", x=0.01, ha="left", color=A.INK)
    fig.tight_layout()
    fig.savefig(OUT / f"{slug(me['label'])}.png", bbox_inches="tight")
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    data, D = compute()
    pedals = data[1:]
    ranks = {d["label"]: {} for d in pedals}
    for key, _, desc in RANK_KEYS:
        order = sorted(pedals, key=lambda d: d[key], reverse=desc)
        for r, d in enumerate(order, 1):
            ranks[d["label"]][key] = r
    with open(A.ROOT / "docs" / "pedal_ranks.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["label"] + [name for _, name, _ in RANK_KEYS] + ["hf_gain_db", "nearest", "Raw との距離"])
        for i, d in enumerate(data):
            if i == 0:
                continue
            near = [(D[i, j], data[j]["label"]) for j in range(1, len(data)) if j != i]
            near.sort()
            nearest = " / ".join(f"{l}（{v:.0f}）" for v, l in near[:2])
            w.writerow([d["label"]] + [ranks[d["label"]][k] for k, _, _ in RANK_KEYS]
                       + [f"{d['hf_gain']:.1f}", nearest, f"{D[i, 0]:.0f}"])
            print(f"{d['label']:18s} " + " ".join(f"{k}={ranks[d['label']][k]}" for k, _, _ in RANK_KEYS)
                  + f" hf={d['hf_gain']:.1f} near={nearest} raw={D[i, 0]:.0f}")
            figure(data, i)


if __name__ == "__main__":
    main()
