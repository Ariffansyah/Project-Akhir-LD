"""Melatih model Decision Tree untuk rekomendasi irigasi dan mengekspornya ke C (firmware/model.h).

Jalankan:  uv run --with scikit-learn --with matplotlib python ai/train_model.py
Di Google Colab cukup unggah file ini lalu jalankan:  !python train_model.py
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import ConfusionMatrixDisplay, accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.tree import DecisionTreeClassifier, plot_tree

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "hasil"
MODEL_H = ROOT.parent / "simulasi" / "firmware" / "model.h"
FITUR = ["soil", "temp", "hum", "lux", "vpd"]
KELAS = ["TIDAK_SIRAM", "SIRAM", "TUNDA"]
rng = np.random.default_rng(42)


def vpd(temp, hum):
    """Vapor Pressure Deficit (kPa), rumus Tetens. Makin tinggi, makin cepat tanah dan daun kehilangan air."""
    return 0.6108 * np.exp(17.27 * temp / (temp + 237.3)) * (1 - hum / 100)


def label(soil, temp, hum, lux):
    """Aturan agronomi untuk memberi label data: tanah kritis selalu disiram; tanah agak kering disiram,
    kecuali saat terik-kering (air banyak menguap) atau malam (daun basah semalaman memicu jamur)."""
    d = vpd(temp, hum)
    perlu = soil < 40 + 6 * d
    tunda = (d > 2.0) | (lux < 20)
    y = np.where(perlu, np.where(tunda, 2, 1), 0)
    y = np.where(soil < 25, 1, y)
    return np.where(soil >= 65, 0, y)


def buat_dataset(n=4000):
    soil = rng.uniform(5, 95, n)
    temp = rng.uniform(20, 38, n)
    hum = np.clip(130 - 2.2 * temp + rng.normal(0, 10, n), 30, 99)
    lux = 10 ** rng.uniform(-1, 4.5, n)
    y = label(soil, temp, hum, lux)
    # Ketidakpastian pelabelan di lapangan: 3% label acak.
    acak = rng.random(n) < 0.03
    y[acak] = rng.integers(0, 3, acak.sum())
    # Label berasal dari kondisi sebenarnya; fitur adalah bacaan sensor yang berderau (akurasi DHT22 dan sensor tanah).
    soil = np.clip(soil + rng.normal(0, 2, n), 0, 100)
    temp = temp + rng.normal(0, 0.5, n)
    hum = np.clip(hum + rng.normal(0, 2, n), 0, 100)
    lux = lux * rng.normal(1, 0.1, n).clip(0.5)
    df = pd.DataFrame({"soil": soil, "temp": temp, "hum": hum, "lux": lux})
    df["vpd"] = vpd(df.temp, df.hum)
    df["label"] = y
    return df.round(3)


def ke_c(model):
    t = model.tree_

    def kelas_tunggal(i):
        """Kelas cabang ini bila semua daunnya sama; cabang seperti itu cukup jadi satu return."""
        if t.children_left[i] == -1:
            return int(model.classes_[t.value[i][0].argmax()])
        a, b = kelas_tunggal(t.children_left[i]), kelas_tunggal(t.children_right[i])
        return a if a == b else None

    def node(i, ind):
        k = kelas_tunggal(i)
        if k is not None:
            return f"{ind}return {k};  // {KELAS[k]}\n"
        # Ambang dicetak sebagai double agar perbandingannya sama persis dengan scikit-learn.
        return (f"{ind}if ({FITUR[t.feature[i]]} <= {t.threshold[i]:.17g}) {{\n" + node(t.children_left[i], ind + "  ")
                + f"{ind}}} else {{\n" + node(t.children_right[i], ind + "  ") + f"{ind}}}\n")

    nama = ", ".join(f'"{k}"' for k in KELAS)
    return (
        "// Dibuat otomatis oleh ai/train_model.py. Jangan diedit manual; latih ulang modelnya.\n"
        "#pragma once\n\n"
        f"const char *const KELAS[] = {{{nama}}};\n\n"
        f"// Decision Tree: kedalaman {model.get_depth()}, {model.get_n_leaves()} daun.\n"
        "inline int prediksi(float soil, float temp, float hum, float lux, float vpd) {\n" + node(0, "  ") + "}\n"
    )


def cek_model_h(X, harapan):
    """Kompilasi model.h dengan g++ dan pastikan hasilnya sama dengan scikit-learn."""
    if not shutil.which("g++"):
        print("g++ tidak ada, cek model.h dilewati")
        return
    with tempfile.TemporaryDirectory() as tmp:
        src, exe = Path(tmp, "cek.cpp"), Path(tmp, "cek")
        src.write_text(f'#include <cstdio>\n#include "{MODEL_H}"\nint main(){{float a,b,c,d,e;'
                       'while(scanf("%f %f %f %f %f",&a,&b,&c,&d,&e)==5)printf("%d\\n",prediksi(a,b,c,d,e));}\n')
        subprocess.run(["g++", "-O1", "-o", exe, src], check=True)
        masukan = "\n".join(" ".join(f"{v:.9g}" for v in baris) for baris in X.astype(np.float32))
        hasil = subprocess.run([exe], input=masukan, capture_output=True, text=True, check=True).stdout.split()
    assert list(map(int, hasil)) == list(harapan), "model.h berbeda dengan model scikit-learn"
    print(f"model.h cocok dengan scikit-learn pada {len(hasil)} data uji")


def main():
    OUT.mkdir(exist_ok=True)
    df = buat_dataset()
    df.to_csv(ROOT / "dataset.csv", index=False)
    X, y = df[FITUR].to_numpy(), df["label"].to_numpy()
    X_lat, X_uji, y_lat, y_uji = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)

    laporan = [f"Dataset: {len(df)} baris, distribusi kelas: {dict(zip(KELAS, np.bincount(y)))}",
               f"Data latih: {len(y_lat)}, data uji: {len(y_uji)}", "",
               "Pemilihan kedalaman pohon (5-fold cross-validation pada data latih):"]
    skor = {}
    for depth in range(2, 11):
        cv = cross_val_score(DecisionTreeClassifier(max_depth=depth, min_samples_leaf=5, random_state=42), X_lat, y_lat, cv=5)
        skor[depth] = cv.mean()
        laporan.append(f"  max_depth={depth:2d}  akurasi={cv.mean():.4f} ± {cv.std():.4f}")
    # Pohon terkecil yang akurasinya tidak lebih dari 0,5% di bawah yang terbaik: lebih hemat memori ESP32.
    depth = min(d for d, s in skor.items() if s >= max(skor.values()) - 0.005)
    model = DecisionTreeClassifier(max_depth=depth, min_samples_leaf=5, random_state=42).fit(X_lat, y_lat)
    pred = model.predict(X_uji)

    # Pembanding tanpa AI: pompa menyala setiap kelembapan tanah < 40%.
    dasar = np.where(X_uji[:, 0] < 40, 1, 0)
    terik_malam = (X_uji[:, 4] > 2.0) | (X_uji[:, 3] < 20)
    laporan += ["", f"Kedalaman terpilih: {depth} ({model.get_n_leaves()} daun)",
                f"Akurasi Decision Tree (data uji): {accuracy_score(y_uji, pred):.4f}",
                f"Akurasi pembanding ambang tetap tanah<40%: {accuracy_score(y_uji, dasar):.4f}", "",
                classification_report(y_uji, pred, target_names=KELAS, digits=4),
                "Matriks konfusi (baris = sebenarnya, kolom = prediksi):", str(confusion_matrix(y_uji, pred)), "",
                "Kepentingan fitur: " + ", ".join(f"{f}={v:.3f}" for f, v in zip(FITUR, model.feature_importances_)), "",
                "Penyiraman saat terik-kering/malam pada data uji:",
                f"  ambang tetap : {int((dasar[terik_malam] == 1).sum())} kali",
                f"  Decision Tree: {int((pred[terik_malam] == 1).sum())} kali"]
    teks = "\n".join(laporan)
    print(teks)
    (OUT / "metrik.txt").write_text(teks + "\n")

    ConfusionMatrixDisplay(confusion_matrix(y_uji, pred), display_labels=KELAS).plot(cmap="Greens")
    plt.title("Matriks Konfusi Decision Tree (data uji)")
    plt.tight_layout()
    plt.savefig(OUT / "matriks_konfusi.png", dpi=150)
    plt.figure(figsize=(22, 10))
    plot_tree(model, feature_names=FITUR, class_names=KELAS, filled=True, max_depth=3, fontsize=8)
    plt.title("Decision Tree (3 tingkat teratas)")
    plt.savefig(OUT / "pohon_keputusan.png", dpi=120, bbox_inches="tight")

    MODEL_H.write_text(ke_c(model))
    print(f"\nModel ditulis ke {MODEL_H}")
    cek_model_h(X_uji, pred)


if __name__ == "__main__":
    main()
