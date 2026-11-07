# Renk Motoru

Kod: [`src/screensync/color/`](../src/screensync/color/), [`src/screensync/sync/`](../src/screensync/sync/)

## Boru hattı

1. **Yakala** (DXGI) → 1440p BGRA kare, GPU'dan CPU'ya geri okuma.
2. **Küçült**: tamsayı adımlı örnekleme (belleğin ~1/16'sı) + `INTER_AREA` → **160×90** RGB. Yaklaşık 2–3 ms.
3. **Letterbox**: kenarlardaki %98,5'i siyah satır/sütunlar; *zaman penceresindeki minimum* alınır (24 analiz), bu yüzden karanlık sahne kırpılmaz. Kenar başına en fazla %30.
4. **Özellikler**: sRGB → doğrusal (LUT) → **OKLab**; her piksel için L, kroma, konum.
5. **Ağırlıklar** (mod bazlı): karanlık eşiği (smoothstep), kroma ağırlığı, altyazı bastırma, merkez/kenar ağırlığı.
6. **Kümeleme**: OKLab ızgara histogramı (25×33×33) → en ağır ≤600 kutu üzerinde **deterministik ağırlıklı k-means** (en uzak-ilk başlatma, rastgelelik yok) → algısal olarak ayırt edilemeyen kümelerin birleştirilmesi.
7. **Seçim** (algoritmaya göre) → 4 bölge hedefi (OKLab).
8. **Geçiş motoru** → eşleme, EMA, histerezis, zaman tabanlı OKLab yaklaşımı.
9. **Çıkış**: doygunluk (kroma ölçeği), gamut kırpma (ton ve L korunur), parlaklık, LED kazancı/gama → 8 bit.
10. **Ölü bant** + worker'ın birebir tekrar bastırması → yalnızca gerekli HID yazımları.

## Neden OKLab?

CIELAB, HSV ve OKLab değerlendirildi. HSV algısal değildir (sarı ve mavi aynı "V"de çok farklı parlaklıkta).
CIELAB'ın mavi bölgesinde ton kayması vardır (mavi→beyaz geçişte morlaşma). OKLab bir 3×3 matris + küp kök kadar ucuzdur,
tonu doğrusala yakın korur ve Öklid uzaklığı iyi bir algısal fark ölçüsüdür (ΔE_ok: 0,02 ≈ fark edilebilir, 0,1 = açıkça farklı).
Hem kümeleme hem enterpolasyon hem de eşleme OKLab'da yapılır.

## Algoritmalar

| Mod | Seçim | Not |
|---|---|---|
| **Baskın** | skor = pay × (0,6 + 0,8·kroma) en yüksek küme → 4 bölge | siyah ve altyazı ağırlıksız; parlaklık sahne anahtarına göre |
| **Çok renkli palet** | skor = pay^0,55 × (0,35 + kroma) × açıklık faktörü; en az 0,065 ΔE uzaklıkla açgözlü 4 seçim; pay ≥ %1,5 | renk sayısı < 4 ise bölgeler paya göre paylaştırılır (tek renk → 4 bölge aynı), soldan sağa x-ağırlık merkezine göre dizilir |
| **Konumsal** | ekran 4 dikey şerit (±%4 örtüşme), her şeritte baskın renk; komşu harmanlaması %5 | şerit karanlıksa bölge karanlık (ambilight) |
| **Sinematik** | kroma ağırlığı 0,9; ≥ %0,3 alan kaplayan doygun vurgular korunur; bölgeler görsel skora göre paylaştırılır | sahne karanlık kalır, vurgu %35'e kadar taban parlaklık alır |
| **Uyarlanabilir** | deterministik kurallar + histerezis (4 analiz; sahne kesmesinde anında) | karanlık → sinematik, tek renk → baskın, sol/sağ farklı (şerit ΔE ≥ 0,16) → konumsal, diğer → palet |

Kullanıcının örneği (kırmızı çiçekler, açık mavi gökyüzü, krem duvar, bordo detaylar) palet modunda tam bu 4 rengi üretir
(`tests/test_color_engine.py::test_film_scene_four_meaningful_colors`).

## Özel sorunlara çözümler

| Sorun | Çözüm | Test |
|---|---|---|
| Siyah alanlar baskın rengi bozuyor | karanlık eşiği altındaki pikseller sıfır ağırlık; parlaklık ayrıca sahne anahtarıyla zarflanır | `test_black_pixels_do_not_dominate` |
| Beyaz altyazılar | alt %22 bantta parlak (L>0,55) ve renksiz (C<0,06) piksel ağırlığı ×0,03; letterbox içindeki altyazılar zaten kırpılır | `test_subtitle_strip_rejected` |
| Küçük renkli nesneler titreşim yapıyor | küme payı eşiği (%1,5), histerezis, EMA | `test_tiny_objects_ignored` |
| Tek renkli sahnede rastgele 4 renk | uzaklık eşiği + paya göre paylaştırma; gürültüye karşı ızgara histogramı | `test_single_color_scene_no_random_colors` |
| Renklerin bölge değiştirmesi | 4×4 kesin atama (24 permütasyon), 0,02 yapışkanlık | `test_palette_assignment_prevents_zone_hopping` |
| Sahne kesmelerinde gecikme | sinyal: 4×4 ızgara OKLab ortalamaları; kesme = skor ≥ 0,09 ve ≥ 3× hareketli ortalama; 0,35 s boyunca τ ≤ 0,1 s | `test_bounded_latency_on_scene_cut` |
| Fare / küçük UI öğeleri | DXGI imleci içermez; küçültme + küme payı eşiği | `test_tiny_objects_ignored` |
| Strobe sahneler | 1 s'de ≥ 3 kesme → 2 s hızlı geçiş kapalı | `test_flash_guard_disables_fast_cuts` |

## Geçiş parametreleri

| Ayar | Eşleme |
|---|---|
| Geçiş hızı 0–100 | τ = 1,4 s → 0,06 s (log) ; çerçeve hızından bağımsız `1 − e^(−dt/τ)` |
| Yumuşatma 0–100 | hedef EMA'sı α = 1 − 0,85·s |
| Hassasiyet 0–100 | histerezis eşiği ΔE = 0,10 → 0,004 (log) |
| Minimum renk farkı | geçiş sırasında kanal farkı < N ise gönderme; yakınsamada son değer her zaman gönderilir |
| Siyah seviyesi | analizdeki karanlık eşiği (OKLab L) |
| Parlaklık / doygunluk | çıkış aşaması; anında etkili |
| Güncelleme hızı 1–15 Hz | DeviceWorker kapısı |

## Statik sahneler

DXGI ekran değişmedikçe kare vermez → analiz yapılmaz. GDI/sentetik kaynaklarda imza farkı < 0,004 ise analiz atlanır.
Geçiş yakınsadıktan ve 1 s yeni kare gelmedikten sonra motor tikini ≤ 10 Hz'e düşürür. Sonuç: durağan ekranda HID trafiği sıfıra iner.
