# Kullanım Kılavuzu

## Başlatma

- Kurulu kopya: **Başlat menüsü → "Refletseher"** veya masaüstündeki kısayol. Dosyalar `%LOCALAPPDATA%\Programs\Refletseher` klasöründedir.
  Uygulama çalışırken sistem tepsisinde (saatin yanında, gerekirse ^ okuna tıklayın) durur; simgeye tıklamak pencereyi açar.
- Kaynaktan derleyip kurmak/güncellemek: `scripts\build_exe.ps1` ardından `scripts\install_local.ps1`.
- Zip'ten: `Refletseher-win64.zip` dosyasını kalıcı bir klasöre çıkarıp `Refletseher.exe`'yi çalıştırın.
- Kaynaktan çalıştırma: `uv run refletseher`

Komut satırı seçenekleri:

| Seçenek | Etki |
|---|---|
| `--tray` | pencere açmadan sistem tepsisinde başlar |
| `--simulate` | HID cihazına erişmez; simüle klavye (arayüzde "Simülasyon" yazar) |
| `--profile ID` | başlangıçta profili uygular (ör. `preset_cinematic`) |
| `--quit` | çalışan örneği temiz şekilde kapatır |
| `--debug` | ayrıntılı günlük + HID paket izi |

**İmzasız uygulama uyarısı**: exe dijital olarak imzalanmamıştır. Windows SmartScreen ilk açılışta "Windows bilgisayarınızı korudu"
diyebilir → *Ek bilgi* → *Yine de çalıştır*. Bu, kod imzalama sertifikası olmayan her yerel derleme için normaldir; uygulama
güvenlik yazılımlarını atlatmaya çalışmaz. İsterseniz `scripts\build_exe.ps1` ile kendiniz derleyebilirsiniz.

## MSI Center hakkında

MSI Center / Mystic Light aynı kontrolcüye yazabilir. Refletseher bunu algılarsa sarı bir uyarı gösterir.
En temiz kullanım için MSI Center'da Mystic Light özelliğini kapatın veya kaldırın. Hizmeti durdurmak isterseniz `services.msc` ile kendiniz yapın.
Refletseher MSI hizmetlerine, sürücülere veya MSI Center'a dokunmaz. Uygulama kontrolcünün kalıcı belleğine yazmaz;
bilgisayar yeniden başlatıldığında klavye MSI'da kayıtlı varsayılana döner.

## Sayfalar

### Kontrol Paneli
Büyük klavye önizlemesi uygulamanın **göndermek istediği** renkleri gösterir. Sağ üstteki rozet durumu söyler:
*Klavyeye gönderildi* (yazım başarılı), *Gönderiliyor…*, *Gönderilemedi · cihaz bağlı değil*, *Donanım efekti · önizleme simülasyondur*.
Bir bölgeye tıklamak RGB Stüdyo'da o bölgeyi açar. Hızlı renkler, hızlı modlar ve son profiller buradadır.

### Ekran Senkronu
1. Ekranı ve yakalama yöntemini seçin (Otomatik önerilir).
2. Algoritma: **Palet** (film/dizi), **Sinematik** (karanlık, atmosferik içerik), **Konumsal** (oyun, ekran kenarları), **Baskın**, **Uyarlanabilir** (otomatik).
3. "Ekran senkronunu başlat".

Ayarlar: hassasiyet, geçiş hızı, yumuşatma, parlaklık, doygunluk, siyah seviyesi, minimum renk farkı, güncelleme hızı (1–15 Hz),
letterbox, altyazı koruması, sahne kesmesi, ışık hassasiyeti koruması, konumsal ağırlık, yakalama bölgesi (yüzde).
Sağda: bellekteki küçük analiz karesi (kaydedilmez), tespit edilen palet, hedef ve klavyeye giden renkler, performans göstergeleri.

DRM korumalı videolarda (bazı yayın uygulamaları) Windows siyah görüntü verir; uygulama bunu belirtir ve aşmaya çalışmaz.

### RGB Stüdyo
Klavyede bölgeye tıklayın (Ctrl/Shift ile çoklu), renk seçicide HSV karesi, ton çubuğu, HEX, RGB ve HSV değerleriyle rengi seçin — değişiklik anında uygulanır.
Ana parlaklık ve bölge parlaklığı, palet, favoriler (sağ tıkla kaldır), "Işıkları kapat/aç", "Önceki duruma dön" ve "Profil olarak kaydet".

### Efekt Stüdyosu
11 efekt. *Donanım + yazılım* etiketli olanlar klavyenin kendi işlemcisinde çalışabilir (Nefes, Renk döngüsü, Gökkuşağı, Dalga, Özel palet döngüsü);
bu durumda HID trafiği olmaz ve önizleme bir **simülasyondur**. Diğerleri (Gradyan akışı, Renk nabzı, Yumuşak geçiş, Bölge takibi, Sinematik ambiyans)
yazılımda hesaplanıp hız sınırlı gönderilir. Hız, parlaklık, yön ve renkler ayarlanabilir. Işık hassasiyeti için sert yanıp sönme yoktur.

### Profiller
12 hazır profil (Cinematic Ambient, Gaming Dynamic, Deep Blue, MSI Red, Cyberpunk, Ocean, Sunset, Rainbow, Night Mode, Minimal White, Screen Adaptive, Custom Profile).
Yeni (mevcut ayarlardan), uygula, yeniden adlandır, mevcut ayarlarla güncelle, çoğalt, sil, varsayılan yap, içe/dışa aktar (JSON), hazır profilleri geri yükle.

### Donanım Durumu
Cihaz algılandı mı, HID erişimi, bağlantı, aktif mod, istenen ve **yazıldığı doğrulanan** renkler ayrı ayrı, hata sayısı, son başarılı güncelleme,
paket/güncelleme istatistikleri, MSI Center çakışması ve güvenlik özeti. "Yeniden bağlan" ve "Renkleri yeniden gönder" düğmeleri.

### Ayarlar
Dil (Türkçe/English, yeniden başlatınca), tema, Windows başlangıcında çalıştır (HKCU Run), tepside başlat, kapatınca tepsiye küçült,
başlangıç profili, çıkış davranışı (son manuel profili geri yükle / olduğu gibi bırak / kapat), yakalama yöntemi, HDR telafisi,
gerçek donanıma yaz (kapalıysa simülasyon), güncelleme hızı, onay okuması, periyodik yeniden gönderim, otomasyon
(gece modu saat aralığı, tam ekran oyun algılama, uygulamaya göre profil), otomatik kurtarma, ayrıntılı günlük ve günlük görüntüleyici.

## Sistem tepsisi
Sol tık: pencereyi göster/gizle. Sağ tık: Ekran senkronunu başlat/durdur, ışıkları aç/kapat, profiller, çıkış.

## Veri konumları
- Ayarlar ve profiller: `%APPDATA%\Refletseher\` (`settings.json`, `profiles.json`)
- Günlükler: `%LOCALAPPDATA%\Refletseher\logs\refletseher.log` (döner, 3×1 MB)

## Sorun giderme
| Belirti | Çözüm |
|---|---|
| "Cihaz bulunamadı" | Klavye kontrolcüsü Windows'ta görünmüyor olabilir; Aygıt Yöneticisi → HID. Uygulama 30 s'ye kadar artan aralıklarla yeniden dener. |
| "Erişim reddedildi" | Başka bir yazılım cihazı özel modda açmış olabilir. MSI Center'ı kapatıp "Yeniden bağlan". |
| Renkler kendiliğinden değişiyor | MSI Mystic Light yazıyor olabilir; kapatın veya Ayarlar → periyodik yeniden gönderimi açın. |
| Ekran senkronu siyah | DRM korumalı içerik, kilit ekranı veya özel tam ekran. Yakalama yöntemini değiştirmeyi deneyin. |
| Renkler soluk (HDR) | HDR telafisini açık tutun veya doygunluğu artırın. |
