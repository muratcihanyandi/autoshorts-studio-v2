---
name: AutoShorts Studio
description: Raspberry Pi 5 üzerindeki otonom YouTube klip stüdyosunun durum panosu — AutoShorts Studio kurumsal marka kiti, Modern Sinematik & Prestij
colors:
  ink-ground: "#0b192c"
  ink-deep: "#081322"
  ink-panel: "#12233c"
  ink-border: "#24354f"
  plate: "#f0f4f8"
  plate-line: "#c7d2de"
  plate-ink: "#0b192c"
  cream-text: "#f0f4f8"
  muted-on-dark: "#94a3b8"
  faint-on-dark: "#7c8ba1"
  plate-muted: "#64748b"
  plate-body-ink: "#334155"
  accent: "#15f5ba"
  accent-ink: "#0b192c"
  accent-deep: "#0a8f6d"
  accent-soft: "#a7f5dd"
  red: "#d64545"
  red-on-plate: "#b91c1c"
  amber: "#e8a33d"
  amber-on-plate: "#92610a"
  amber-on-dark: "#e8a33d"
  green: "#0e9f6e"
  green-on-plate: "#047857"
  green-on-dark: "#34d399"
  paper-white: "#ffffff"
typography:
  display:
    fontFamily: "'Noto Sans Display', 'Segoe UI', sans-serif"
    fontWeight: 800
    fontSize: "clamp(64px, 8vw, 116px)"
    lineHeight: 0.92
  headline:
    fontFamily: "'Noto Sans Display', 'Segoe UI', sans-serif"
    fontWeight: 800
    fontSize: "24px"
    letterSpacing: "0.03em"
  title:
    fontFamily: "'Noto Sans Display', 'Segoe UI', sans-serif"
    fontWeight: 700
    fontSize: "20px"
    letterSpacing: "0.03em"
  body:
    fontFamily: "'Google Sans', 'Noto Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: "14px"
    lineHeight: 1.5
  label:
    fontFamily: "'Google Sans', 'Noto Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontWeight: 600
    fontSize: "11.5px"
    letterSpacing: "0.12em"
rounded:
  print: "12px"
  panel: "8px"
  control: "6px"
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
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    padding: "10px 20px"
  plate-action:
    backgroundColor: "{colors.plate-ink}"
    textColor: "{colors.plate}"
    rounded: "{rounded.control}"
    padding: "9px 18px"
  gauge-fill:
    backgroundColor: "{colors.accent}"
    height: "10px"
---

# Design System: AutoShorts Studio

## Overview

**Creative North Star: "Modern Sinematik & Prestij" — AutoShorts Studio marka kiti**

Stüdyo panosu, marka kitinin kurumsal dünyasıdır: Zengin Geceyarısı Mavisi
masasının üstünde günün çıktısı Fildişi Beyazı levhalar olarak sunulur.
Canlı Okyanus Yeşili tek vurgudur — eylem, seçim ve canlılığın rengi; rozet
filmi andıran sinematik imzadır. Kullanım dengesi marka rehberinden gelir:
%60 açık zemin (levhalar), %30 koyu zemin (kabuk ve paneller), %10 vurgu.

Yoğunluk ve felsefe durum-izleme ağırlıklıdır: kullanıcı ilk viewport'ta 5
saniyede "sorun var mı, ne oluyor" cevabını alır. Süs yok; tek koreografi
edilmiş hareket damganın basılışıdır, başka hiçbir öğe kendi kendine
kıpırdamaz. Malzeme düz ve gölgesizdir — derinlik ton farkıyla verilir,
levha fildişi kâğıdı gibi geceyarısı zemininin üstünde fiziksel olarak
durur.

**Key Characteristics:**
- Geceyarısı mavisi zemin üstünde fildişi levhalar; Okyanus Yeşili tek vurgu
- Noto Sans Display ExtraBold yalnız başlıklarda, dev sayılarda ve etiketlerde
- Google Sans + Noto Sans gövde ikilisi; tam Türkçe glif desteği self-hosted
- Düz yüzeyler, gölge yok, tonal katmanlama
- Tek imza hareketi: damganın basılışı (450 ms)
- Veri sayıları her zaman tabular-nums
- Marka logosu (koyu zemin varyantı) sol rayda; ikon favicon'da
- Türkçe mikrocopy; boş veri katmanları yönlendirici empty-state'lerle temsil edilir

## Colors

Palet, AutoShorts Studio kurumsal renk paletidir (marka kiti
`2_Renk_Paleti/Renk_Paleti_ve_Kodlar.txt`, 2026-10-17).

### Primary
- **Fildişi Beyazı** (#f0f4f8): her ekranın ana anlatım yüzeyi — `plate`
  token'ı. Dev sayı (marquee), jenerik blok, durum kutuları ve
  empty-state'ler bu levhaya basılır; %60 kullanım oranı.

### Accent
- **Canlı Okyanus Yeşili** (#15f5ba): eylem ve seçim — CTA, aktif nav bloğu,
  odak halkası, metin seçimi, normal gösterge dolgusu, logo film şeridi
  rozeti; %10 kullanım oranı.

### Secondary (durum renkleri — işlevsel, marka nötr temelli)
- **Kızıl** (#d64545; levhada #b91c1c): kritik durum ve canlı yayın imzası —
  "ŞİMDİ YAYINDA" damgası, hata kutusu konturu.
- **Hardal** (#e8a33d; levhada #92610a): uyarı ve kurulum aşaması — bekleyen
  uyarılar, sıcaklık/disk baskısı, bayat veri notu.
- **Yeşim** (#0e9f6e; levhada #047857, koyuda #34d399): sağlıklı durum —
  veritabanı bağlı, kaynaklar normal. Vurgudan ayrışır: okyanus yeşilinin
  saturation-parlaması taşıyıcı yüzeyde, yeşimin tonu durum bildirimdedir.

### Neutral
- **Zengin Geceyarısı Mavisi** (#0b192c): sayfanın zemini (`ink-ground`),
  ana koyu mürekkep ve levha üstü metin (`plate-ink`); %30 kullanım oranı.
- **Derin Geceyarısı** (#081322): sol nav rayı ve gösterge olukları (`ink-deep`).
- **Panel Mavisi** (#12233c): koyu panellerin yüzeyi (`ink-panel`).
- **Mavi Kenar** (#24354f): 1px panel/kenar çizgileri, kaydırma çubuğu (`ink-border`).
- **Fildişi Metin** (#f0f4f8): koyu zeminde ana metin (`cream-text`) — marka
  rehberi koyu zemindeki logo/metin rengi olarak tanımlar.
- **Arduvaz Grisi** (#64748b): levha üstü alt metin ve ikincil öğeler
  (`plate-muted`) — markanın nötr rengi; koyu zemin açık varyantları
  #94a3b8 (`muted-on-dark`) / #7c8ba1 (`faint-on-dark`).
- **Gövde Mürekkebi** (#334155): levha üstü açıklama metni (`plate-body-ink`).
- **Levha Çizgisi** (#c7d2de): levha üstü ince ayraç çizgileri (`plate-line`).
- **Beyaz** (#ffffff): input zeminleri (`paper-white`).

### Named Rules
**Vurgu İş Görür Kuralı.** Okyanus Yeşili yalnız eylem ve seçim işi yapar:
CTA, aktif nav, odak, seçim, canlı gösterge. Hiçbir yerde dekoratif dolgu
olarak kullanılmaz; vurgu levhanın kendisidir.

**Vurgu Üstü Koyu Metin Kuralı.** Okyanus Yeşili üstünde metin daima
Zengin Geceyarısı Mavisi'dir (#0b192c), asla beyaz değil — marka rehberi
kuralı. Metin kontrastı her eşleşmede en az 4.5:1.

**Zemin Lehçesi Kuralı.** Durum renkleri, üstünde durduğu zeminin varyantını
kullanır: fildişi levhada `-on-plate` tonu, koyu zeminde `-on-dark` tonu.
Ham hardal (#e8a33d) fildişi levha üstünde metin olarak yasak (kontrast
yetersiz); levhada daima #92610a.

## Typography

**Display Font:** Noto Sans Display (ExtraBold 800 + Bold 700; self-hosted
TTF, marka kitinden — başlık ve logo fontu)
**Body Font:** Google Sans (Regular) + Noto Sans (Regular/SemiBold) yığını
(self-hosted TTF; latin-ext dahil tam Türkçe glif desteği fontTools cmap
kontrolüyle doğrulandı)

**Character:** Noto Sans Display ExtraBold prestij sıkılığı — modern,
geniş, güven veren başlık harfi. Gövde Google Sans arayüz metnidir;
Türkçe karakterler her iki ailede de birinci sınıftır.

### Hierarchy
- **Display** (Noto Sans Display 800, clamp(64px, 8vw, 116px), 0.92 satır):
  marquee dev sayısı. 1440px'te 115.2px, 390px'te 64px'e ölçüldü.
- **Headline** (Noto Sans Display 800, 24px, 0.03em; ≤900px'te 20px): ekran
  başlıkları (h1).
- **Title** (Noto Sans Display 700, 20px, 0.03em): durum kutusu başlıkları;
  jenerik satırı etiketleri 15px/0.05em; damga 15px/0.08em.
- **Body** (Google Sans/Noto Sans 400, 14px, 1.5): tüm okuma metni;
  empty-state açıklamaları 13.5px, en fazla ~52ch satır.
- **Label** (600, 11.5px, 0.12em, uppercase): panel başlıkları, tablo
  başlıkları, gösterge etiketleri üstü.

### Named Rules
**Rakam Düz Durur Kuralı.** Veri sayıları her zaman tabular-nums
(`font-variant-numeric: tabular-nums`); akan rakam yok.

**Display Başlıkta Kalır Kuralı.** Noto Sans Display yalnız başlıkta, dev
sayıda ve kısa etiketlerde; paragraf metninde asla.

## Layout

Sol tarafta 208px sabit nav rayı (marka logosu + 8 hedef + alt bilgi),
sağında içerik alanı (dolgular 28px üst/alt, 40px yan). İlk viewport
formülü: solda fildişi marquee levhası (dev sayı + sağ üstte damga +
jenerik blok), sağda iki koyu panel (Pi kaynak göstergeleri, kanal
kurdeleleri) — two-col grid 1.35fr/1fr.

Kırılımlar: ≤1100px'te iki kolon tek kolona döner; ≤900px'te ray üst yatay
çubuğa döner (nav overflow-x: auto kaydırmalı şerit, halkalar 1px konturlu,
ray alt bilgisi gizli), içerik dolgusu 20px'e iner, h1 20px.

Boşluk ölçeği: 4 / 8 / 14 / 20 / 28 / 40px. Yoğunluk durum-izleme
yoğunluğudur: büyük sayılar, sıkı satırlar, bolca hava yok.

## Elevation & Depth

Gölge yok — sistem tamamen düz ve gölgesizdir (hiçbir kuralda box-shadow
yoktur). Derinlik tonal katmanlamayla verilir: geceyarısı zeminini (#0b192c)
panel mavisi (#12233c) ve derin geceyarısı (#081322) katmanları keser; fildişi
levha, ton farkının tamamını taşıyan fiziksel kâğıt gibi üstünde durur.
Kenarlar 1px mavi kenar çizgisiyle (#24354f) çizilir.

### Named Rules
**Gölge Yok Kuralı.** Hiçbir yüzeye box-shadow eklenmez; kalkma hissi
verilecekse ton katmanı veya çizgi kullanılır.

## Shapes

Köşe stratejisi modern sinematik prestijdendir: fildişi levha geniş yumuşak
köşe taşır (12px), koyu paneller orta (8px), küçük kontroller dar (6px).
İmza formu damgadır: 3px konturlu, -4° döndürülmüş dikdörtgen, kendi
renginde. Jenerik blok = 2px kalın üst çizgi + 1px ince alt çizgilerle
ayrılan satırlar. Kesikli kontur sözleşmesi: kesikli çizgi "bekleyen /
henüz yok" demektir (bekleyen damga, empty-state kutusu); düz kesikli
çizgiden kalın kontura geçiş durumun sertleşmesidir (hata).

## Brand Assets

- **Logo:** tam logo (amblem + "AutoShorts STUDIO" yazısı) sol rayın marka
  bloğunda, koyu zemin varyantı (`logo-dark-bg.svg`, 1600×500 viewBox,
  148px render genişliği). Açık zemin varyantı (`logo-light-bg.svg`) el altında.
- **İkon:** 512×512 amblem; tarayıcı favicon'u olarak aydınlık zemin
  varyyantı (`icon-light-bg.svg` → `/favicon.svg`).
- **Amblem anatomisi:** 'A' harfi + sinematik film şeridi rozeti; rozet
  okyanus yeşili, gövde zemine göre fildişi ya da geceyarısı mavisi.
- **Fontlar:** marka kitinden beş TTF self-hosted (`src/assets/fonts/`);
  CDN'e bağımlılık yok, Pi offline ortamında da tutarlı.

## Components

### Signature: Marquee + Damga
Stüdyonun kimlik bileşeni. Fildişi levhada dev Noto Sans Display 800 sayı
(clamp 64–116px) + yanında etiket + sağ üstte hafif eğik damga (3px kontur,
rotate(-4°), 15px Display). Damga varyantları: `--live` kızıl (ŞİMDİ
YAYINDA), `--setup` hardal (KURULUM), `--wait` kesikli kontur arduvaz
(KANAL BEKLENİYOR). Tek hareket: `stamp-press` — 450ms
cubic-bezier(0.19, 1, 0.22, 1), -14°'den 1.6x ölçekle iner; faz değiştiğinde
damga yeniden basılır (bileşen fazla anahtarlanır), prefers-reduced-motion'da
kapalı. Müdahale damgası: kullanıcı hattı durdurunca onun damgası panoda
kalır — Otomasyon empty state'inde kırmızı "DURAKLATILDI" önizlemesi.

### Jenerik Blok (bill-row)
Levhadaki veri satırı: sol tarafta Display 700 15px/0.05em büyük-harf
etiket, sağda gövde 600 13px değer; satırlar 1px levha çizgisiyle ayrılır,
blok 2px levha mürekkebi üst çizgisi taşır. Ton sınıfları değeri boyar:
`tone-red` / `tone-amber` / `tone-green` (on-plate varyantlarıyla).

### Gösterge (gauge)
Koyu panelde 10px dolgu çubuğu: normal okyanus yeşili, `warn` hardal, `ok`
yeşim; oluk derin geceyarısı. Üstünde 12.5px etiket + yüzde değeri;
role="meter".

### Levha (plate) ve Panel (ink-panel)
Levha: fildişi yüzey, 12px köşe, 28px/28px/20px dolgu — anlatım yüzeyi.
Panel: #12233c yüzey, 1px kenar, 8px köşe, 20px/28px dolgu — ölçüm yüzeyi.
Panel başlığı her ikisinde de 11.5px uppercase label.

### Durum Kutusu (state-box)
Boş katmanların temsili: kesikli levha çizgisi konturlu fildişi kutu (12px
köşe), ortada Display 700 20px başlık + 13.5px açıklama (≤52ch, gövde
mürekkebi) + koyu levha-butonu (#0b192c zemin, fildişi metin, 6px köşe,
9px/18px). Hata varyantı düz kızıl kontur + kızıl başlık. Empty-state metni
kullanıcının sıradaki kurulum adımını söyler.

### Yükleme ve Bayat Veri
Yükleme: `ink-loading` — koyu panelde 42px'ten 120px'e genişleyen okyanus
yeşili çubuk (1.1s). Bağlantı koptuğunda: `stale-note` — hardal konturlu,
hardal metinli ince şerit + tekrar dene butonu; eski veri ekranda kalır,
gizlenmez.

### Navigation (ray)
Sol ray: 11.5–13.5px gövde linkleri, arduvaz açık; hover fildişi metin;
aktif hedef okyanus yeşili blok + geceyarısı mavisi metin (vurgu üstü koyu
metin kuralı). Mobil: yatay kaydırmalı şerit, halkalar 1px konturlu, aktif
vurgu konturu. Odak her yerde 2px okyanus yeşili halkası (outline-offset
2px). Skip-link vurgu blok + koyu metin.

## Do's and Don'ts

### Do:
- **Do** okyanus yeşilini eylem/seçim için kullan: CTA, aktif nav, odak,
  seçim, canlı gösterge — başka hiçbir amaç için değil.
- **Do** vurgu üstünde daima geceyarısı mavisi metin kullan; asla beyaz değil.
- **Do** veri sayılarını tabular-nums ile yaz; değerleri jenerik satırının
  sağında sağa hizala.
- **Do** boş veri katmanlarını yönlendirici empty-state'lerle göster;
  sentetik/örnek veri ancak "sentetik" etiketiyle görünür.
- **Do** Türkçe mikrocopy kullan; Türkçe karakterler UI'da serbesttir (tüm
  marka fontlarında tam glif desteği doğrulandı).
- **Do** klavye erişimini koru: görünür focus-visible halkası, skip-link,
  role="meter"/role="alert" anlambilimi.
- **Do** hareketi kullanıcı eylemine bağla; tek istisna damganın ilk
  basılışıdır ve prefers-reduced-motion'da kapalıdır.

### Don't:
- **Don't** gradient metin, gölge (box-shadow) veya 1px'den kalın
  border-left vurgu şeridi kullanma.
- **Don't** kicker/eyebrow etiketi uydurma; panel başlığı label'ı yeter.
- **Don't** Noto Sans Display'i gövde metninde veya uzun paragraflarda
  kullanma.
- **Don't** ham hardalı (#e8a33d) fildişi levha üstünde metin rengi yapma —
  levhada #92610a kullan.
- **Don't** marka dışı renk veya harici font CDN'i katma; yeni yüzey bu
  dünyanın malzemesinden (levha, panel, vurgu) olur.
- **Don't** API'de olmayan veriyi uydurma; sıfır da gerçektir ve öyle
  gösterilir.
