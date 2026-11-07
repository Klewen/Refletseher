# Güvenlik

## Neden `0xA0` asla gönderilmez

`0xA0` efektleri kontrolcünün **kalıcı flash belleğine** yazar. Gerçek zamanlı senkronizasyon saniyede 10–15 güncelleme
üretir; her güncellemede flash'a yazmak:

- flash hücrelerini sınırlı yazma ömrü nedeniyle hızla aşındırabilir,
- yarım kalan bir yazımda (güç kesintisi, uyku) kontrolcüyü tanımsız bir duruma sokabilir,
- kullanıcının MSI Center ile kaydettiği varsayılan aydınlatmayı kalıcı olarak değiştirir.

Önizleme ve ekran senkronu için kalıcılık gerekmez: `0x01/0x02` ile yazılan durum yeniden başlatmaya kadar geçerlidir.
Bu yüzden `0xA0` (ve `0xB0`, `0xFF`) **hiçbir kod yolunda üretilmez** ve üretilse bile sürücü katmanında reddedilir.

## Katmanlı koruma

1. **Oluşturucu**: `protocol.py` yalnızca `build_select_zones()` ve `build_effect()/build_steady()` sağlar; başka paket üretemez.
2. **İzin listesi**: `ALLOWED_PACKET_IDS = {0x01, 0x02}`. `FORBIDDEN_PACKET_IDS` yalnızca açıklayıcı hata mesajı içindir.
3. **Doğrulama kapısı**: `GuardedTransport.send_feature_report()` her paketi `validate_packet()`'tan geçirir; ihlal → `ProtocolViolation`, paket `hidapi`'ye ulaşmaz.
4. **Okuma sınırı**: yalnızca `get_feature_report(0x01, 64)`.
5. **Tek yazıcı**: Tüm HID erişimi `DeviceWorker` iş parçacığındadır. GUI `hidapi`'yi içe aktarmaz; `HidapiBackend` tek içe aktarma noktasıdır.
6. **Hız sınırı**: renk kareleri en fazla 15 Hz (`MinInterval`), ayrıca sert 120 paket/s token bucket. Kopya renkler gönderilmez.
7. **Cihaz kimliği**: yalnızca VID `0x1462` / PID `0x1601`, usage page 0xFF / usage 1 açılır; başka HID cihazına komut gönderilmez.

Testler: `tests/test_protocol.py` (yasak id'ler, uzunluk, dolgu, maske, renk sınırları, flash paketinin transport'a ulaşmaması),
`tests/test_app.py::test_flash_command_never_sent` (uygulamanın tüm modlarında yalnızca 0x01/0x02 gönderildiği).

## Yapılmayanlar

- Firmware, BIOS veya Embedded Controller'a erişim yok.
- HID sürücüsü değiştirilmez; Zadig/libusb kurulmaz.
- MSI hizmetleri durdurulmaz, kaldırılmaz; MSI Center'a dokunulmaz. Çakışma yalnızca **salt-okunur** süreç listesiyle tespit edilir ve kullanıcıya yönerge verilir.
- DRM/korumalı içerik yakalama kısıtları aşılmaz; siyah kare görülürse kullanıcı bilgilendirilir.
- Yakalanan görüntüler diske yazılmaz, ağa gönderilmez; yalnızca 160×90 analiz karesi bellekte tutulur (GUI önizlemesi için).
- Windows Defender'ı atlatmaya yönelik paketleme/gizleme yok: tek klasörlü PyInstaller çıktısı, UPX kapalı, kod gizleme yok.

## Işık hassasiyeti (fotosensitivite)

- Tüm efektler ≥ 1 s döngü süresi; döngüsel efektlerde **renk başına ≥ 0,34 s** → en kötü siyah/beyaz palette bile ≤ ~1,5 parlaklık flaşı/s
  (WCAG genel flaş eşiği 3/s). Test: `tests/test_app.py::test_effects_are_photosensitivity_safe` (WCAG tarzı bağıl parlaklık salınımı sayımı, tüm efektler, en hızlı ayar).
- Varsayılan olarak strobe/flaş efekti yoktur; nabız efekti tam kararmaz (%12 taban).
- Ekran senkronunda "Işık hassasiyeti koruması": 1 s içinde ≥ 3 sert sahne kesmesi olursa hızlı geçişler 2 s boyunca kapatılır ve normal yumuşatma kullanılır.

## Hata durumunda davranış

- Sonsuz yeniden deneme döngüsü yok: cihaz/yakalama hatalarında üstel bekleme (1, 2, 4, … en fazla 30 s; kilit ekranında en fazla 5 s).
- Çöken iş parçacıkları 5 dakikada en fazla 5 kez yeniden başlatılır.
- Geçersiz bir durum (ör. hatalı efekt) worker'a ulaşmadan çağıranın iş parçacığında reddedilir.
