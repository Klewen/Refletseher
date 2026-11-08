# Donanım Doğrulaması

"Doğrulandı" = gerçek MSI Katana 15 HX B14W üzerinde çalıştırıldı **ve** (görsel davranışsa) kullanıcı tarafından gözlemlendi.
"Simülasyon" = yalnızca sahte HID (MockBackend) ile test edildi. "Beklemede" = henüz gerçek donanımda doğrulanmadı.

## Sonuçlar (2026-11-07)

| # | Özellik | Yöntem | Sonuç |
|---|---|---|---|
| 1 | Cihaz bulunuyor (VID 1462 / PID 1601, usage page 0xFF, usage 1, interface 0) | `hw_validate.py probe` | **Doğrulandı** |
| 2 | Sürücü paketi = kullanıcının çalışan kodu | `hw_validate.py snippet` | **Doğrulandı** (bayt bayt aynı) |
| 3 | 4 bölgeye ayrı renk (Z1 kırmızı, Z2 yeşil, Z3 mavi, Z4 beyaz) | `hw_validate.py zones` + gözlem | **Doğrulandı** (soldan sağa sıra doğru) |
| 4 | Nefes (tür 2) | `hw_validate.py effects` + gözlem | **Doğrulandı** |
| 5 | Renk döngüsü (tür 3) | aynı | **Doğrulandı** |
| 6 | Dalga (tür 4), yön 1 = soldan sağa | aynı | **Doğrulandı** |
| 7 | 5/10/15 Hz bölge güncellemesi, takılma yok | `hw_validate.py latency` + gözlem | **Doğrulandı** (0 geç kare, ~0,6 ms/paket) |
| 8 | Onay okuması (report 0x01) | ölçüm | **Doğrulandı** (962/962 + 744/744 başarılı) |
| 9 | Paketlenmiş exe Windows 11'de açılıyor, pencere + tepsi ikonu | exe + gözlem | **Doğrulandı** |
| 10 | Ekran senkronu canlı görüntüyle (DXGI) | exe + `live_validation.py` | **Doğrulandı** |
| 11 | Konumsal ambilight: 4 ekran şeridi → 4 bölge doğru sırada | `live_validation.py` aşama 1 + gözlem | **Doğrulandı** |
| 12 | Yumuşak geçiş; sahne kesmesinde hızlı ama flaşsız tepki | `live_validation.py` aşama 2–3 + gözlem | **Doğrulandı** |
| 13 | 17 dk kesintisiz çalışma, HID hatası yok, `--quit` ile temiz kapanış (kod 0) | exe günlüğü | **Doğrulandı** |
| 14 | Tekrarlanan HID komutlarının bastırılması / hız sınırı | gerçek donanım benchmark + `tests/hardware` | **Doğrulandı** (≤ 10 Hz kapı, 0 hata) |
| 15 | Flash kaydı (0xA0) hiç gönderilmiyor | kod + testler + paket izi | **Doğrulandı** (yalnızca 0x01/0x02) |
| 16 | Manuel RGB (RGB Stüdyo) gerçek donanımda | uygulama yolu `set_steady` (#3 ile aynı komutlar) | Doğrulandı (komut düzeyinde); GUI ile ayrıca gözlenmedi |
| 17 | Sinematik: karanlık sahne + küçük kırmızı ışık → loş kırmızı; tam siyah → sönük | `cinema_reel.py` (gerçek yakalama + gerçek HID) + gözlem | **Doğrulandı** (2026-11-08) |
| 18 | Palet: film sahnesi (kırmızı çiçek / açık mavi gökyüzü / krem duvar / bordo) → 4 doğru renk | aynı | **Doğrulandı** |
| 19 | Palet: mavi sahne + beyaz altyazı → 4 bölge mavi, beyaz yansımıyor | aynı | **Doğrulandı** |
| 20 | Uyarlanabilir: letterbox'lı turuncu/mor sahne → turuncu-turuncu-mor-mor | aynı | **Doğrulandı** (5/5 sahnede istenen = yazılan, 0 HID hatası) |
| 21 | Oturum kilidi / açma (Win+L) | exe günlüğü + desen gözlemi | **Doğrulandı**: kilitte yakalama durdu, açılıştan 0,3 sn sonra yeniden başladı, klavye takip etti |
| 22 | Uyku / uyanma (Modern Standby, S0 Low Power Idle) | exe günlüğü + desen gözlemi | **Doğrulandı (düzeltme sonrası)**: ilk denemede uyku olayı gelmedi ve yakalama GDI'ye düşüp kaldı → ekran durumu bildirimi + DXGI'de bekleme/geri dönüş eklendi; ikinci denemede ekran kapanınca duraklatıldı, açılınca renkler yeniden gönderildi ve 0,13 sn'de DXGI açıldı |
| 23 | Uygulamaya göre profil otomasyonu | exe + `ping.exe` kuralı | **Doğrulandı**: süreç başlayınca 6 sn içinde "MSI Red", bitince "Screen Adaptive"e geri dönüş |
| 24 | Windows başlangıcında çalıştırma | uygulamanın `autostart` koduyla HKCU Run kaydı + aynı komutla başlatma | **Kısmen**: kayıt yazıldı (kullanıcı isteğiyle açık bırakıldı), komut uygulamayı tepside, gerçek veri klasörüyle başlattı; gerçek oturum açılışında otomatik başlama bir sonraki girişte gözlenecek |
| 25 | HDR | — | **Uygulanamaz**: dahili panel HDR desteklemiyor (Windows "Display does not support HDR"). Tespit kodu düzeltildi: v1 API geniş renk/ACM'yi HDR sanıyordu, artık `ADVANCED_COLOR_INFO_2` ile `hdr_supported=False` |
| 26 | Harici monitör / çoklu monitör | — | **Beklemede** (harici monitör bağlı değil) |
| 27 | MSI Center ile uzun süreli çakışma | süreç listesi | **Kısmen**: Mystic_Light_Service ve LEDKeeper2 çalışıyor; tüm testler boyunca renklerin üzerine yazıldığı gözlenmedi |
| 28 | Gerçek film/dizi içeriği (yayın uygulaması, DRM) | — | **Beklemede** (film benzeri test makarası doğrulandı; gerçek içerikte gözlem yapılmadı) |

## Tekrar çalıştırma

```bash
uv run python scripts/hw_validate.py snippet
```

```bash
uv run python scripts/hw_validate.py zones
```

```bash
uv run python scripts/hw_validate.py effects --seconds 60
```

```bash
uv run pytest tests/hardware --run-hardware
```

```bash
uv run python scripts/live_validation.py --seconds 45
```

```bash
uv run python scripts/cinema_reel.py
```

`live_validation.py`'yi uygulama ekran senkronundayken (ör. `Refletseher.exe --profile preset_gaming`) çalıştırın ve klavyeyi izleyin.

## Beklemedeki maddeler için kontrol listesi

- [ ] Bir sonraki oturum açılışında Refletseher'nin tepside kendiliğinden başladığını kontrol edin (kayıt artık kurulu kopyayı gösteriyor: `%LOCALAPPDATA%\Programs\Refletseher`; Ayarlar → "Windows başlangıcında çalıştır" ile kapatılabilir).
- [ ] Gerçek bir film/dizi sahnesinde Palet, Sinematik ve Uyarlanabilir modları izleyin.
- [ ] Harici monitör bağlayıp Ekran listesinden seçin.
