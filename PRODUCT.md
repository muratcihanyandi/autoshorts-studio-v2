# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Tek kullanıcı: stüdyonun sahibi (kendi homelab'ında çalışan içerik üreticisi).
Kullanım şekli **durum takibi ağırlıklı** — kullanıcı arayüze çoğunlukla
"pipeline sağlıklı mı, bugün ne yayınlandı, sıra ne durumda, kaynaklardan
ne geldi" sorularını yanıtlamak için bakar; müdahale istisnadır, kural
değildir. (Kullanıcı cevabıyla doğrulandı; tek kullanıcılık homelab
kurulumundan çıkarım.)

## Product Purpose

AutoShorts Studio: Raspberry Pi 5 üzerinde çalışan, birden çok
YouTube kanalını yöneten otonom klip stüdyosu. Yetkili kaynak kanalları
izler, yatay videoları dikey kliplere dönüştürür, Türkçe altyazıları
düzeltir, metaveri hazırlar, özel (private) video stoğu tutar ve
yapılandırılabilir takvimle yayınlar. Başarı: kullanıcının günlük
müdahalesi olmadan sürekli ve güvenilir üretim; sorun çıktığında
kullanıcının tek ekrandan görüp tek tıkla durdurabilmesi.

## Positioning

Tam otomatik ama tamamen görünür: her adımı (hak kaydı, kota, kaynak
izni, kalite kontrolü) kodda zorunlu kılınan, tek kartlık bir homelab
donanımında (Pi 5, 8GB, CasaOS) yaşayan çok kanallı YouTube üretim
hattı. Yayın davranışı **tam otomatik** (kullanıcı cevabı): sistem
kurallar sağlanınca kendisi yayınlar; onay akışı varsayılan kapı değil,
gerektiğinde açılan bir geçiş/override mekanizmasıdır.

## Operating Context

- Tarayıcıdan LAN erişimi (Raspberry Pi 5 üzerinde Docker/CasaOS).
- Arayüz dili **Türkçe** (proje kuralı; UI metinlerinde Türkçe karakter
  serbest).
- Ağır medya işleri API'den ayrı worker süreçlerinde; arayüz her zaman
  hızlı kalmalı.
- Kaynak medya yalnızca yetkili/izinli kanallardan; hak kaydı olmadan
  yayın yok.

## Capabilities and Constraints

- Uygulama bugün: sağlık uçları, yapılandırılmış loglama, PostgreSQL +
  migration altyapısı. (Doğrulandı, repoda.)
- Yol haritası: kanal yönetimi (OAuth), kaynak izleme, LLM sağlayıcı
  yöneticisi (3 sağlayıcı, sınırlı fallback), kalıcı iş kuyruğu, medya
  pipeline'ı, 9:16 stüdyo + webcam takibi, Türkçe altyazı düzeltme,
  takvimli yayın, uçtan uca otomasyon (docs/ROADMAP.md).
- Donanım sınırı: 8GB RAM diğer CasaOS servisleriyle paylaşılıyor;
  eşzamanlılık sınırlı, FFmpeg kısıtlı, disk doluluk kontrolü zorunlu.
- Gizli bilgi kuralı: API yanıtlarında ve loglarda secret yok.

## Brand Commitments

- Arayüz metinleri Türkçe, teknik terimler (OAuth, LLM) evrensel
  kalabilir.
- Mevcut marka varlığı/logo yok; isim: "AutoShorts Studio".

## Evidence on Hand

- Çalışan dağıtım: Pi üzerinde backend+frontend+PostgreSQL sağlıklı
  (sağlık uçları doğrulandı).
- Gerçek içerik/kanal verisi henüz yok — M2 ekranlarında veri
  katmanları M3+ gelene kadar boş durum (empty state) olarak
  tasarlanır; örnek/uydurma veri "sentetik" etiketiyle gösterilir.

## Product Principles

1. Durum önce: her ekran kullanıcının 5 saniyede "sorun var mı, ne
   oluyor" sorusunu yanıtlamasını sağlar.
2. Otomasyon görünür: sistem kendi kararlarını verir ama her karar
   izlenebilir ve geri alınabilir.
3. Kaynaklar korunur: Pi'nin belleği, diski ve kotaları birinci sınıf
   vatandaş; arayüz kaynak baskısını gösterir.
4. Türkçe ve doğrudan: mikrocopy işlem yapar, süslemez.
5. Boş ekran yol gösterir: henüz var olmayan veri katmanları,
   kullanıcının sıradaki kurulum adımını söyleyen boş durumlarla
   temsil edilir.

## Accessibility & Inclusion

Klavye ile tam gezinme ve görünür odak zorunlu (roadmap M2 kabul
kriteri). Ekran okuyucu için anlamlı başlık hiyerarşisi.
