# MS-1565 HID Protokolü

Bu belge, Refletseher'nin MSI MysticLight MS-1565 kontrolcüsüyle nasıl konuştuğunu anlatır.
**Doğrulanmış** (gerçek donanımda gözlemlenmiş) davranış ile **belgelenmiş/teorik** davranış ayrı işaretlenmiştir.

Kod: [`src/refletseher/device/protocol.py`](../src/refletseher/device/protocol.py), [`driver.py`](../src/refletseher/device/driver.py), [`transport.py`](../src/refletseher/device/transport.py)

## Cihaz kimliği (doğrulandı)

| Alan | Değer |
|---|---|
| Üretici / Ürün | `MSI` / `MysticLight MS-1565` |
| VID / PID | `0x1462` / `0x1601` |
| Interface | `0` |
| Usage Page / Usage | `0xFF` (hidapi 255 bildiriyor) / `1` |
| Bus | hidapi `bus_type = 1` |
| Yol (örnek) | `\\?\HID#VID_1462&PID_1601#...` |

Eşleme katıdır: VID/PID tutmayan veya farklı bir HID koleksiyonuna (ör. klavye usage page'i) ait cihaz **açılmaz**. Birden fazla eşleşme olursa yalnızca tam doğrulanmış koleksiyon (usage page 0xFF, usage 1, interface 0) seçilir; aksi halde `AmbiguousDevice` hatası verilir.

## Taşıma (doğrulandı)

- Windows HID, `cython-hidapi` (`import hid`), `hid.device().open_path(path)`.
- Her paket **64 baytlık feature report**, report id `0x02`: `[0x02, packet_id, payload..., 0x00 dolgu]`.
- `send_feature_report` dönüşü `64` olmalı; değilse hata.
- Her yazımdan sonra `get_feature_report(0x01, 64)` okunur, sonucu **yorumlanmaz**, hatası yok sayılır (orijinal doğrulanmış kodla aynı). Ölçüm: 962/962 okuma başarılı.

## Paket kimlikleri

| ID | Anlam | Durum |
|---|---|---|
| `0x01` | Bölge seçimi, 1 bayt maske | **Doğrulandı**, izin listesinde |
| `0x02` | Seçili bölgelerin efektini ayarla | **Doğrulandı**, izin listesinde |
| `0xA0` | Efektleri flash'a kaydet (kalıcı) | **YASAK** — sürücüde engellenir |
| `0xB0` | Efektleri flash'tan yükle | **YASAK** — sürücüde engellenir |
| `0xFF` | Belgelenmemiş (MCU yeniden başlatma?) | **YASAK** — sürücüde engellenir |
| diğer | — | İzin listesinde değil → reddedilir |

## Bölge maskeleri (doğrulandı, 2026-11-07)

| Bölge | Maske | Fiziksel konum |
|---|---|---|
| Zone 1 | `0x01` | Sol (Esc…F4, WASD bölgesi) |
| Zone 2 | `0x02` | Sol-orta |
| Zone 3 | `0x04` | Sağ-orta (Enter, oklar) |
| Zone 4 | `0x08` | Sağ (numpad) |
| Tümü | `0x0F` | |

Kullanıcı R-G-B-W testiyle soldan sağa sırayı gözlemleyerek onayladı. Maskeler birleştirilebilir (ör. `0x05` = Zone 1 + 3); uygulama aynı renge sahip bölgeleri tek pakette gruplar.

## Efekt paketi (`0x02`) yerleşimi

| Rapor ofseti | Boyut | Alan |
|---|---|---|
| 0 | u8 | report id `0x02` |
| 1 | u8 | packet id `0x02` |
| 2 | u8 | efekt türü: 0 kapalı, 1 sabit, 2 nefes, 3 renk döngüsü, 4 dalga |
| 3–4 | u16 LE | hız: bir tam döngünün süresi × 100 (santisaniye) |
| 5–8 | 4 × u8 | sabit `00 00 0F 01` (anlamı bilinmiyor; daima aynen gönderilir) |
| 9 | u8 | yön: 0 sağdan sola, 1 soldan sağa |
| 10… | 4 bayt × n | anahtar kareler: `zaman(0..100), R, G, B` |
| kalan | | sıfır dolgu |

Doğrulanmış sabit renk paketi (kullanıcının çalışan kodu, sürücünün ürettiği paketle **bayt bayt aynı**, testle güvence altında):

```
02 02 01 58 02 00 00 0F 01 00 | 00 FF 00 00 | 64 FF 00 00 | 00 ... (64 bayt)
          ^speed=600          ^dir  ^kf0 t=0 kırmızı ^kf1 t=100 kırmızı
```

### Efekt türleri

| Tür | Kod | Durum |
|---|---|---|
| Sabit (steady) | 1 | **Doğrulandı** (orijinal test + 4 bölge testi) |
| Nefes (breath) | 2 | **Gözlemle doğrulandı** (2026-11-07) |
| Renk döngüsü | 3 | **Gözlemle doğrulandı** |
| Dalga | 4 | **Gözlemle doğrulandı**, yön 1 = soldan sağa |
| Kapalı (disable) | 0 | Belgelenmiş, **kullanılmıyor** — "kapalı" için sabit siyah gönderilir (doğrulanmış yol) |

### Anahtar kare kuralları (sürücüde zorunlu)

- 2–10 anahtar kare; ilki `t=0`, sonuncusu `t=100`, aradakiler artan, `t=100` yalnızca son karede.
- MCU döngüyü kendiliğinden kapatmaz: döngüsel efektlerde ilk renk sona tekrar eklenir.
- Hız: sabit/kapalı için daima 600; animasyonlarda 100–6000 cs (1–60 s). Alt sınır 1 s, ışık hassasiyeti sınırıdır.

## Doğrulama kapısı

`protocol.validate_packet()` her paket için, `hidapi`'ye ulaşmadan önce çalışır (`GuardedTransport`):
uzunluk tam 64, report id 0x02, packet id izin listesinde, maske 0x01–0x0F, efekt türü bilinen, hız aralıkta,
sabit baytlar `00 00 0F 01`, yön 0/1, anahtar kareler geçerli ve **dolgu tamamen sıfır**.
Okuma da yalnızca `report 0x01 / 64 bayt` ile sınırlıdır.

## Durum okuma

Kontrolcünün mevcut renklerini okuyan bir protokol **doğrulanmadı**. `report 0x01` okuması yalnızca onay amaçlı yapılır
ve içeriği yorumlanmaz. Bu yüzden uygulama başlangıçta donanım renklerini bildiğini varsaymaz; "Yazıldı" yalnızca
başarılı HID yazımını ifade eder, LED'lerin fiziksel rengini değil.

## Kaynak karşılaştırması

| Kaynak | Katkı | Kullanılmayan kısım |
|---|---|---|
| natanalt gist | Paket kimlikleri, efekt yerleşimi, anahtar kare kuralları | `0xA0/0xB0/0xFF` |
| sarpowsky/msi-katana-rgb (Python) | Aynı yerleşim, hız = s×100, onay okuması | Her uygulamada flash kaydı seçeneği |
| jeremylanes/msi-rgb (Rust, Linux) | Maske önbelleği, parlaklık = RGB ölçekleme, 33 FPS deneyimi | Linux `hidraw/ioctl`, `apply_*` sonrası otomatik `0xA0` |

Linux'a özgü kod kullanılmadı; yalnızca Windows'ta doğrulanmış `hidapi` yolu temel alındı.

## Ölçülen zamanlama (gerçek donanım)

Paket başına ~0,6 ms (onay okuması dahil), 4 bölgelik tam kare ~5 ms. 5/10/15 Hz'de gecikmeli kare yok, gözle görülür takılma yok.
Ayrıntı: [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md), [BENCHMARKS.md](BENCHMARKS.md).
