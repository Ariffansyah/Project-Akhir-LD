"""Asisten LLM: mengubah data sensor dan keputusan Decision Tree menjadi saran bahasa Indonesia untuk petani,
dan menjawab pertanyaan dari dashboard. Pompa tetap dikendalikan Decision Tree di ESP32; LLM hanya menjelaskan.

Lokal (default, Ollama):  ollama pull gemma3:1b
                          uv run --with paho-mqtt python ai/asisten_llm.py
Groq (cloud):             GROQ_API_KEY=gsk_... uv run --with paho-mqtt python ai/asisten_llm.py
Uji tanpa MQTT:           uv run --with paho-mqtt python ai/asisten_llm.py --uji
Model lain:               LLM_MODEL=qwen2.5:1.5b ...
"""
import json
import os
import queue
import re
import sys
import time
import urllib.request
from pathlib import Path

import paho.mqtt.client as mqtt

BROKER = "broker.hivemq.com"
# Harus sama dengan TOPIK di firmware dan dashboard (tanpa "/data").
DASAR = "litdih-aiot/irigasi-cerdas"
JEDA_SARAN = 60
JEDA_MIN = 10

if os.environ.get("GROQ_API_KEY"):
    URL = "https://api.groq.com/openai/v1/chat/completions"
    KUNCI, MODEL = os.environ["GROQ_API_KEY"], os.environ.get("LLM_MODEL", "llama-3.1-8b-instant")
else:
    URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/v1/chat/completions"
    KUNCI, MODEL = "ollama", os.environ.get("LLM_MODEL", "gemma3:1b")

SISTEM = ("Kamu asisten pertanian untuk petani Indonesia pada sistem irigasi cerdas. "
          "Tulis dalam bahasa Indonesia sederhana, paling banyak 3 kalimat, tanpa markdown dan tanpa salam pembuka. "
          "Keputusan pompa sudah diambil model Decision Tree di ESP32: jangan mengubah atau membantah keputusan itu. "
          "Gunakan hanya data dan alasan yang diberikan, jangan mengarang angka lain.")
# Contoh few-shot: model 1B meniru panjang, gaya, dan kepatuhannya pada keputusan jauh lebih baik daripada
# dari instruksi saja.
CONTOH = [
    ("Data sensor: kelembapan tanah 30%, suhu 29 °C, kelembapan udara 70%, cahaya 900 lux, VPD 1.2 kPa. "
     "Keputusan Decision Tree: siram sekarang (pompa menyala). Alasan: tanah mulai kering dan udara tidak terlalu panas "
     "sehingga air terserap dengan baik. Jelaskan keputusan ini kepada petani, lalu beri satu saran praktis.",
     "Pompa dinyalakan karena tanah mulai kering (30%) dan udara masih sejuk, jadi air terserap dengan baik. "
     "Saran: arahkan air ke pangkal tanaman, bukan ke daun, agar langsung sampai ke akar."),
    ("Data sensor: kelembapan tanah 68%, suhu 33 °C, kelembapan udara 50%, cahaya 1500 lux, VPD 2.5 kPa. "
     "Keputusan Decision Tree: tidak perlu menyiram (pompa mati). Alasan: tanah masih cukup lembap untuk kondisi udara "
     "saat ini. Jelaskan keputusan ini kepada petani, lalu beri satu saran praktis.",
     "Pompa tetap mati karena tanah masih cukup lembap (68%), walaupun udara sedang panas. "
     "Saran: beri mulsa jerami di permukaan tanah agar kelembapannya bertahan lebih lama."),
    ("Data sensor: kelembapan tanah 38%, suhu 34 °C, kelembapan udara 45%, cahaya 1600 lux, VPD 2.9 kPa. "
     "Keputusan Decision Tree: tunda penyiraman (pompa mati). Alasan: udara sedang panas dan kering, air siraman cepat "
     "menguap, jadi siram sore hari.\nPertanyaan petani: Boleh saya siram sekarang?",
     "Sebaiknya jangan dulu, pompa sengaja dimatikan karena udara sedang panas dan kering sehingga air cepat menguap. "
     "Siram sore hari ketika matahari sudah tidak terik."),
]
ARTI = {"TIDAK_SIRAM": "tidak perlu menyiram (pompa mati)", "SIRAM": "siram sekarang (pompa menyala)",
        "TUNDA": "tunda penyiraman (pompa mati)"}


def alasan(d):
    """Alasan keputusan, mengikuti aturan agronomi yang dipelajari Decision Tree. Model 1B jauh lebih
    konsisten bila alasannya diberikan sebagai fakta daripada disuruh menyimpulkan sendiri."""
    if d["keputusan"] == "TIDAK_SIRAM":
        return "tanah masih cukup lembap untuk kondisi udara saat ini"
    if d["keputusan"] == "SIRAM":
        return "tanah sangat kering sehingga harus segera disiram" if d["tanah"] < 27 else \
            "tanah mulai kering dan udara tidak terlalu panas sehingga air terserap dengan baik"
    if d["lux"] < 20:
        return "sekarang malam hari; daun yang basah semalaman mudah terserang jamur, jadi siram besok pagi"
    return "udara sedang panas dan kering, air siraman cepat menguap, jadi siram sore hari"


def konteks(d):
    return (f"Data sensor: kelembapan tanah {d['tanah']}%, suhu {d['suhu']} °C, kelembapan udara {d['kelembapan']}%, "
            f"cahaya {d['lux']} lux, VPD {d['vpd']} kPa. Keputusan Decision Tree: {ARTI[d['keputusan']]}. "
            f"Alasan: {alasan(d)}.")


def rapikan(teks):
    """Model kecil sering bertele-tele: buang markdown dan ambil paling banyak 3 kalimat pertama."""
    kalimat = re.split(r"(?<=[.!?])\s+", re.sub(r"[*#]+", "", teks).strip())
    return " ".join(kalimat[:3])


def tanya_llm(teks_user):
    pesan = [{"role": "system", "content": SISTEM}]
    for tanya, jawab_contoh in CONTOH:
        pesan += [{"role": "user", "content": tanya}, {"role": "assistant", "content": jawab_contoh}]
    pesan.append({"role": "user", "content": teks_user})
    isi = json.dumps({"model": MODEL, "temperature": 0.2, "max_tokens": 150, "messages": pesan})
    req = urllib.request.Request(URL, isi.encode(), {"Content-Type": "application/json", "Authorization": f"Bearer {KUNCI}",
                                                     "User-Agent": "irigasi-cerdas/1.0"})
    mulai = time.time()
    with urllib.request.urlopen(req, timeout=90) as r:
        teks = json.load(r)["choices"][0]["message"]["content"].strip()
    return rapikan(teks), round(time.time() - mulai, 1)


def minta_saran(d):
    return tanya_llm(konteks(d) + " Jelaskan keputusan ini kepada petani, lalu beri satu saran praktis.")


def jawab(pertanyaan, d):
    if not d:
        return tanya_llm(f"Belum ada data sensor.\nPertanyaan petani: {pertanyaan}")
    # Keputusan diulang di akhir karena model kecil paling mematuhi kalimat terakhir.
    return tanya_llm(f"{konteks(d)}\nPertanyaan petani: {pertanyaan}\n"
                     f"Ingat: keputusan pompa saat ini adalah {ARTI[d['keputusan']]} dan tidak boleh diubah.")


def uji():
    """Menjalankan skenario uji yang sama dengan pengujian Wokwi dan mencatat jawaban serta waktu respons."""
    kasus = [(80, 30, 65, 800, "TIDAK_SIRAM"), (15, 35, 40, 1500, "SIRAM"), (35, 28, 75, 800, "SIRAM"),
             (35, 35, 45, 1500, "TUNDA"), (35, 26, 85, 5, "TUNDA"), (50, 34, 45, 1500, "TUNDA"),
             (50, 27, 80, 800, "TIDAK_SIRAM"), (70, 36, 35, 2000, "TIDAK_SIRAM")]
    baris = [f"Model: {MODEL}", ""]
    waktu = []
    for i, (tanah, suhu, rh, lux, k) in enumerate(kasus, 1):
        vpd = round(0.6108 * 2.718281828 ** (17.27 * suhu / (suhu + 237.3)) * (1 - rh / 100), 2)
        d = {"tanah": tanah, "suhu": suhu, "kelembapan": rh, "lux": lux, "vpd": vpd, "keputusan": k}
        teks, detik = minta_saran(d)
        waktu.append(detik)
        baris += [f"[{i}] tanah {tanah}%, {suhu} °C, RH {rh}%, {lux} lux -> {k} ({detik} s)", teks, ""]
        print(baris[-3], "\n", teks, "\n", flush=True)
    # Konsistensi: jawaban soal pompa harus sejalan dengan keputusan Decision Tree. Dinilai dari kata pembuka,
    # jadi tetap periksa teksnya secara manual.
    kondisi = {"SIRAM": (30, 28, 75, 800, 0.95), "TUNDA": (35, 35, 45, 1500, 3.09), "TIDAK_SIRAM": (70, 30, 65, 800, 1.49)}
    cocok = total = 0
    for k, (tanah, suhu, rh, lux, vpd) in kondisi.items():
        d = {"tanah": tanah, "suhu": suhu, "kelembapan": rh, "lux": lux, "vpd": vpd, "keputusan": k}
        for q in ["Apakah saya harus menyalakan pompa sekarang?", "Boleh saya siram tanaman sekarang?"]:
            teks, detik = jawab(q, d)
            waktu.append(detik)
            awal = teks.lower()[:40]
            setuju = re.match(r"(ya|boleh|silakan|tentu|benar)\b", awal) is not None
            menolak = re.search(r"\b(tidak|jangan|belum|tunda)\b", awal) is not None
            benar = setuju and not menolak if k == "SIRAM" else menolak
            cocok += benar
            total += 1
            baris += [f"[Tanya, {k}] {q} ({detik} s) -> {'konsisten' if benar else 'TIDAK KONSISTEN'}", teks, ""]
            print(baris[-3], "\n", teks, "\n", flush=True)
    teks, detik = jawab("Kapan waktu terbaik untuk menyiram hari ini?", {**d, **dict(zip(
        ["tanah", "suhu", "kelembapan", "lux", "vpd"], kondisi["TUNDA"])), "keputusan": "TUNDA"})
    waktu.append(detik)
    baris += [f"[Tanya, TUNDA] Kapan waktu terbaik untuk menyiram hari ini? ({detik} s)", teks, ""]
    print(baris[-3], "\n", teks, "\n", flush=True)
    baris.append(f"Konsistensi jawaban soal pompa: {cocok}/{total}")
    baris.append(f"Waktu respons rata-rata: {sum(waktu) / len(waktu):.1f} s, maksimum {max(waktu):.1f} s")
    out = Path(__file__).resolve().parent.parent / "pengujian" / f"uji_llm_{MODEL.replace(':', '_').replace('/', '_')}.txt"
    out.write_text("\n".join(baris) + "\n")
    print(baris[-1], f"\nDisimpan ke {out}")


def main():
    if "--uji" in sys.argv:
        return uji()
    # Pemanggilan LLM butuh beberapa detik, jadi dikerjakan di luar thread MQTT; antrean kecil membatasi
    # banjir pertanyaan dari broker publik.
    antrean = queue.Queue(maxsize=3)
    status = {"data": None, "alasan": None, "waktu": 0.0}

    def masukkan(tugas):
        try:
            antrean.put_nowait(tugas)
        except queue.Full:
            print("antrean penuh, permintaan dilewati")

    def terima(_klien, _userdata, pesan):
        try:
            d = json.loads(pesan.payload)
        except ValueError:
            return
        if not isinstance(d, dict):
            return
        if pesan.topic.endswith("/data") and d.get("keputusan") in ARTI:
            status["data"] = d
            # Dibandingkan per alasan, bukan per kelas: TUNDA karena malam dan TUNDA karena terik butuh saran berbeda.
            # JEDA_MIN meredam sensor yang naik-turun di sekitar batas keputusan.
            sekarang = time.time()
            if (alasan(d) != status["alasan"] and sekarang - status["waktu"] >= JEDA_MIN) or sekarang - status["waktu"] > JEDA_SARAN:
                status["alasan"], status["waktu"] = alasan(d), sekarang
                masukkan(("saran", d))
        elif pesan.topic.endswith("/tanya") and isinstance(d.get("teks"), str) and d["teks"].strip():
            masukkan(("jawaban", d))

    klien = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"asisten-llm-{os.getpid()}")
    klien.on_connect = lambda k, *_: k.subscribe([(f"{DASAR}/data", 0), (f"{DASAR}/tanya", 0)])
    klien.on_message = terima
    klien.connect(BROKER, 1883)
    klien.loop_start()
    print(f"Asisten LLM aktif: model {MODEL}, topik {DASAR}/#")

    while True:
        jenis, d = antrean.get()
        try:
            if jenis == "saran":
                teks, detik = minta_saran(d)
                hasil = {"keputusan": d["keputusan"]}
            else:
                teks, detik = jawab(d["teks"][:300], status["data"])
                hasil = {"id": str(d.get("id", ""))[:32], "tanya": d["teks"][:300]}
        except (OSError, KeyError, ValueError) as e:
            # LLM mati atau lambat tidak boleh menghentikan asisten; dashboard diberi tahu.
            teks, detik = f"Asisten AI tidak dapat dihubungi ({e}).", 0
            hasil = {"id": str(d.get("id", ""))[:32]} if jenis == "jawaban" else {"keputusan": d.get("keputusan")}
        klien.publish(f"{DASAR}/{jenis}", json.dumps({**hasil, "teks": teks, "model": MODEL, "detik": detik}))
        print(f"[{jenis}] {detik} s: {teks}", flush=True)


if __name__ == "__main__":
    main()
