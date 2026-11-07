# Performans Ölçümleri

Makine: MSI Katana 15 HX B14W, Windows 11 Pro 26200, Intel iGPU + RTX 5060 Laptop, 24 mantıksal çekirdek, tek ekran 2560×1440 @165 Hz (SDR, HDR destekli ama kapalı).
Python 3.12.14. Tarih: 2026-11-07.

Yeniden üretmek için:

```bash
uv run python scripts/benchmark.py --animate --hardware --seconds 10
```

Ham sonuç: [`benchmarks/results-20261107-232240-hw.json`](../benchmarks/results-20261107-232240-hw.json) ·
donanım gecikmesi: [`benchmarks/hardware_results.json`](../benchmarks/hardware_results.json).
`--animate` ölçümü bozmaması için ayrı bir süreçte tam ekran, yavaş renk kayan bir pencere açar (DXGI'nin kare üretmesi için).

## Uçtan uca (gerçek MS-1565, canlı DXGI, "Dengeli")

| Ölçüm | Değer |
|---|---|
| Analiz hızı (hedef 12) | 11,5 /s |
| Yakalama gecikmesi | 5,6 ms |
| Renk çıkarma (palet) | 2,1 ms |
| Geçiş işleme | 0,38 ms |
| Yakalama → gönderim (işlem) | 8,3 ms |
| Etkili RGB güncellemesi (sınır 10 Hz) | 9,4 /s |
| HID paketleri (10 s) | 744 (~74/s) |
| İstek → HID yazımı gecikmesi | medyan 23,5 ms · p95 41 ms · maks 114 ms (hız kapısı dahil) |
| HID hataları / onay hatası | **0 / 0** |
| Birleştirilen (atlanan ara) kareler | 261 |
| Düşen tik | 0 |
| Motor iş parçacığı CPU | tek çekirdeğin %9,3'ü |
| Süreç CPU (toplam) | %0,39 |

## Paketlenmiş uygulama (exe, pencere açık, ekran senkronu + uyarlanabilir mod)

| Ölçüm | Değer |
|---|---|
| Kararlı durum CPU (10 s) | toplam CPU'nun %0,92'si (GUI 30 Hz önizleme dahil) |
| Working set / private | 238 MB / 219 MB |
| İş parçacığı | 22 |
| Dağıtım boyutu | 189 MB (tek klasör) |

Not: İlk sürümde private bellek 956 MB idi; nedeni 24 iş parçacıklı OpenBLAS havuzunun iş parçacığı başına bellek ayırmasıydı.
`OPENBLAS_NUM_THREADS=1` ve `cv2.setNumThreads(1)` ile 219 MB'a indi (matrisler 4×3 / 160×90 olduğundan paralellik gereksiz).

## Bileşenler

### Ekran yakalama (1440p tam ekran → 160×90)

| Arka uç | Medyan | p95 |
|---|---|---|
| DXGI Desktop Duplication | 5,6 ms | 6,7 ms |
| Windows Graphics Capture | 5,1 ms | 6,5 ms |
| GDI (mss) | 26,8 ms | 29,9 ms |

### Renk çıkarma (160×90, 4 sentetik sahne karışımı, gürültü sahnesi dahil)

| Mod | Medyan | p95 |
|---|---|---|
| Baskın | 1,57 ms | 3,7 ms |
| Palet | 1,63 ms | 4,4 ms |
| Konumsal | 2,26 ms | 6,4 ms |
| Sinematik | 1,68 ms | 4,5 ms |
| Uyarlanabilir | 3,81 ms | 11,6 ms |

Optimizasyon öncesi p95 değerleri 11–43 ms idi (dokulu karelerde binlerce histogram kutusu). k-means artık en ağır 600 kutuda
çalışıyor, kalan kutular tek vektörel adımla atanıyor; gamut kırpma vektörleştirildi (geçiş adımı 0,49 → 0,18 ms).

### Performans profilleri (sentetik kare, sahte HID)

| Profil | Analiz/s | HID güncelleme/s | Motor CPU (1 çekirdek) |
|---|---|---|---|
| Eko | 6,0 | 6,2 | %3,1 |
| Dengeli | 12,0 | 10,2 | %3,1 |
| Hızlı tepki | 6,0* | 8,7 | %7,7 |

\* Sentetik sahne yavaş değiştiği için kareler "statik" sayılıp atlandı; gerçek içerikte 24/s'e kadar analiz yapılır. Tüm profillerde HID sınırı ≤ 15 Hz.

### HID (gerçek donanım, `scripts/hw_validate.py latency`)

| Hedef | Elde edilen | Kare (4 bölge) medyan | Paket medyan | İş parçacığı doluluk |
|---|---|---|---|---|
| 5 Hz | 5,26 Hz | 5,2 ms | 0,60 ms | %2,8 |
| 10 Hz | 10,24 Hz | 5,4 ms | 0,61 ms | %5,6 |
| 15 Hz | 15,23 Hz | 5,0 ms | 0,59 ms | %7,9 |

Varsayılan 10 Hz seçildi: 15 Hz kararlı ve takılmasız gözlemlendi, ancak ekran senkronunda 10 Hz'in üzeri görsel olarak fark yaratmazken HID trafiğini artırır.

## Windows zamanlama notu

`time.monotonic()` Windows'ta 15,6 ms çözünürlüklüdür ve `Event/Condition.wait` aynı ayrıntıdadır. Bu, ilk ölçümlerde 12 Hz hedefin
~10 Hz'e düşmesine ve gecikmelerin 16 ms'nin katları görünmesine neden oluyordu. Tüm zamanlama `time.perf_counter()`'a taşındı ve
kısa beklemelerde (≤ 60 ms) Python 3.12'nin yüksek çözünürlüklü `time.sleep`'i kullanılıyor.
