# Irigasi Cerdas AIoT (Proyek Akhir Literasi Digital)

ESP32 + DHT22 + LDR + sensor tanah (potensiometer) → Decision Tree di ESP32 → relay pompa, LED, LCD → MQTT → dashboard, plus asisten LLM (Gemma 3 1B lokal via Ollama, atau Groq) yang menjelaskan keputusan dan menjawab pertanyaan di dashboard.

| Folder | Isi |
|---|---|
| `simulasi/` | Proyek Wokwi/WireLab (`diagram.json`, `firmware/firmware.ino`, `firmware/model.h`) |
| `simulasi/build/wokwi/` | File siap unggah ke wokwi.com (hasil Export to Wokwi) |
| `ai/` | `train_model.py` (dataset, pelatihan, evaluasi, ekspor `model.h`), `asisten_llm.py` (asisten LLM), `dataset.csv`, `hasil/` |
| `dashboard/index.html` | Dashboard monitoring (buka di browser saat simulasi jalan) |
| `aplikasi-dashboard/` | Dashboard yang sama sebagai aplikasi desktop Tauri 2; hasil build di `rilis/` |
| `pengujian/` | Skenario uji Wokwi, log serial, screenshot |
| `laporan/` | Laporan .docx (bagian kuning `[ISI: ...]` harus dilengkapi) dan gambar |

## Menjalankan

- **wokwi.com:** buka https://wokwi.com/projects/new/esp32, unggah semua file di `simulasi/build/wokwi/` (menu *Upload file(s)…* di samping tab file), Start, lalu Save dan Share untuk mendapat link.
- **WireLab:** `wirelab simulasi/` lalu Run.
- **Dashboard:** buka `dashboard/index.html` di browser, atau jalankan aplikasi desktop `aplikasi-dashboard/rilis/dashboard-irigasi-linux-x64` (Linux; butuh webkit2gtk-4.1) atau pasang `.deb`-nya.
- **Build aplikasi desktop:** di `aplikasi-dashboard/` jalankan `npm install` lalu `npm run build` (butuh Rust dan prasyarat Tauri: https://v2.tauri.app/start/prerequisites/). Di Windows perintah yang sama menghasilkan installer `.exe`/`.msi` di `target/release/bundle/`. Jangan ikutkan folder `target/` saat membagikan proyek karena ukurannya bisa beberapa GB.
- **Asisten LLM:** `ollama pull gemma3:1b`, lalu `uv run --with paho-mqtt python ai/asisten_llm.py` dan biarkan berjalan. Untuk Groq: `GROQ_API_KEY=gsk_... uv run --with paho-mqtt python ai/asisten_llm.py`. Uji tanpa simulasi: tambahkan `--uji` (hasil di `pengujian/uji_llm_*.txt`).
- **Latih ulang model:** `uv run --with scikit-learn --with matplotlib --with pandas python ai/train_model.py` (atau di Colab: `!python train_model.py`). Setelah itu, export ulang ke Wokwi.
- **Uji otomatis di Wokwi:** `cd simulasi && wokwi-cli . --scenario ../pengujian/skenario_wokwi.yaml --timeout 60000` (butuh `WOKWI_CLI_TOKEN`).
