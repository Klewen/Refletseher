# İlerleme

## 2026-11-07 — v1.0.0

### Faz 1 — Araştırma ve mimari ✅
- Çalışma dizini boştu; uv projesi (Python 3.12.14) kuruldu. PySide6-Essentials seçildi (WebEngine'siz, ~125 MB daha küçük).
- Protokol kaynakları karşılaştırıldı (natanalt gist, sarpowsky Python, jeremylanes Rust): paket yerleşimi tutarlı; iki proje de `0xA0` kullanıyor — biz kullanmıyoruz.
- Donanım salt-okunur tarandı: 1 cihaz, usage page 0xFF / usage 1 / interface 0. MSI Center + Mystic_Light_Service + LEDKeeper2 çalışıyor.
- Yakalama ölçüldü: DXGI ~6,6 ms, WGC ~8 ms, GDI ~110 ms (1440p) → DXGI varsayılan, WGC/GDI yedek.

### Faz 2 — HID sürücüsü ✅
- `protocol.py` (oluşturucular + doğrulama + izin listesi), `transport.py` (tek `hidapi` noktası), `driver.py`, `worker.py`, `ratelimit.py`, `mock.py`, `conflicts.py`.
- Paketlerin doğrulanmış kodla bayt bayt aynı olduğu test ve gerçek cihazla teyit edildi.
- Gerçek donanım: 4 bölge testi (sıra doğru), nefes/döngü/dalga efektleri, 5/10/15 Hz gecikme testi — kullanıcı gözlemiyle doğrulandı.

### Faz 3 — Yakalama ve renk motoru ✅
- Monitör keşfi (DPI, yenileme, HDR), DXGI/WGC/GDI arka uçları, dxcam'in sonsuz kurtarma döngüsü kesilebilir backoff ile değiştirildi.
- OKLab, letterbox izleyici, ağırlıklar, histogram + deterministik k-means, 5 algoritma, sahne kesmesi + flaş koruması.
- Ayar: palet uzaklığı 0,09 → 0,065 (kullanıcının "gökyüzü + krem duvar" örneği ayrışsın diye).

### Faz 4 — Senkron motoru ✅
- Geçiş motoru (eşleme, EMA, histerezis, τ tabanlı OKLab), çıkış aşaması, ölü bant, ScreenSyncEngine iş parçacığı.
- Analiz zamanı gelmeden yakalama API'sine dokunulmuyor (CPU tasarrufu); DPI farkındalığı düzeltildi (mantıksal 1707×960 → fiziksel 2560×1440).

### Faz 5 — Masaüstü arayüzü ✅
- Tema tokenları, kart/kaydırıcı/anahtar/rozet bileşenleri, HSV renk seçici, 4 bölgeli klavye görselleştirici, 7 sayfa, tepsi, bildirim.
- Ekran görüntüsü inceleme ile düzeltilenler: `sync.subtitle` anahtar çakışması, Qt'nin `NoButtons` spinbox QSS hatası (metin alanı 1 px), simülasyon modunun "gönderildi" demesi (artık her yerde "Simülasyon"), çakışan bölge seçim çerçeveleri (artık seçilmeyen bölgeler karartılıyor).

### Faz 6 — Otomasyon ve entegrasyon ✅
- Profiller (12 hazır, atomik JSON, içe/dışa aktarma), ayarlar, Windows başlangıç kaydı, otomasyon servisi, uyku/kilit olayları, watchdog, tek örnek (`--quit`, `--profile`).
- Işık hassasiyeti testi gerçek bir sorun buldu: hızlı çok renkli paletler > 3 flaş/s üretebiliyordu → renk başına ≥ 0,34 s kuralı.

### Faz 7 — Doğrulama ve paketleme ✅
- 153 otomatik test geçiyor, 4 donanım testi gerçek cihazda geçti.
- Benchmark: Windows `time.monotonic` 15,6 ms çözünürlüğü keşfedildi → `perf_counter` + yüksek çözünürlüklü uyku; k-means kutu sınırı ve vektörel gamut kırpma ile p95 analiz süresi 3–4× düştü; OpenBLAS iş parçacığı sınırı ile private bellek 956 → 219 MB.
- PyInstaller tek klasör (UPX yok, gizleme yok), FFmpeg ve yazılım OpenGL DLL'leri çıkarıldı (238 → 189 MB).
- Paketlenmiş exe gerçek donanımda: pencere, tepsi, canlı konumsal senkron, yumuşak geçiş ve sahne kesmesi kullanıcı tarafından doğrulandı; 17 dk hatasız.

## 2026-11-08 — Donanım doğrulama turu (kullanıcıyla)
- `scripts/cinema_reel.py`: film benzeri 5 sahne gerçek yakalama + gerçek klavyeyle; kullanıcı 5/5 sahnenin beklendiği gibi olduğunu gözlemledi.
- Otomasyon (uygulamaya göre profil) exe'de doğrulandı.
- Kilit/açma doğrulandı.
- **Hata bulundu ve düzeltildi**: laptop Modern Standby kullanıyor, uyku mesajı gelmiyordu ve uyanınca yakalama GDI'ye düşüp kalıyordu → ekran durumu bildirimi, geçici hatada yedek yönteme düşmeme, DXGI'ye geri dönüş; yeniden test edildi ve doğrulandı.
- **Hata bulundu ve düzeltildi**: HDR desteği yanlış raporlanıyordu (v1 API) → `ADVANCED_COLOR_INFO_2`.
- Windows başlangıç kaydı kullanıcının isteğiyle açık bırakıldı; uygulama gerçek veri klasörüyle tepside çalışıyor.
- Testler: 157 geçti (Modern Standby olayları, geçici hata/geri dönüş testleri eklendi).

### Bekleyen (donanımda doğrulama)
Bkz. [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md): oturum açılışında otomatik başlamanın gözlemi, gerçek film/dizi içeriği,
harici monitör, uzun süreli MSI Center çakışması. HDR bu panelde uygulanamaz.

### Olası sonraki adımlar
- Klavye görselleştiricisinin bölge sınırlarının fiziksel klavyeyle tuş tuş eşlenmesi (şu an yaklaşık: 5/5/5 birim + numpad).
- Kod imzalama sertifikası ile imzalı derleme (SmartScreen uyarısını kaldırır).
- Canlı dil değiştirme (şu an yeniden başlatma gerekiyor).
