# Test Stratejisi

```bash
uv run pytest -q
```

Son çalıştırma: **157 geçti, 4 atlandı** (atlananlar opt-in donanım testleri). Süre ~20 s. Gerçek ekran veya klavye gerektirmez.

## Paketler

| Dosya | Kapsam |
|---|---|
| `tests/test_protocol.py` | doğrulanmış koda bayt bayt eşitlik, 64 bayt doğrulama, maske/renk sınırları, yasak id'ler (0xA0/0xB0/0xFF/bilinmeyen), dolgu, sabit baytlar, hız sınırları, VID/PID eşleme, belirsiz cihaz, sürücü sırası ve onay okuması |
| `tests/test_worker.py` | bağlanma, tekrar bastırma, yalnızca değişen bölgeler, hız sınırı + birleştirme (son durum her zaman uygulanır), çok iş parçacıklı sıralama (tüm yazımlar tek iş parçacığından, select/effect çiftleri bozulmaz), donanım efekti, cihaz yok → takıldı, kopma → yeniden gönderme, erişim reddi backoff (meşgul döngü yok), askıya alma/devam, temiz durdurma, token bucket, backoff |
| `tests/test_color_engine.py` | kırmızı/mavi/yeşil/beyaz/siyah, siyah alan baskınlığı, 4 renk soldan sağa, kullanıcının film örneği, tek renk sahnede rastgele renk yok, doygun çok renk, küçük nesne, altyazı, determinizm, konumsal eşleme, karanlık şerit, sinematik karanlık+vurgu, uyarlanabilir sınıflandırma ve histerezis, letterbox ve karanlık sahne koruması, sahne kesmesi, yavaş hareketin kesme sayılmaması, flaş koruması |
| `tests/test_transition.py` | kırmızı→mavi yumuşak ve monoton geçiş, sahne kesmesinde sınırlı gecikme, flaş korumasında hızlı geçişin kapanması, histerezisin gürültüyü yok sayması, EMA kararlılığı, palet ataması (bölge zıplaması yok), parametre eşlemeleri, ölü bant (son değer her zaman, bir kez), yakınsayınca gönderimin durması, parlaklık/doygunluk çıkışı |
| `tests/test_app.py` | manuel bölge kontrolü, parlaklık ve güç, geri al, mod geçişi (donanım/yazılım efekti), uçtan uca ekran senkronu (sentetik), yakalama kaybından kurtulma, cihaz kopmasında istenen/onaylanan ayrımı, watchdog, profil uygula + çıkışta geri yükleme, temiz kapanış, **hiçbir modda 0x01/0x02 dışı paket gönderilmemesi**, hazır profiller, kaydet/yükle/çoğalt/sil, geçersiz profil, bozuk dosya kurtarma, içe/dışa aktarma, geçersiz ayarlar, 11 efektin geçerli renk üretmesi, **ışık hassasiyeti (≤ 3 flaş/s, en kötü palette bile)**, donanım eşlemesi, otomasyon (zaman aralığı, öncelik, kenar tetikleme, geri dönüş, elle seçimin önceliği), çakışma sınıflandırma, statik sahnede iş azaltma |
| `tests/test_ui.py` | tr/en anahtar eşitliği, yinelenen anahtar yok, koddaki tüm anahtarlar mevcut, dinamik anahtar aileleri, çeviri yedeği; GUI: tüm sayfalar, **ekran senkronu sırasında olay döngüsü < 250 ms bloklanır**, stüdyo tıklamasının cihaza ulaşması, tepsiye küçült / temiz çıkış |
| `tests/hardware/test_hardware_smoke.py` | **opt-in**: tek cihaz, 4 bölge yazımı, yerel efekt, gerçek donanımda hız sınırı |

## Sentetik kareler

`refletseher.capture.synthetic`: `solid`, `vertical_bands`, `horizontal_bands`, `blobs`, `with_letterbox`, `with_subtitle`, `moving_scene`
ve başarısızlık enjekte edebilen `SyntheticBackend`. Ekran yakalama olmadan tüm renk motoru ve uçtan uca senkron test edilir.

## Sahte HID

`MockBackend` gerçek arayüzün aynısını uygular, aldığı paketleri çözer ve bir *simüle* klavye modeli tutar. Bağlantı kopması,
erişim reddi, yazma hatası, kısa yazım ve gecikme enjekte edilebilir. Uygulama `--simulate` ile bu arka uçla çalışır ve arayüz her yerde "Simülasyon" yazar.

## Donanım testleri

Otomatik testler fiziksel klavyeye **hiçbir zaman** yazmaz. Donanım testleri yalnızca açıkça istendiğinde çalışır:

```bash
uv run pytest tests/hardware --run-hardware
```

Son çalıştırma (2026-11-07): 4/4 geçti.

## Ekran görüntüleri

```bash
uv run python scripts/ui_snapshots.py docs/screenshots
```

Simüle cihaz ve sentetik ekranla tüm sayfaları PNG'ye render eder (arayüz regresyonlarını görsel kontrol için).
