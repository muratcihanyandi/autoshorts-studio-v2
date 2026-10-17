---
name: Autonomous Creator Studio
description: Raspberry Pi 5 üzerindeki otonom YouTube klip stüdyosunun durum panosu — Yeşilçam baskı odası estetiği
colors:
  ink-ground: "#171b26"
  ink-deep: "#10131c"
  ink-panel: "#1e2330"
  ink-border: "#2c3244"
  plate: "#f2ecdd"
  plate-line: "#c9c1ac"
  plate-ink: "#1c1b17"
  cream-text: "#ede6d3"
  muted-on-dark: "#b9b29e"
  faint-on-dark: "#9a9380"
  plate-muted: "#6e6753"
  plate-body-ink: "#4a4436"
  red: "#c93a2e"
  red-on-plate: "#b02f24"
  amber: "#d9a036"
  amber-on-plate: "#8f5e0f"
  green: "#2e7f6f"
  green-on-plate: "#1f5b4e"
  green-on-dark: "#4fa391"
  cobalt: "#3550c4"
  cobalt-on-dark: "#7d92e8"
  paper-white: "#fffdf6"
typography:
  display:
    fontFamily: "Anton, 'Arial Narrow', sans-serif"
    fontWeight: 400
    fontSize: "clamp(64px, 8vw, 116px)"
    lineHeight: 0.92
  headline:
    fontFamily: "Anton, 'Arial Narrow', sans-serif"
    fontWeight: 400
    fontSize: "24px"
    letterSpacing: "0.03em"
  title:
    fontFamily: "Anton, 'Arial Narrow', sans-serif"
    fontWeight: 400
    fontSize: "20px"
    letterSpacing: "0.03em"
  body:
    fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: "14px"
    lineHeight: 1.5
  label:
    fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontWeight: 600
    fontSize: "11.5px"
    letterSpacing: "0.12em"
rounded:
  print: "0px"
  panel: "4px"
  control: "2px"
spacing:
  space-1: "4px"
  space-2: "8px"
  space-3: "14px"
  space-4: "20px"
  space-5: "28px"
  space-6: "40px"
components:
  plate:
    backgroundColor: "{colors.plate}"
    textColor: "{colors.plate-ink}"
    rounded: "{rounded.print}"
    padding: "28px 28px 20px"
  ink-panel:
    backgroundColor: "{colors.ink-panel}"
    textColor: "{colors.cream-text}"
    rounded: "{rounded.panel}"
    padding: "20px 28px"
  stamp-live:
    typography: "{typography.display}"
    textColor: "{colors.red-on-plate}"
    padding: "8px 12px"
  rail-link-active:
    backgroundColor: "{colors.cobalt}"
    textColor: "{colors.paper-white}"
    padding: "10px 20px"
  plate-action:
    backgroundColor: "{colors.plate-ink}"
    textColor: "{colors.plate}"
    rounded: "{rounded.control}"
    padding: "9px 18px"
  gauge-fill:
    backgroundColor: "{colors.cobalt}"
    height: "10px"
---

# Design System: Autonomous Creator Studio

## Overview

**Creative North Star: "Yeşilçam Baskı Odası"**

Stüdyo panosu, 70'ler İstanbul'u bir film afişi baskı odasıdır: koyu mürekkep
masasının (koyu lacivert-siyah zemin) üstünde günün çıktısı krem afiş
levhaları olarak asılır. Dev sayılar, jenerik bloklar ve durum damgaları bu
levhaya basılır; sistemin durumu poster mürekkepleriyle (kırmızı, hardal,
yeşil, kobalt) yazılır. Koyu paneller baskı odasının mürekkep kutularıdır —
ölçüm ve kaynak göstergeleri orada yaşar.

Yoğunluk ve felsefe durum-izleme ağırlıklıdır: kullanıcı ilk viewport'ta 5
saniyede "sorun var mı, ne oluyor" cevabını alır. Süs yok; tek koreografi
edilmiş hareket damganın basılışıdır, başka hiçbir öğe kendi kendine
kıpırdamaz. Malzeme düz ve gölgesizdir — derinlik ton farkıyla verilir,
levha kâğıdı gibi mürekkep zemininin üstünde fiziksel olarak durur.

Kategori varsayılanı bilinçli reddedilir: nötr gri paneller + tek vurgu
rengi + yumuşak gölgeli kartlar değil; her yüzeyin bir malzemesi ve her
rengin bir işi vardır.

**Key Characteristics:**
- Koyu mürekkep zemini üstünde krem afiş levhaları; durum poster mürekkepleriyle
- Anton afiş display'i yalnız başlıklarda, dev sayılarda ve jenerik etiketlerinde
- Düz yüzeyler, gölge yok, tonal katmanlama
- Tek imza hareketi: damganın basılışı (450 ms)
- Veri sayıları her zaman tabular-nums
- Türkçe mikrocopy; boş veri katmanları yönlendirici empty-state'lerle temsil edilir

## Colors

Palet, tek bir krem afiş levhasının mürekkep zeminine kontrastından ve dört
poster mürekkebinin iş bölümünden oluşur.

### Primary
- **Krem Afiş Levhası** (#f2ecdd): her ekranın ana anlatım yüzeyi. Dev sayı
  (marquee), jenerik blok, durum kutuları ve empty-state'ler bu levhaya
  basılır; mürekkep zemininin üstünde fiziksel bir kâğıt gibi durur.

### Secondary
- **Kızıl Baskı** (#c93a2e; levhada #b02f24): kritik durum ve canlı yayın
  imzası — "ŞİMDİ YAYINDA" damgası, hata kutusu konturu, kırmızı jenerik
  değerleri.
- **Hardal Mürekkebi** (#d9a036; levhada #8f5e0f): uyarı ve kurulum aşaması —
  bekleyen uyarılar, sıcaklık/disk baskısı, bayat veri notu.
- **Çam Yeşili** (#2e7f6f; levhada #1f5b4e, koyuda #4fa391): sağlıklı durum —
  veritabanı bağlı, kaynaklar normal.
- **Kobalt** (#3550c4; koyuda #7d92e8): seçim ve etkileşim — aktif nav bloğu,
  odak halkası, metin seçimi, normal gösterge dolgusu.

### Neutral
- **Mürekkep Zemini** (#171b26): sayfanın masa yüzeyi; body arka planı.
- **Derin Mürekkep** (#10131c): sol nav rayı ve gösterge olukları.
- **Panel Mürekkebi** (#1e2330): koyu panellerin yüzeyi.
- **Mürekkep Kenarı** (#2c3244): 1px panel/kenar çizgileri, kaydırma çubuğu.
- **Krem Metin** (#ede6d3): koyu zeminde ana metin.
- **Soluk Krem** (#b9b29e) / **Soluk Mürekkep Sarısı** (#9a9380): koyu zeminde
  ikincil/üçüncül metin; soluk ton panel mürekkebi üstünde de 4.5:1'i geçer.
- **Levha Mürekkebi** (#1c1b17): levha üstü metin ve koyu levha butonları.
- **Levha Soluk Mürekkebi** (#6e6753): levha üstü panel başlıkları ve bekleme
  damgasının mürekkebi (krem üstünde 4.78:1).
- **Levha Gövde Mürekkebi** (#4a4436): levha üstü açıklama metni (8.2:1).
- **Levha Çizgisi** (#c9c1ac): levha üstü ince ayraç çizgileri.
- **Kâğıt Beyazı** (#fffdf6): kobalt üstü metin (aktif nav, seçim).

### Named Rules
**Mürekkep İş Görür Kuralı.** Poster mürekkepleri yalnız durum işi yapar:
kırmızı = kritik/canlı, hardal = uyarı/kurulum, yeşil = sağlıklı, kobalt =
seçim/etkileşim. Hiçbiri dekoratif vurgu olarak kullanılmaz; vurgu levhanın
kendisidir.

**Zemin Lehçesi Kuralı.** Her mürekkep, üstünde durduğu zeminin varyantını
kullanır: krem levhada `-on-plate` tonu, mürekkep zemininde `-on-dark` tonu.
Ham hardal (#d9a036) krem levha üstünde metin olarak yasak (kontrast
yetersiz); levhada daima #8f5e0f. Metin kontrastı her eşleşmede en az 4.5:1.

## Typography

**Display Font:** Anton ('Arial Narrow' düşüşüyle; latin + latin-ext
kendi sunucundan, @fontsource/anton)
**Body Font:** system-ui yığını (-apple-system, 'Segoe UI', Roboto, sans-serif)

**Character:** Anton afiş sıkılığı — sıkışık, geniş, tek ağırlıklı (400);
başlıkları poster harfi gibi basar. Gövde nötr sistem sans'ıdır; afiş harfi
okuma metnine asla inmez.

### Hierarchy
- **Display** (Anton 400, clamp(64px, 8vw, 116px), 0.92 satır): marquee dev
  sayısı. 1440px'te 115.2px, 390px'te 64px'e ölçüldü.
- **Headline** (Anton 400, 24px, 0.03em; ≤900px'te 20px): ekran başlıkları
  (h1) ve marka bloğu (17px).
- **Title** (Anton 400, 20px, 0.03em): durum kutusu başlıkları; jenerik
  satırı etiketleri 15px/0.05em; damga 15px/0.08em.
- **Body** (system 400, 14px, 1.5): tüm okuma metni; empty-state açıklamaları
  13.5px, en fazla ~52ch satır.
- **Label** (system 600, 11.5px, 0.12em, uppercase): panel başlıkları, tablo
  başlıkları, gösterge etiketleri üstü.

### Named Rules
**Rakam Düz Durur Kuralı.** Veri sayıları her zaman tabular-nums
(`font-variant-numeric: tabular-nums`); akan rakam yok.

**Afiş Başlıkta Kalır Kuralı.** Anton yalnız başlıkta, dev sayıda ve kısa
etiketlerde; paragraf metninde asla.

## Layout

Sol tarafta 208px sabit nav rayı (marka bloğu + 8 hedef + alt bilgi),
sağında içerik alanı (dolgular 28px üst/alt, 40px yan). İlk viewport
formülü: solda krem marquee levhası (dev sayı + sağ üstte damga + jenerik
blok), sağda iki koyu panel (Pi kaynak göstergeleri, kanal kurdeleleri) —
two-col grid 1.35fr/1fr.

Kırılımlar: ≤1100px'te iki kolon tek kolona döner; ≤900px'te ray üst yatay
çubuğa döner (nav overflow-x: auto kaydırmalı şerit, halkalar 1px konturlu,
ray alt bilgisi gizli), içerik dolgusu 20px'e iner, h1 20px.

Boşluk ölçeği: 4 / 8 / 14 / 20 / 28 / 40px. Yoğunluk durum-izleme
yoğunluğudur: büyük sayılar, sıkı satırlar, bolca hava yok — baskı
formundadır.

## Elevation & Depth

Gölge yok — sistem tamamen düz ve gölgesizdir (hiçbir kuralda box-shadow
yoktur). Derinlik tonal katmanlamayla verilir: mürekkep zeminini (#171b26)
panel mürekkebi (#1e2330) ve derin mürekkep (#10131c) katmanları keser;
krem levha, ton farkının tamamını taşıyan fiziksel kâğıt gibi üstünde
durur. Kenarlar 1px mürekkep kenarı çizgisiyle (#2c3244) çizilir.

### Named Rules
**Gölge Yok Kuralı.** Hiçbir yüzeye box-shadow eklenmez; kalkma hissi
verilecekse ton katmanı veya çizgi kullanılır.

## Shapes

Köşe stratejisi malzemeye bağlıdır: krem afiş levhası keskin baskı köşesi
taşır (0px radius — kâğıt makasla kesilmiş), koyu paneller hafif yumuşar
(4px), küçük kontroller 2px. İmza formu damgadır: 3px konturlu, -4°
döndürülmüş dikdörtgen, kendi renginde. Jenerik blok = 2px kalın üst çizgi +
1px ince alt çizgilerle ayrılan satırlar (baskı jeneriği). Kesikli kontur
sözleşmesi: kesikli çizgi "bekleyen / henüz yok" demektir (bekleyen damga,
empty-state kutusu); düz kesikli çizgiden kalın kontura geçiş durumun
sertleşmesidir (hata).

## Components

### Signature: Marquee + Damga
Stüdyonun kimlik bileşeni. Krem levhada dev Anton sayı (clamp 64–116px)
+ yanında afiş etiketi + sağ üstte hafif eğik damga (3px kontur,
rotate(-4°), 15px Anton). Damga varyantları: `--live` kızıl (ŞİMDİ YAYINDA),
`--setup` hardal (KURULUM), `--wait` kesikli kontur levha soluk mürekkebi
(KANAL BEKLENİYOR). Tek hareket: `stamp-press` — 450ms cubic-bezier(0.19, 1,
0.22, 1), -14°'den 1.6x ölçekle iner; faz değiştiğinde damga yeniden
basılır (bileşen fazla anahtarlanır), prefers-reduced-motion'da kapalı.
Müdahale damgası (design-annual yükseltmesi): kullanıcı hattı durdurunca
onun damgası panoda kalır — Otomasyon empty state'inde kırmızı "DURAKLATILDI"
önizlemesi olarak tasarımı taşınır, "yakında" etiketiyle.

### Jenerik Blok (bill-row)
Levhadaki veri satırı: sol tarafta Anton 15px/0.05em büyük-harf etiket,
sağda system 600 13px değer; satırlar 1px levha çizgisiyle ayrılır, blok
2px levha mürekkebi üst çizgisi taşır. Ton sınıfları değeri boyar:
`tone-red` / `tone-amber` / `tone-green` (on-plate varyantlarıyla).

### Mürekkep Göstergesi (gauge)
Koyu panelde 10px dolgu çubuğu: normal kobalt, `warn` hardal, `ok` yeşil;
oluk derin mürekkep. Üstünde 12.5px etiket + yüzde değeri; role="meter".

### Levha (plate) ve Mürekkep Paneli (ink-panel)
Levha: krem yüzey, keskin köşe (0px), 28px/28px/20px dolgu — anlatım yüzeyi.
Panel: #1e2330 yüzey, 1px kenar, 4px köşe, 20px/28px dolgu — ölçüm yüzeyi.
Panel başlığı her ikisinde de 11.5px uppercase label.

### Durum Kutusu (state-box)
Boş katmanların temsili: kesikli levha çizgisi konturlu krem kutu (keskin
köşe), ortada Anton 20px başlık + 13.5px açıklama (≤52ch, levha gövde
mürekkebi) + koyu levha-butonu (#1c1b17 zemin, krem metin, 2px köşe,
9px/18px). Hata varyantı düz kızıl kontur + kızıl başlık. Empty-state metni
kullanıcının sıradaki kurulum adımını söyler.

### Yükleme ve Bayat Veri
Yükleme: `ink-loading` — koyu panelde 42px'ten 120px'e genişleyen kobalt
çubuk (1.1s). Bağlantı koptuğunda: `stale-note` — hardal konturlu, hardal
metinli ince şerit + tekrar dene butonu; eski veri ekranda kalır, gizlenmez.

### Navigation (ray)
Sol ray: 11.5–13.5px system linkler, soluk krem; hover krem metin; aktif
hedef kobalt blok + kâğıt beyazı metin. Mobil: yatay kaydırmalı şerit,
halkalar 1px konturlu, aktif kobalt kontur. Odak her yerde 2px
cobalt-on-dark halkası (outline-offset 2px). Skip-link kobalt blok.

## Do's and Don'ts

### Do:
- **Do** durum renklerini iş için kullan: kırmızı kritik/canlı, hardal
  uyarı, yeşil sağlıklı, kobalt seçim — başka hiçbir amaç için değil.
- **Do** veri sayılarını tabular-nums ile yaz; değerleri jenerik satırının
  sağında sağa hizala.
- **Do** boş veri katmanlarını yönlendirici empty-state'lerle göster;
  sentetik/örnek veri ancak "sentetik" etiketiyle görünür.
- **Do** Türkçe mikrocopy kullan; Türkçe karakterler UI'da serbesttir
  (Anton latin-ext ile yüklenir).
- **Do** klavye erişimini koru: görünür focus-visible halkası, skip-link,
  role="meter"/role="alert" anlambilimi.
- **Do** hareketi kullanıcı eylemine bağla; tek istisna damganın ilk
  basılışıdır ve prefers-reduced-motion'da kapalıdır.

### Don't:
- **Don't** gradient metin, gölge (box-shadow) veya 1px'den kalın
  border-left vurgu şeridi kullanma.
- **Don't** kicker/eyebrow etiketi uydurma; panel başlığı label'ı yeter.
- **Don't** Anton'u gövde metninde veya uzun paragraflarda kullanma.
- **Don't** ham hardalı (#d9a036) krem levha üstünde metin rengi yapma —
  levhada #8f5e0f kullan.
- **Don't** nötr gri panel + tek vurgu rengi kategori varsayılanına dön;
  her yeni yüzey bu dünyanın malzemesinden (levha, mürekkep paneli) olur.
- **Don't** API'de olmayan veriyi uydurma; sıfır da gerçektir ve öyle
  gösterilir.
