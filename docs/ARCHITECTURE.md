# Mimari

```
            ┌──────────────────────── UI (PySide6, ana iş parçacığı) ───────────────────────┐
            │ MainWindow · 7 sayfa · KeyboardView · ColorPicker · Tray · native olaylar      │
            │   30 Hz QTimer → controller.snapshot()   (GUI hiçbir zaman hidapi/dxcam çağırmaz)│
            └───────────────────────────────┬────────────────────────────────────────────────┘
                                            │ thread-safe çağrılar
                              ┌─────────────▼─────────────┐
                              │       AppController        │  mod makinesi, profiller, geçmiş (geri al),
                              │  (core/controller.py)      │  ana parlaklık, watchdog, çıkış davranışı
                              └──┬──────────┬──────────┬───┘
               renk kareleri     │          │          │ HardwareEffect / ZoneColors
         ┌───────────────────────▼──┐  ┌────▼─────┐  ┌─▼──────────────────────────────────┐
         │ ScreenSyncEngine (thread)│  │EffectRun-│  │ DeviceWorker (TEK HID iş parçacığı) │
         │ capture → analyse →      │  │ner(thread│  │ istenen durum ↔ onaylanan durum     │
         │ transition → output      │  │ yazılım  │  │ birleştirme, tekrar bastırma,       │
         └──┬──────────────┬────────┘  │ efektleri│  │ 15 Hz kapısı + 120 pkt/s kova,      │
            │              │           └──────────┘  │ backoff, uyku/kilit                 │
   ┌────────▼───────┐ ┌────▼─────────────┐           └──┬──────────────────────────────────┘
   │ Capture layer  │ │ Color engine     │              │ Ms1565Driver → GuardedTransport
   │ dxgi/winrt/gdi │ │ OKLab, kümeleme, │              │ (validate_packet) → hidapi
   │ monitör/HDR    │ │ 5 algoritma      │              ▼
   └────────────────┘ └──────────────────┘        MS-1565 (0x01 / 0x02)
```

## Katmanlar

| Katman | Paket | Sorumluluk |
|---|---|---|
| Device | `screensync.device` | protokol + doğrulama, `DeviceBackend` arayüzü (`HidapiBackend`, `MockBackend`), sürücü, worker, hız sınırlayıcı, MSI Center tespiti |
| Capture | `screensync.capture` | monitör keşfi (Win32 + DisplayConfig, DPI, HDR), DXGI/WGC (`dxcam`), GDI (`mss`), sentetik kaynak, bölge, ön küçültme |
| Color engine | `screensync.color` | renk uzayları, letterbox, piksel ağırlıkları, histogram + ağırlıklı k-means, 5 çıkarıcı, sahne kesmesi |
| Transition | `screensync.sync` | eşleme (Hungarian 4×4), EMA, histerezis, OKLab geçişi, ölü bant, çıkış aşaması, motor iş parçacığı |
| Effects | `screensync.effects` | 11 efekt, donanım eşlemesi, yazılım renderı, ışık hassasiyeti koruması, runner |
| Profiles | `screensync.profiles` | model + doğrulama, 12 hazır profil, atomik JSON deposu, içe/dışa aktarma |
| Automation | `screensync.automation` | kural protokolü (süreç, zamanlama, tam ekran), kenar tetiklemeli servis |
| Core | `screensync.core` | denetleyici, ayarlar, performans profilleri, Windows başlangıç kaydı |
| UI | `screensync.ui` | tema/tasarım tokenları, bileşenler, sayfalar, tepsi, olaylar |
| i18n | `screensync.i18n` | JSON yerelleştirme (tr birincil, en) |

## İş parçacıkları ve veri akışı

- **DeviceWorker** yalnızca *istenen durumu* (4 renk veya donanım efekti) alır; en son gönderilen kazanır, böylece yavaş cihaz kuyruk biriktirmez.
  Her döngüde onaylanan durumla karşılaştırır ve yalnızca değişen bölgeler için `select + steady` gönderir (aynı renkli bölgeler tek maskede).
- **ScreenSyncEngine** analiz hızı (performans profili: 6/12/24 fps) ile geçiş tikini (20/30 Hz) ayırır; HID hızı worker'da ayrıca sınırlanır.
  Yakalama API'sine yalnızca analiz zamanı geldiğinde dokunulur (1440p geri okuma ~5–7 ms).
- **GUI** 30 Hz'de `snapshot()` çeker (yalnızca görünürken); gizliyken 2 s'lik arka plan zamanlayıcısı watchdog ve tepsi günceller.
  GUI testleri ekran senkronu sırasında olay döngüsünün 250 ms'den uzun bloklanmadığını doğrular.

## Ekran yakalama değerlendirmesi

Hedef makinede ölçüldü (2560×1440, Intel UHD + RTX 5060, tek ekran):

| Arka uç | Gecikme (medyan) | Notlar | Karar |
|---|---|---|---|
| DXGI Desktop Duplication (`dxcam`, `dxgi`) | 5,6 ms | yalnızca ekran değişince kare verir (boşta bedava), imleç dahil değil, kilit ekranında erişim kaybı | **Varsayılan** |
| Windows Graphics Capture (`dxcam`, `winrt`) | 5,1 ms | bazı tam ekran uygulamalarda daha sağlam | Otomatik yedek 1 |
| GDI BitBlt (`mss`) | 27–44 ms | her zaman kare döner, en uyumlu | Otomatik yedek 2 |

dxcam'in yerleşik kurtarması (kilit ekranında) uyuyarak sonsuz dener; kamera örneği başına `_recover_output` bir istisnaya
çevrildi, kurtarma motorun kesilebilir üstel beklemesiyle yapılır.

**HDR**: `DisplayConfigGetDeviceInfo(ADVANCED_COLOR_INFO_2)` (Windows 11 24H2+, `highDynamicRangeSupported` + `activeColorMode`) ile algılanır; eski sürümlerde v1'e düşülür (v1 geniş renk/ACM'yi de "gelişmiş renk" sayar). DXGI `DuplicateOutput` Windows'un SDR'ye
dönüştürdüğü 8 bit görüntüyü verir; renkler soluk olabileceği için "HDR telafisi" doygunluğu %20 artırır ve kullanıcı bilgilendirilir.

**DPI**: süreç Per-Monitor-V2 DPI farkındalığında çalışır; monitör geometrisi fiziksel pikseldir. Bölge seçimi yüzdeseldir.

## Hata kurtarma

| Durum | Davranış |
|---|---|
| Cihaz yok / erişim reddi / G/Ç hatası | worker kapatır, üstel bekleme (1→30 s), yeniden bağlanınca istenen durumu tekrar gönderir |
| HID zaman aşımı | yazım 1,5 s'yi aşarsa "yanıt vermiyor" gösterilir (GUI etkilenmez, ayrı iş parçacığı) |
| Uyku / devam (S3) | `WM_POWERBROADCAST`: suspend → yakalama durur, HID kapanır; resume → yeniden bağlan + durumu yeniden gönder |
| Modern Standby (S0ix, bu laptop) | `PBT_APMSUSPEND` gelmez → `RegisterPowerSettingNotification(GUID_CONSOLE_DISPLAY_STATE)`: ekran kapanınca yakalama durur, açılınca renkler yeniden gönderilir + yakalama sürer (gerçek donanımda doğrulandı) |
| Oturum kilidi | `WTSRegisterSessionNotification`: kilitte yakalama durur, açılınca devam + durum yeniden gönderilir |
| Yakalama kaybı / çözünürlük değişimi / monitör çıkışı | kamera kapatılır, kesilebilir backoff ile yeniden açılır, monitör yoksa birincile düşülür. Otomatik modda geçici erişim kaybı (`CaptureAccessLost`) yedek yönteme düşürmez; yedek yönteme düşülmüşse 30 sn'de bir DXGI'ye kesintisiz geri dönüş denenir |
| İş parçacığı çökmesi | watchdog (2 s) 5 dk'da en fazla 5 kez yeniden başlatır |
| Bozuk profil/ayar dosyası | yedeklenir (`*.corrupt-<ts>.json`), varsayılanlar/hazır profiller kullanılır |
| İkinci örnek | `QLocalServer` tek örnek; ikinci örnek ilkine "göster"/"çık" mesajı yollar (iki süreç aynı anda HID'e yazmaz) |

## Bağımlılıklar

Python 3.12 (uv yönetimli), PySide6-Essentials 6.12 (WebEngine yok), hidapi 0.15, numpy 2.5, opencv-python-headless 5.0
(headless: PySide6 ile Qt eklenti çakışması olmaz), dxcam 0.3 [+winrt], mss 10.2, psutil 7.2. Sürümler `uv.lock` ile sabitlenmiştir.
