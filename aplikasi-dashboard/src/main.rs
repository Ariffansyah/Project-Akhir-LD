// Jendela desktop untuk dashboard/index.html; MQTT, grafik, dan asisten LLM tetap berjalan di halaman itu.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("gagal menjalankan Dashboard Irigasi Cerdas");
}
