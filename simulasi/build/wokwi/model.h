// Dibuat otomatis oleh ai/train_model.py. Jangan diedit manual; latih ulang modelnya.
#pragma once

const char *const KELAS[] = {"TIDAK_SIRAM", "SIRAM", "TUNDA"};

// Decision Tree: kedalaman 4, 16 daun.
inline int prediksi(float soil, float temp, float hum, float lux, float vpd) {
  if (soil <= 46.525001525878906) {
    if (soil <= 26.725000381469727) {
      return 1;  // SIRAM
    } else {
      if (lux <= 19.63599967956543) {
        return 2;  // TUNDA
      } else {
        if (vpd <= 2.0255000591278076) {
          return 1;  // SIRAM
        } else {
          return 2;  // TUNDA
        }
      }
    }
  } else {
    if (soil <= 52.114500045776367) {
      if (vpd <= 1.8105000257492065) {
        return 0;  // TIDAK_SIRAM
      } else {
        return 2;  // TUNDA
      }
    } else {
      if (soil <= 58.217500686645508) {
        if (vpd <= 2.3825000524520874) {
          return 0;  // TIDAK_SIRAM
        } else {
          return 2;  // TUNDA
        }
      } else {
        return 0;  // TIDAK_SIRAM
      }
    }
  }
}
