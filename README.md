# 🎥 Reycamview — Virtual Camera & Webcam Control Engine

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-blue?style=for-the-badge&logo=windows" alt="Platform Windows">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3">
  <img src="https://img.shields.io/badge/UI-Apple%20WWDC25%20Liquid%20Glass-black?style=for-the-badge&logo=apple" alt="Apple Liquid Glass">
  <img src="https://img.shields.io/badge/Output-Virtual%20Camera%20%22reycam%22-00C7BE?style=for-the-badge" alt="Virtual Cam reycam">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License MIT">
</p>

---

## 📖 Tentang Reycamview

**Reycamview** adalah aplikasi pengontrol webcam dan *virtual camera engine* untuk Windows dengan antarmuka modern **Apple WWDC25 Liquid Glass**. 

Aplikasi ini membaca input langsung dari webcam fisik Anda (seperti *USB2.0 HD UVC WebCam* atau kamera bawaan laptop), mengolah pengaturan visual secara *real-time* (Shutter Speed, Sensor Gain, Exposure, White Balance, Zoom, Mirror, dan FPS Pacing), kemudian **memancarkan (*broadcast*) feed video yang sudah disempurnakan tersebut ke kamera virtual bernama `"reycam"`**.

Di aplikasi apapun (**Discord**, **Zoom**, **OBS Studio**, **Google Meet**, **Microsoft Teams**), Anda cukup memilih kamera bernama **`reycam`** untuk menikmati hasil pengaturan kamera berkualitas tinggi dengan konsumsi CPU yang sangat rendah!

---

## 🌟 Fitur Utama

- 🔄 **Virtual Camera Output (`reycam`):** Memancarkan hasil olahan kamera ke perangkat virtual sistem `reycam` yang otomatis dikenali oleh seluruh aplikasi streaming dan video call.
- ⚡ **Shutter Speed Control:** Pengaturan kecepatan rana manual khusus fotografi: **`1/16`**, **`1/32`**, **`1/64`**, `1/128`, `1/250`, `1/500`, dan `Auto`.
- ⏱️ **FPS Broadcast Adjustment:** Pilihan target frame rate `15 FPS`, `24 FPS`, `30 FPS`, hingga `60 FPS` untuk memastikan kelancaran video.
- 🍃 **Ultra-Lightweight & Eco / Low CPU Mode:** Didesain khusus untuk PC atau laptop dengan spesifikasi rendah (*low-spec*). Dilengkapi mode **Eco Mode** yang mematikan render antarmuka saat berada di background, memangkas konsumsi CPU hingga **hanya ~1-2%**.
- 🏷️ **Deteksi Nama Asli Webcam Windows:** Otomatis membaca nama perangkat fisik dari Windows PnP Device Manager (*bukan sekadar "Camera 0" atau "Camera 1"*).
- 🎨 **Apple WWDC25 Liquid Glass Dark UI:** Tampilan *glassmorphism* modern dengan *pill toggles switch*, *segmented buttons*, dan *glowing sliders* tanpa popup yang macet.
- 🎛️ **Full Image Processing:** Kontrol Exposure, Gain, Brightness, Contrast, Sharpness, Gamma, White Balance (K), Saturation, Digital Zoom (100%-400%), serta Flip Horizontal & Vertikal.
- 💾 **Preset 1-Tap & Export/Import Profile:** Profil siap pakai (*Daylight*, *Low Light*, *Studio*, *Cinema*) serta simpan/muat konfigurasi format `.json`.

---

## 🔄 Cara Kerja (Architecture Pipeline)

```
[ Webcam Fisik ] 
 (e.g. USB2.0 HD UVC WebCam)
         │
         ▼
[ Reycamview Engine ]
 ├── Shutter Speed (1/16, 1/32, 1/64, Auto)
 ├── Hardware Exposure & Sensor Gain
 ├── Image Proc (Brightness, Contrast, Sharpness)
 ├── White Balance & Color Temp (K)
 ├── FPS Pacing Engine (15 - 60 FPS)
 └── Digital Zoom & Flip H/V
         │
         ▼  (DirectShow Broadcast)
[ Virtual Camera: "reycam" ]
         │
 ┌───────┼─────────────────────────┐
 ▼       ▼                         ▼
[ Discord ]  [ Zoom & Google Meet ]  [ OBS Studio & Teams ]
```

---

## 🚀 Cara Penggunaan (Bagi Pengguna)

1. Unduh file **`Reycamview.exe`** dari tab [Releases](../../releases).
2. Jalankan `Reycamview.exe` *(aplikasi bersifat portabel, tanpa perlu instalasi)*.
3. Pilih kamera fisik Anda pada menu **INPUT CAMERA** (misalnya `USB2.0 HD UVC WebCam`).
4. Klik **▶ Start Streaming**.
5. Sesuaikan Shutter Speed, FPS, dan kecerahan sesuai kebutuhan Anda.
6. Buka aplikasi meeting/streaming Anda (**Discord, Zoom, Google Meet, OBS**), lalu pilih kamera **`reycam`** *(atau `OBS Virtual Camera`)*.

> [!TIP]
> **Khusus Pengguna Discord:**  
> Untuk mengubah label kamera di Discord agar tertulis resmi **`reycam`**, klik tombol **`🏷️ Daftarkan Nama 'reycam' ke Discord`** di bagian atas aplikasi Reycamview (atau klik kanan file `register_reycam_admin.bat` lalu pilih *Run as Administrator*), kemudian restart Discord Anda!

---

## 🛠️ Pengembangan & Build dari Source Code (Bagi Developer)

### 1. Kloning Repository
```bash
git clone https://github.com/USERNAME/Reycamview.git
cd Reycamview
```

### 2. Pasang Dependensi
Pastikan Python 3.10+ sudah terpasang di sistem Windows Anda:
```bash
pip install -r requirements.txt
```

### 3. Menjalankan Source Code
```bash
python reycamview.py
```

### 4. Mengompilasi Menjadi File `.exe` Standalone
Jalankan script build bawaan:
```bash
python build.py
```
*Hasil file `.exe` yang sudah jadi akan berada di folder `dist/Reycamview.exe`.*

---

## 📁 Struktur File Repository

```
Reycamview/
├── reycamview.py             # Source code utama aplikasi Reycamview
├── requirements.txt          # Daftar library Python (opencv, Pillow, pyvirtualcam, pyinstaller)
├── build.py                  # Script build PyInstaller otomatis
├── build.bat                 # Script batch Windows build 1-klik
├── register_reycam_admin.bat # Script batch pendaftaran nama virtual camera ke sistem Windows
├── .gitignore                # Filter file sementara (mengabaikan dist/, build/, __pycache__/)
├── LICENSE                   # Lisensi open-source MIT
└── README.md                 # Halaman dokumentasi utama repository
```

---

## 📄 Lisensi

Proyek ini dilisensikan di bawah lisensi open-source [MIT License](LICENSE). Bebas digunakan, dimodifikasi, dan didistribusikan.
