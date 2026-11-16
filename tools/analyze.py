"""ドライブペダル比較の解析（docs/analysis-plan.md の項目 A〜F）。

入力: wav/aligned/*.wav（前処理済み）、ノイズ解析のみ元ファイル wav/*.wav
出力: docs/figures/*.png、docs/metrics.csv、docs/distance_segments.csv

使い方:
  uv run --with numpy --with scipy --with soundfile --with matplotlib --with librosa \
      python tools/analyze.py
"""
from pathlib import Path
import csv
import numpy as np
import soundfile as sf
import librosa
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
from scipy.signal import welch, butter, sosfiltfilt
from scipy.cluster.hierarchy import linkage, dendrogram
from scipy.spatial.distance import squareform

import align_trim  # 立ち上がり検出を前処理と共通にする

ROOT = Path(__file__).resolve().parent.parent
WAV = ROOT / "wav"
ALIGNED = WAV / "aligned"
FIG = ROOT / "docs" / "figures"
PRE = align_trim.PRE  # aligned ファイルでの立ち上がり位置 [秒]

# ---- 表示設定 ------------------------------------------------------------
# 表示名は短縮名。正式名との対応は docs/pre-process.md の「対象ペダルと表記」を参照
# 系統ごとに色（dataviz 参照パレットの固定順）、設定違いは線種で区別する
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6")
PEDALS = [  # (ファイル名, 表示名, 色, 線種)
    ("Raw.wav", "Raw", "#0b0b0b", (0, (4, 2))),
    ("Broadcast-AP-II-Ge.wav", "Broadcast Ge", BLUE, "-"),
    ("Broadcast-AP-II-Silicon.wav", "Broadcast Si", BLUE, (0, (4, 2))),
    ("DS-1.wav", "DS-1W", ORANGE, "-"),
    ("Distortion-plus.wav", "Distortion+", AQUA, "-"),
    ("PPSE-Classic.wav", "PPSE Classic", YELLOW, "-"),
    ("Riverside-low.wav", "Riverside low", MAGENTA, "-"),
    ("Riverside-low-mid.wav", "Riverside low-mid", MAGENTA, (0, (4, 2))),
    ("Riverside-high.wav", "Riverside high", MAGENTA, (0, (1, 1.5))),
    ("SD-1.wav", "SD-1W", GREEN, "-"),
    ("Soul-Driven.wav", "Soul Driven", VIOLET, "-"),
]
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SEQ = LinearSegmentedColormap.from_list("seq", ["#cde2fb", "#86b6ef", "#2a78d6", "#184f95", "#0d366b"])
DIV = LinearSegmentedColormap.from_list("div", ["#2a78d6", "#f0efec", "#e34948"])

plt.rcParams.update({
    "font.family": ["Hiragino Sans", "sans-serif"],
    "font.size": 10, "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False,
    "axes.spines.right": False, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
    "savefig.dpi": 150, "legend.frameon": False, "lines.linewidth": 1.6, "axes.axisbelow": True,
})

# 録音経路で 5〜6kHz より上がカットされているため、5kHz までを区切る
BANDS = [("低域\n<250", 20, 250), ("中低域\n250–500", 250, 500), ("中域\n500–1k", 500, 1000),
         ("中高域\n1k–2k", 1000, 2000), ("高域\n2k–5k", 2000, 5000)]
N_HARM = 20  # 倍音解析で扱う次数（f0≈220Hz で 4.4kHz まで。カットオフより下）
FREQ_TICKS = [50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]
FREQ_LABELS = ["50", "100", "200", "500", "1k", "2k", "5k", "10k", "20k"]


def db(x, floor=1e-12):
    return 10 * np.log10(np.maximum(x, floor))


def freq_axis(ax, lo=40, hi=20000):
    ax.set_xscale("log")
    ax.set_xlim(lo, hi)
    ax.set_xticks([t for t in FREQ_TICKS if lo <= t <= hi])
    ax.set_xticklabels([l for t, l in zip(FREQ_TICKS, FREQ_LABELS) if lo <= t <= hi])
    ax.minorticks_off()
    ax.set_xlabel("周波数 [Hz]")


def legend_outside(ax):
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=9, handlelength=2.8)


def save(fig, name):
    fig.savefig(FIG / name, bbox_inches="tight")
    plt.close(fig)


def octave_smooth(f, p, frac=6, lo=20, hi=24000):
    """1/frac オクターブ幅で平滑化したパワーを対数間隔の中心周波数で返す。"""
    centers = lo * 2 ** (np.arange(0, np.log2(hi / lo), 1 / 48))
    half = 2 ** (1 / (2 * frac))
    out = np.array([p[(f >= c / half) & (f < c * half)].mean() if np.any((f >= c / half) & (f < c * half)) else np.nan
                    for c in centers])
    return centers, out


# ---- 読み込み ------------------------------------------------------------
def load():
    data = []
    for fname, label, color, ls in PEDALS:
        x, sr = sf.read(ALIGNED / fname, always_2d=True)
        data.append(dict(file=fname, label=label, color=color, ls=ls, y=x.mean(1), sr=sr))
    return data


# ---- A. 周波数特性 -------------------------------------------------------
def analyze_spectrum(data):
    for d in data:
        f, p = welch(d["y"], d["sr"], nperseg=8192, noverlap=6144)
        d["psd_f"], d["psd"] = f, p
        d["sm_f"], d["sm"] = octave_smooth(f, p)
        tot = p[(f >= 20)].sum()
        # ピークを揃える調整をしているため、絶対レベルではなく全体のパワーを揃えた形で比べる
        d["sm_n"] = d["sm"] / tot
        d["band_share"] = [p[(f >= lo) & (f < hi)].sum() / tot for _, lo, hi in BANDS]
    raw = data[0]

    fig, ax = plt.subplots(figsize=(10, 5.2))
    for d in data:
        ax.plot(d["sm_f"], db(d["sm"]), color=d["color"], ls=d["ls"], label=d["label"])
    freq_axis(ax)
    ax.set_ylim(-150, -45)
    ax.set_ylabel("パワースペクトル密度 [dB/Hz]")
    ax.set_title("A1. 平均スペクトル（1/6 オクターブ平滑化、ピークを揃えた音量のまま）", loc="left", color=INK)
    legend_outside(ax)
    save(fig, "01_spectrum.png")

    fig, ax = plt.subplots(figsize=(10, 5.2))
    for d in data:
        ax.plot(d["sm_f"], db(d["sm_n"]) - db(raw["sm_n"]), color=d["color"], ls=d["ls"], label=d["label"])
    freq_axis(ax, 40, 6000)  # 7kHz 以上はどのファイルも成分がほぼなく、差に意味がない
    ax.set_ylabel("Raw とのレベル差 [dB]")
    ax.set_title("A2. Raw とのスペクトル差分（全体のパワーを揃えて比較、0dB = Raw）", loc="left", color=INK)
    legend_outside(ax)
    save(fig, "02_spectrum_diff.png")

    # A3: 各帯域のエネルギー比。色は Raw との差（dB）、数値は比率（%）
    share = np.array([d["band_share"] for d in data])
    diff = db(share) - db(share[0])
    lim = np.nanmax(np.abs(diff))
    fig, ax = plt.subplots(figsize=(9, 6))
    im = ax.imshow(diff, cmap=DIV, norm=TwoSlopeNorm(0, -lim, lim), aspect="auto")
    for i in range(share.shape[0]):
        for j in range(share.shape[1]):
            v = share[i, j] * 100
            ax.text(j, i, f"{v:.1f}%" if v >= 0.1 else f"{v:.2f}%", ha="center", va="center", fontsize=9,
                    color="#ffffff" if abs(diff[i, j]) > lim * 0.6 else INK)
    ax.set_xticks(range(len(BANDS)), [b[0] for b in BANDS])
    ax.set_yticks(range(len(data)), [d["label"] for d in data])
    ax.grid(False)
    ax.tick_params(length=0)
    cb = fig.colorbar(im, ax=ax, shrink=0.8)
    cb.set_label("Raw との比率の差 [dB]", color=INK2)
    ax.set_title("A3. 帯域別エネルギー比（数値 = 全体に占める割合）", loc="left", color=INK)
    save(fig, "03_band_levels.png")


# ---- B. 時間変化 ---------------------------------------------------------
def analyze_time(data):
    n_fft, hop = 4096, 512
    specs = []
    for d in data:
        S = np.abs(librosa.stft(d["y"], n_fft=n_fft, hop_length=hop)) ** 2
        specs.append(S)
    gmax = max(S.max() for S in specs)
    freqs = librosa.fft_frequencies(sr=data[0]["sr"], n_fft=n_fft)
    times = librosa.frames_to_time(np.arange(specs[0].shape[1]), sr=data[0]["sr"], hop_length=hop)

    fig, axes = plt.subplots(3, 4, figsize=(15, 9), sharex=True, sharey=True)
    for ax, d, S in zip(axes.flat, data, specs):
        im = ax.pcolormesh(times, freqs[1:], db(S[1:] / gmax), cmap="magma", vmin=-90, vmax=0, shading="auto",
                           rasterized=True)
        ax.set_yscale("log")
        ax.set_ylim(50, 10000)
        ax.set_yticks([100, 1000, 10000], ["100", "1k", "10k"])
        ax.minorticks_off()
        ax.grid(False)
        ax.set_title(d["label"], fontsize=10, color=INK, loc="left")
    axes.flat[-1].remove()
    for ax in list(axes[-1][:3]) + [axes[1, 3]]:
        ax.set_xlabel("時間 [秒]")
        ax.tick_params(labelbottom=True)
    for ax in axes[:, 0]:
        ax.set_ylabel("周波数 [Hz]")
    cax = fig.add_axes([0.80, 0.09, 0.012, 0.16])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label("全ファイル共通の最大値\nからのレベル [dB]", color=INK2)
    fig.suptitle("B1. スペクトログラム（色の尺度は全ペダル共通）", x=0.01, ha="left", color=INK)
    save(fig, "04_spectrogram.png")

    # B2: スペクトル重心（ノイズフロア +15dB 以上のフレームのみ。下回るとノイズの重心を測ってしまう）
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for d, S in zip(data, specs):
        e = S.sum(0)
        c = (freqs[:, None] * S).sum(0) / np.maximum(e, 1e-20)
        c = np.convolve(c, np.ones(9) / 9, mode="same")  # 約 0.1 秒の移動平均
        rms = librosa.feature.rms(y=d["y"], frame_length=n_fft, hop_length=hop)[0]
        c[20 * np.log10(np.maximum(rms, 1e-12)) < d["noise_dbfs"] + 15] = np.nan
        d["centroid_t"], d["centroid"] = times, c
        act = (times > PRE) & (times < PRE + 1.0)
        d["centroid_1s"] = np.nanmean(c[act])
        ax.plot(times, c, color=d["color"], ls=d["ls"], label=d["label"])
    ax.set_yscale("log")
    ax.set_yticks([300, 500, 1000, 2000, 3000], ["300", "500", "1k", "2k", "3k"])
    ax.minorticks_off()
    ax.set_xlim(0, times[-1])
    ax.set_xlabel("時間 [秒]")
    ax.set_ylabel("スペクトル重心 [Hz]")
    ax.set_title("B2. スペクトル重心の時間変化（ノイズフロア +15dB 以上の区間のみ）", loc="left", color=INK)
    legend_outside(ax)
    save(fig, "05_centroid.png")


# ---- C. ダイナミクス -----------------------------------------------------
def analyze_dynamics(data):
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for d in data:
        y, sr = d["y"], d["sr"]
        win, hop = int(0.02 * sr), int(0.01 * sr)
        frames = librosa.util.frame(y, frame_length=win, hop_length=hop)
        rms = np.sqrt((frames ** 2).mean(0))
        t = (np.arange(len(rms)) * hop + win / 2) / sr
        lv = 20 * np.log10(np.maximum(rms, 1e-9) / rms.max())
        d["env_t"], d["env_db"] = t, lv
        ipk = int(np.argmax(lv))
        # 減衰: ピーク後、最後に閾値を上回っていた時刻（少し持ち上がる箇所があっても過小評価しない）
        for thr in (10, 20):
            above = np.where(lv[ipk:] >= -thr)[0]
            last = ipk + above[-1]
            d[f"sustain{thr}"] = (t[last] - t[ipk]) if last < len(lv) - 1 else np.nan
        # アタック: 振幅エンベロープ（200Hz ローパス）が 10% → 90% に上がる時間
        env = sosfiltfilt(butter(2, 200, "lp", fs=sr, output="sos"), np.abs(y))
        pk = env[: int((PRE + 0.5) * sr)].max()
        i10 = np.argmax(env > 0.1 * pk)
        i90 = np.argmax(env > 0.9 * pk)
        d["attack_ms"] = (i90 - i10) / sr * 1000
        # クレストファクタ: 立ち上がりから 2 秒間
        seg = y[int(PRE * sr): int((PRE + 2.0) * sr)]
        d["crest_db"] = 20 * np.log10(np.abs(seg).max() / np.sqrt((seg ** 2).mean()))
        ax.plot(t, lv, color=d["color"], ls=d["ls"], label=d["label"])
    ax.set_xlim(0, data[0]["env_t"][-1])
    ax.set_ylim(-60, 2)
    ax.set_xlabel("時間 [秒]")
    ax.set_ylabel("各ファイルのピークからのレベル [dB]")
    ax.set_title("C1. 減衰カーブ（RMS、窓 20ms）", loc="left", color=INK)
    legend_outside(ax)
    save(fig, "07_envelope.png")

    metrics = [("sustain10", "-10dB まで [秒]"), ("sustain20", "-20dB まで [秒]"),
               ("attack_ms", "アタック 10→90% [ms]"), ("crest_db", "クレストファクタ [dB]")]
    fig, axes = plt.subplots(1, 4, figsize=(15, 5.5), sharey=True)
    ypos = np.arange(len(data))
    for ax, (key, title) in zip(axes, metrics):
        vals = np.array([d[key] for d in data])
        ax.barh(ypos, vals, color=[d["color"] for d in data], height=0.7,
                hatch=None, edgecolor="#fcfcfb", linewidth=2)
        for yi, v in zip(ypos, vals):
            ax.text(v, yi, f" {v:.2f}" if key.startswith("sus") else f" {v:.1f}", va="center", fontsize=8.5, color=INK2)
        ax.set_title(title, fontsize=10, color=INK, loc="left")
        ax.grid(axis="y", visible=False)
        ax.set_xlim(0, np.nanmax(vals) * 1.25)
    axes[0].set_yticks(ypos, [d["label"] for d in data])
    axes[0].invert_yaxis()
    fig.suptitle("C2–C4. ダイナミクス指標", x=0.01, ha="left", color=INK)
    save(fig, "08_dynamics.png")


# ---- D. 歪みの性質（倍音解析） ------------------------------------------
def marker_of(d):
    return "o" if d["ls"] == "-" else ("s" if d["ls"] == (0, (4, 2)) else "^")


def harmonic_levels(y, sr, f0, n=N_HARM):
    """立ち上がりから 2 秒間の倍音ごとのパワー、倍音以外の成分のパワーを返す。"""
    seg = y[int(PRE * sr): int((PRE + 2.0) * sr)]
    nfft = 1 << 18
    P = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), nfft)) ** 2
    f = np.fft.rfftfreq(nfft, 1 / sr)
    lv, mask = [], np.zeros_like(f, dtype=bool)
    for h in range(1, n + 1):
        w = (np.abs(f - h * f0) < f0 * 0.06)
        lv.append(P[w].sum())
        mask |= w
    band = (f >= f0 * 0.5) & (f < (n + 0.5) * f0)
    return np.array(lv), P[band & ~mask].sum()


def analyze_distortion(data):
    sr = data[0]["sr"]
    # 基音: Raw の 150–300Hz で最大のピーク（放物線補間）
    seg = data[0]["y"][int(PRE * sr): int((PRE + 2.0) * sr)]
    nfft = 1 << 18
    P = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), nfft))
    f = np.fft.rfftfreq(nfft, 1 / sr)
    k = np.argmax(np.where((f > 150) & (f < 300), P, 0))
    a, b, c = np.log(P[k - 1:k + 2])
    f0 = (k + 0.5 * (a - c) / (a - 2 * b + c)) * sr / nfft
    for d in data:
        lv, other = harmonic_levels(d["y"], sr, f0)
        d["harm_rel"] = db(lv / lv[0])  # 基音比 [dB]
        d["thd_db"] = db(lv[1:].sum() / lv[0])
        d["even_odd_db"] = db(lv[1::2].sum() / lv[2::2].sum())  # 偶数次(2,4,..) / 奇数次(3,5,..)
        d["hnr_db"] = db(lv.sum() / other)
    hn = np.arange(1, N_HARM + 1)

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 8.5), sharex=True)
    for d in data:
        a1.plot(hn, d["harm_rel"], color=d["color"], ls=d["ls"], marker=marker_of(d), ms=4, label=d["label"])
        a2.plot(hn, d["harm_rel"] - data[0]["harm_rel"], color=d["color"], ls=d["ls"], marker=marker_of(d), ms=4)
    a1.set_ylabel("基音からのレベル [dB]")
    a1.set_title(f"D1. 倍音ごとのレベル（基音 {f0:.1f}Hz、立ち上がりから 2 秒間）", loc="left", color=INK)
    a2.set_ylabel("Raw との差 [dB]")
    a2.set_title("D2. 倍音ごとのレベルの Raw との差（0dB = Raw）", loc="left", color=INK)
    a2.set_xlabel("倍音の次数（1 = 基音）")
    a2.set_xticks(hn)
    legend_outside(a1)
    save(fig, "06_harmonics.png")

    fig, axes = plt.subplots(1, 3, figsize=(15, 5.5), sharey=True)
    ypos = np.arange(len(data))
    for ax, (key, title) in zip(axes, [("thd_db", "倍音比（2〜20 次／基音）[dB]"),
                                       ("even_odd_db", "偶数次／奇数次 [dB]（＋ほど偶数次が多い）"),
                                       ("hnr_db", "倍音／倍音以外の成分 [dB]")]):
        vals = np.array([d[key] for d in data])
        ax.barh(ypos, vals, color=[d["color"] for d in data], height=0.7, edgecolor="#fcfcfb", linewidth=2)
        for yi, v in zip(ypos, vals):
            ax.text(v, yi, f" {v:.1f}" if v >= 0 else f"{v:.1f} ", va="center", ha="left" if v >= 0 else "right",
                    fontsize=8.5, color=INK2)
        ax.axvline(0, color="#c3c2b7", lw=1)
        lo, hi = min(0, vals.min()), max(0, vals.max())
        pad = (hi - lo) * 0.25
        ax.set_xlim(lo - (pad if lo < 0 else 0), hi + pad)
        ax.set_title(title, fontsize=10, color=INK, loc="left")
        ax.grid(axis="y", visible=False)
    axes[0].set_yticks(ypos, [d["label"] for d in data])
    axes[0].invert_yaxis()
    fig.suptitle("D3. 倍音の指標（立ち上がりから 2 秒間）", x=0.01, ha="left", color=INK)
    save(fig, "06b_harmonic_metrics.png")


# ---- E. ノイズ -----------------------------------------------------------
def analyze_noise(data):
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for d in data:
        x, sr = sf.read(WAV / d["file"], always_2d=True)
        y = x.mean(1)
        onset = d["onset_src"]  # 前処理と同じ方法で求めた元ファイルの立ち上がり位置
        seg = y[: max(onset - int(0.1 * sr), 0)]
        # 50ms ごとの RMS の中央値（前処理と同じ定義）
        n = int(0.05 * sr)
        blocks = seg[: len(seg) // n * n].reshape(-1, n)
        d["noise_dbfs"] = 20 * np.log10(np.median(np.sqrt((blocks ** 2).mean(1))))
        # スペクトル: 8192 点のフレームごとのパワーの中央値（短い突発音の影響を避ける）
        nper = 8192
        fr = librosa.util.frame(seg, frame_length=nper, hop_length=1024)
        P = np.abs(np.fft.rfft(fr * np.hanning(nper)[:, None], axis=0)) ** 2
        p = np.median(P, axis=1) / (sr * (np.hanning(nper) ** 2).sum()) * 2
        f = np.fft.rfftfreq(nper, 1 / sr)
        # ヒス: 2–5kHz の帯域レベル（立ち上がり前の区間にある音程成分は 1kHz 付近まで）
        d["hiss_db"] = db(p[(f >= 2000) & (f < 5000)].sum() * (f[1] - f[0]))
        # ハム: 50/60Hz 系の各ピークが周囲（±15Hz）の中央値をどれだけ上回るか、の最大値
        hum = []
        for h in (50, 60, 100, 120, 150, 180):
            k = np.argmin(np.abs(f - h))
            nb = p[(np.abs(f - h) > 4) & (np.abs(f - h) < 15)]
            hum.append(db(p[k - 1:k + 2].max()) - db(np.median(nb)))
        d["hum_db"] = max(hum)
        cf, sm = octave_smooth(f, p, frac=12)
        ax.plot(cf, db(sm), color=d["color"], ls=d["ls"], label=f"{d['label']}（{d['noise_dbfs']:.1f} dBFS）")
    freq_axis(ax, 20, 20000)
    ax.set_ylabel("パワースペクトル密度 [dB/Hz]")
    ax.set_title("E. ノイズのスペクトル（立ち上がり前の区間、1/12 オクターブ平滑化）", loc="left", color=INK)
    legend_outside(ax)
    save(fig, "09_noise.png")


# ---- F. 類似度 -----------------------------------------------------------
def analyze_similarity(data):
    feats = []
    for d in data:
        m = librosa.feature.mfcc(y=d["y"], sr=d["sr"], n_mfcc=14, n_fft=4096, hop_length=1024)[1:]  # c0（音量）を除く
        feats.append(m)
    e = np.abs(librosa.stft(data[0]["y"], n_fft=4096, hop_length=1024)) ** 2
    e = e.sum(0)
    act = e > e.max() * 1e-4  # Raw がピーク比 -40dB 以上の区間を比較対象にする
    n = len(data)
    D = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            D[i, j] = np.linalg.norm(feats[i][:, act] - feats[j][:, act], axis=0).mean()
    labels = [d["label"] for d in data]

    fig, ax = plt.subplots(figsize=(9, 7.5))
    im = ax.imshow(D, cmap=SEQ)
    for i in range(n):
        for j in range(n):
            ax.text(j, i, f"{D[i, j]:.0f}", ha="center", va="center", fontsize=8.5,
                    color="#ffffff" if D[i, j] > D.max() * 0.55 else INK)
    ax.set_xticks(range(n), labels, rotation=45, ha="right")
    ax.set_yticks(range(n), labels)
    ax.grid(False)
    ax.tick_params(length=0)
    cb = fig.colorbar(im, ax=ax, shrink=0.8)
    cb.set_label("MFCC 距離（小さいほど似ている）", color=INK2)
    ax.set_title("F1. ペダル間の距離行列（MFCC）", loc="left", color=INK)
    save(fig, "10_distance.png")

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(15, 6))
    Z = linkage(squareform(D, checks=False), "average")
    dn = dendrogram(Z, labels=labels, orientation="right", ax=a1, color_threshold=0,
                    above_threshold_color=INK2)
    a1.grid(False)
    a1.set_xlabel("MFCC 距離（平均連結法）")
    a1.set_title("F2. 樹形図", loc="left", color=INK)
    # 古典的 MDS
    J = np.eye(n) - 1 / n
    B = -0.5 * J @ (D ** 2) @ J
    w, v = np.linalg.eigh(B)
    idx = np.argsort(w)[::-1][:2]
    X = v[:, idx] * np.sqrt(np.maximum(w[idx], 0))
    expl = w[idx] / w[w > 0].sum() * 100
    span = np.ptp(X, axis=0)
    placed = []
    for d, (px, py) in zip(data, X):
        a2.scatter(px, py, s=90, color=d["color"], marker=marker_of(d), edgecolor="#fcfcfb", linewidth=2, zorder=3)
        # 近くに既にラベルがある点は、ラベルを下側に置いて重なりを避ける
        near = any(abs(px - qx) < span[0] * 0.12 and abs(py - qy) < span[1] * 0.06 for qx, qy in placed)
        a2.annotate(d["label"], (px, py), xytext=(7, -12 if near else 4), textcoords="offset points",
                    fontsize=9, color=INK2)
        placed.append((px, py))
    a2.set_xlabel(f"第 1 軸（{expl[0]:.0f}%）")
    a2.set_ylabel(f"第 2 軸（{expl[1]:.0f}%）")
    a2.set_title("F2. MDS 配置図（近いほど似ている）", loc="left", color=INK)
    save(fig, "11_clustering.png")
    return D


# 区間ごとの距離。ファイル全体の平均では、時間の長い持続部と減衰部の影響が大きく、
# 立ち上がりの違いが薄まるため、区間に分けて比べる
SEGMENTS = [("立ち上がり（0〜0.3 秒）", 0.0, 0.35), ("持続部（0.3〜2 秒）", 0.35, 2.05), ("減衰部（2〜5 秒）", 2.05, 5.05)]


def analyze_similarity_segments(data):
    sr = data[0]["sr"]
    feats = [librosa.feature.mfcc(y=d["y"], sr=sr, n_mfcc=14, n_fft=4096, hop_length=1024)[1:] for d in data]
    t = librosa.frames_to_time(np.arange(feats[0].shape[1]), sr=sr, hop_length=1024)  # aligned ファイルの時刻（立ち上がりは PRE 秒）
    n = len(data)
    labels = [d["label"] for d in data]
    out = []
    fig, axes = plt.subplots(1, 3, figsize=(20, 6.2))
    for ax, (name, t0, t1) in zip(axes, SEGMENTS):
        m = (t >= t0) & (t < t1)
        D = np.array([[np.linalg.norm(feats[i][:, m] - feats[j][:, m], axis=0).mean() for j in range(n)] for i in range(n)])
        med = np.median(D[np.triu_indices(n, 1)])
        out.append((name, D, med))
        im = ax.imshow(D / med, cmap=SEQ, vmin=0, vmax=2)
        for i in range(n):
            for j in range(n):
                ax.text(j, i, f"{D[i, j]:.0f}", ha="center", va="center", fontsize=7.5,
                        color="#ffffff" if D[i, j] / med > 1.1 else INK)
        ax.set_xticks(range(n), labels, rotation=45, ha="right", fontsize=8.5)
        ax.set_yticks(range(n), labels if ax is axes[0] else [""] * n, fontsize=8.5)
        ax.grid(False)
        ax.tick_params(length=0)
        ax.set_title(f"{name}（中央値 {med:.0f}）", loc="left", color=INK, fontsize=10)
    cb = fig.colorbar(im, ax=axes, shrink=0.7)
    cb.set_label("区間内の中央値に対する比（数値は距離そのもの）", color=INK2)
    fig.suptitle("F3. 区間ごとの距離行列（MFCC）", x=0.01, y=0.9, ha="left", color=INK)
    save(fig, "12_distance_segments.png")
    with open(ROOT / "docs" / "distance_segments.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["区間", "ペダル"] + labels)
        for name, D, _ in out:
            for i, l in enumerate(labels):
                w.writerow([name, l] + [f"{v:.1f}" for v in D[i]])
    return out


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    data = load()
    # 元ファイルの立ち上がり位置（ノイズ解析用）を前処理と同じ方法で求める
    src = {}
    for fname, *_ in PEDALS:
        x, sr = sf.read(WAV / fname, always_2d=True)
        src[fname] = align_trim.envelope(x.mean(1), sr)
    sr = data[0]["sr"]
    ref_on = align_trim.detect_onset(src["Raw.wav"], sr)
    a = src["Raw.wav"] - src["Raw.wav"].mean()
    from scipy.signal import correlate
    for d in data:
        b = src[d["file"]] - src[d["file"]].mean()
        lag = int(np.argmax(correlate(b, a, "full", method="fft")) - (len(a) - 1))
        w = int(align_trim.SEARCH * sr)
        g = ref_on + lag
        d["onset_src"] = align_trim.detect_onset(src[d["file"]], sr, max(g - w, 0), g + w)

    analyze_spectrum(data)
    analyze_noise(data)  # B2 でノイズフロアを使うため先に実行する
    analyze_time(data)
    analyze_dynamics(data)
    analyze_distortion(data)
    analyze_similarity(data)
    analyze_similarity_segments(data)

    cols = ["label", "sustain10", "sustain20", "attack_ms", "crest_db", "centroid_1s", "thd_db",
            "even_odd_db", "hnr_db", "noise_dbfs", "hiss_db", "hum_db"]
    with open(ROOT / "docs" / "metrics.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols + [b[0].replace("\n", " ") + " [%]" for b in BANDS])
        for d in data:
            w.writerow([d["label"]] + [f"{d[c]:.4g}" for c in cols[1:]] + [f"{s * 100:.3g}" for s in d["band_share"]])
    for d in data:
        print(f"{d['label']:18s} sus10={d['sustain10']:.2f} sus20={d['sustain20']:.2f} atk={d['attack_ms']:.1f}ms "
              f"crest={d['crest_db']:.1f} cent={d['centroid_1s']:.0f}Hz thd={d['thd_db']:.1f} eo={d['even_odd_db']:.1f} "
              f"hnr={d['hnr_db']:.1f} noise={d['noise_dbfs']:.1f} hiss={d['hiss_db']:.1f} hum={d['hum_db']:.1f} "
              f"bands=" + " ".join(f"{s*100:.1f}" for s in d["band_share"]))


if __name__ == "__main__":
    main()
