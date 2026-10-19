---
name: AutoShorts Studio
description: Raspberry Pi 5 üzerindeki otonom YouTube klip stüdyosunun durum panosu — "Kategori Standardı" izleme panosu yapısı + AutoShorts Studio marka kimliği
colors:
  page-bg: "#f0f4f8"
  ink-ground: "#0b192c"
  ink-deep: "#081322"
  ink-panel: "#12233c"
  ink-border: "#24354f"
  plate: "#ffffff"
  plate-line: "#dfe5ec"
  plate-ink: "#0b192c"
  cream-text: "#f0f4f8"
  muted-on-dark: "#94a3b8"
  faint-on-dark: "#7c8ba1"
  plate-muted: "#64748b"
  plate-body-ink: "#334155"
  accent: "#15f5ba"
  accent-ink: "#0b192c"
  accent-deep: "#0a8f6d"
  accent-soft: "#cff9ec"
  red: "#d64545"
  red-on-plate: "#b91c1c"
  red-soft: "#fde3e3"
  amber: "#e8a33d"
  amber-on-plate: "#92610a"
  amber-soft: "#fdf0d7"
  green: "#0e9f6e"
  green-on-plate: "#047857"
  green-soft: "#d6f5e8"
  paper-white: "#ffffff"
typography:
  screen-title:
    fontFamily: "'Noto Sans Display', 'Segoe UI', sans-serif"
    fontWeight: 700
    fontSize: "21px"
    letterSpacing: "0.01em"
  stat-value:
    fontFamily: "'Noto Sans Display', 'Segoe UI', sans-serif"
    fontWeight: 700
    fontSize: "26px"
    lineHeight: 1.2
  panel-title:
    fontFamily: "'Google Sans', 'Noto Sans', system-ui, sans-serif"
    fontWeight: 600
    fontSize: "13px"
  body:
    fontFamily: "'Google Sans', 'Noto Sans', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    fontSize: "14px"
    lineHeight: 1.5
  label:
    fontFamily: "'Google Sans', 'Noto Sans', system-ui, sans-serif"
    fontWeight: 500
    fontSize: "12px"
rounded:
  print: "10px"
  panel: "10px"
  control: "8px"
spacing:
  space-1: "4px"
  space-2: "8px"
  space-3: "14px"
  space-4: "20px"
  space-5: "28px"
  space-6: "40px"
shadow:
  card: "0 1px 3px rgba(11, 25, 44, 0.08)"
components:
  stat-card:
    backgroundColor: "{colors.plate}"
    borderColor: "{colors.plate-line}"
    rounded: "{rounded.print}"
    shadow: "{shadow.card}"
    padding: "16px 18px"
  panel:
    backgroundColor: "{colors.plate}"
    borderColor: "{colors.plate-line}"
    rounded: "{rounded.panel}"
    shadow: "{shadow.card}"
  rail-link-active:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
  btn:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.control}"
    padding: "9px 18px"
  pill:
    padding: "4px 12px"
    borderRadius: "99px"
  gauge-fill:
    backgroundColor: "{colors.accent}"
    height: "6px"
---

# Design System: AutoShorts Studio

## Overview

**Creative North Star: "Kategori Standardı" izleme panosu yapısı + AutoShorts
Studio marka kimliği** (2026-10-17 yön değişimi)

Stüdyo panosu, tema kataloğundan seçilen "Kategori Standardı" dilinin
yapısını taşır: açık zemin üstünde beyaz kartlar, dörtlü stat kartı grid'i,
başlık şeritli tablo panelleri, yumuşak zeminli durum hapları ve ince
yuvarlak meter'lar. Bu nötr izleme panosu iskeleti, AutoShorts Studio marka
kitinin kimliğiyle giydirilir: sayfa zemini Fildişi Beyazı (#f0f4f8), sol
nav rayı Zengin Geceyarısı Mavisi'nde (marka logosu burada yaşar), tek vurgu
Canlı Okyanus Yeşili. Kullanım dengesi 60/30/10'dur: fildişi zemin + beyaz
kartlar, geceyarısı nav, okyanus vurgu.

Yoğunluk ve felsefe durum-izlemeye odaklıdır: kullanıcı ilk viewport'ta 5
saniyede "sorun var mı, ne oluyor" cevabını alır — üstte durum hapı, altında
dört stat kartı, altında kanallar ve boru hattı tabloları. Süs yok; hiçbir
öğe kendi kendine kıpırdamaz. Yeşilçam afiş anlatısının imza bileşenleri
(marquee dev sayısı, damga, jenerik blok) bu dilden çıktı; yerini stat
kartları, başlık şeritli paneller ve haplar aldı.

**Key Characteristics:**
- Fildişi sayfa zemini üstünde beyaz kart/panel: 1px çizgi + 10px köşe +
  ölçülü gölge (0 1px 3px rgba(11,25,44,.08))
- Sol 216px geceyarısı nav: marka logosu + nokta göstergeli linkler;
  aktif hedef okyanus yeşili blok + sağda 3px şerit
- Noto Sans Display yalnız ekran başlığında (21px, cümle case) ve stat
  değerinde (26px); gövde Google Sans + Noto Sans, self-hosted
- Durumlar yumuşak zeminli haplarla: ok/yeşil, warn/hardal, run/okyanus,
  idle/arduvaz, error/kızıl — koyu metinle
- Meter'lar 6px yuvarlak dolgu çubukları (oluk #e2e8f0)
- Veri sayıları her zaman tabular-nums
- Türkçe mikrocopy; boş veri katmanları yönlendirici empty-state'lerle

## Colors

Palet, AutoShorts Studio kurumsal renk paletidir (marka kiti
`2_Renk_Paleti/Renk_Paleti_ve_Kodlar.txt`); zemin/kart rolleri "Kategori
Standardı" yapısına göre yeniden atanmıştır.

### Primary
- **Fildişi Beyazı** (#f0f4f8): sayfa zemini (`page-bg`) — sahne, kartların
  altındaki açık zemin.
- **Beyaz** (#ffffff): kart ve panel yüzeyi (`plate`), input zeminleri —
  fildişi zemin üstünde ton farkıyla kalkar.

### Accent
- **Canlı Okyanus Yeşili** (#15f5ba): eylem ve seçim — CTA butonu, aktif nav
  bloğu, odak halkası, normal meter dolgusu; %10 kullanım oranı.

### Secondary (durum renkleri — yumuşak zemin + koyu metin hapları)
- **Yeşim** (zemin #d6f5e8 `green-soft`, metin #047857 `green-on-plate`):
  sağlıklı durum — `pill--ok`.
- **Hardal** (zemin #fdf0d7 `amber-soft`, metin #92610a `amber-on-plate`):
  uyarı ve kurulum aşaması — `pill--warn`, `stat-card.warn` değeri.
- **Okyanus yumuşak** (zemin #cff9ec `accent-soft`, metin #0a8f6d
  `accent-deep`): sürüyor/bilgi durumu — `pill--run`.
- **Kızıl** (zemin #fde3e3 `red-soft`, metin #b91c1c `red-on-plate`): kritik
  durum ve hata — `pill--error`, hata kutusu konturu.

### Neutral
- **Zengin Geceyarısı Mavisi** (#0b192c): sol nav rayının rengi, kart üstü
  ana metin (`plate-ink`) ve vurgu üstü metin (`accent-ink`).
- **Derin Geceyarısı** (#081322): nav'ın en koyu katmanı (`ink-deep`).
- **Panel Mavisi** (#12233c): koyu iç yüzeyler (`ink-panel`).
- **Mavi Kenar** (#24354f): koyu zemin çizgileri (`ink-border`).
- **Arduvaz Grisi** (#64748b): kart üstü alt metin, tablo başlıkları, boş
  durum hapı metni (`plate-muted`); koyu zemin açık varyantları #94a3b8 /
  #7c8ba1.
- **Gövde Mürekkebi** (#334155): kart üstü açıklama metni
  (`plate-body-ink`).
- **Kart Çizgisi** (#dfe5ec): beyaz kartın 1px konturu (`plate-line`);
  tablo satır ayraçları #eef2f6, meter oluğu #e2e8f0.

### Named Rules
**Vurgu İş Görür Kuralı.** Okyanus Yeşili yalnız eylem ve seçim işi yapar:
CTA, aktif nav, odak, seçim, normal meter dolgusu. Dekoratif dolgu olarak
kullanılmaz.

**Vurgu Üstü Koyu Metin Kuralı.** Okyanus Yeşili üstünde metin daima
Zengin Geceyarısı Mavisi'dir (#0b192c), asla beyaz değil — marka rehberi
kuralı. Metin kontrastı her eşleşmede en az 4.5:1.

**Hap Yumuşak Zemin Kuralı.** Durum hapları ham renkle değil, yumuşak
zemin + koyu metin çiftiyle kurulur (`green-soft`/`green-on-plate` gibi).
Ham hardal (#e8a33d) beyaz kart üstünde metin olarak yasak.

## Typography

**Display Font:** Noto Sans Display (Bold 700; self-hosted TTF, marka
kitinden) — ekran başlığı ve stat kartı değeri
**Body Font:** Google Sans (Regular) + Noto Sans (Regular/SemiBold) yığını
(self-hosted TTF; latin-ext dahil tam Türkçe glif desteği fontTools cmap
kontrolüyle doğrulandı)

**Character:** Noto Sans Display Bold panonun sayı ve başlık sesidir —
güven veren, modern, geniş. Gövde Google Sans arayüz metnidir; Türkçe
karakterler her iki ailede de birinci sınıftır.

### Hierarchy
- **Ekran başlığı** (Noto Sans Display 700, 21px, 0.01em, cümle case): h1 —
  "Genel Bakış", "Kanallar"… Yanında 12.5px arduvaz alt bilgi.
- **Stat değeri** (Noto Sans Display 700, 26px, 1.2 satır): stat kartının
  sayısı; `warn` durumunda hardal tonu.
- **Panel başlığı** (Google Sans 600, 13px): başlık şeridindeki h2.
- **Gövde** (Google Sans/Noto Sans 400, 14px, 1.5): tüm okuma metni;
  empty-state açıklamaları 13.5px, en fazla ~52ch satır.
- **Etiket** (500–600, 12px): stat kartı etiketi, tablo başlığı (th),
  gösterge etiketi — uppercase yok, doğal case.

### Named Rules
**Rakam Düz Durur Kuralı.** Veri sayıları her zaman tabular-nums
(`font-variant-numeric: tabular-nums`); akan rakam yok.

**Display Sayıda ve Başlıkta Kalır Kuralı.** Noto Sans Display yalnız h1,
stat değeri ve kısa etikette; paragraf metninde asla.

## Layout

Sol tarafta 216px sabit geceyarısı nav rayı (marka logosu + nokta göstergeli
8 hedef), sağında fildişi zeminli içerik alanı (dolgular 28px üst/alt, 40px
yan). Genel Bakış ilk viewport formülü: üst satır (h1 + sağda faz durum
hapı), altında dörtlü stat kartı grid'i (Bugün yayınlanan / Özel stok /
Bağlı kanal / İş kuyruğu), altında iki kolon (1.4fr/1fr) — solda Kanallar
tablo paneli + Boru hattı tablo paneli dikte, sağda Pi kaynakları meter
paneli.

Kırılımlar: stat grid'i ≤900px'te 2 kolona, ≤620px'te 1 kolona iner; iki
kolon ≤1100px'te tek kolona döner; ≤900px'te ray üst yatay hap sekmelerine
döner (kaydırmalı şerit, aktif hedef okyanus blok + koyu metin), içerik
dolgusu 20px'e iner, h1 18px.

Boşluk ölçeği: 4 / 8 / 14 / 20 / 28 / 40px. Yoğunluk izleme yoğunluğudur:
stat kartları kısa, tablo satırları sıkı (10px dikey dolgu), bolca hava yok.

## Elevation & Depth

Kartlar ölçülü tek gölge taşır: `--card-shadow: 0 1px 3px
rgba(11,25,44,.08)` — "Kategori Standardı" dilinin kâğıt-üstünde-kâğıt
hissi. Gölge bu tek değerle sınırlıdır; daha derin kalkma, çok katmanlı
gölge veya glow yok. Derinlik hiyerarşisi: fildişi zemin → beyaz kart
(1px #dfe5ec kontur + gölge) → koyu nav (ton katmanı).

### Named Rules
**Tek Gölge Kuralı.** Box-shadow yalnız `--card-shadow` değeriyle ve kart/
panel yüzeylerinde kullanılır; başka hiçbir öğe gölge taşımaz.

## Shapes

Köşe stratejisi "Kategori Standardı"ndan gelir: kart ve panel 10px, küçük
kontroller 8px, haplar ve meter'lar 99px (tam yuvarlak). İnce çizgi dili:
kart 1px kontur, panel başlık şeridi 1px alt çizgi, tablo satırları 1px
ayraç (#eef2f6). Kesikli kontur sözleşmesi korunur: kesikli çizgi
"bekleyen / henüz yok" demektir (empty-state kutusu).

## Brand Assets

- **Logo:** tam logo (amblem + "AutoShorts STUDIO" yazısı) sol rayın marka
  bloğunda, koyu zemin varyantı (`logo-dark-bg.svg`, 148px render
  genişliği). Açık zemin varyantı (`logo-light-bg.svg`) el altında.
- **İkon:** 512×512 amblem; tarayıcı favicon'u olarak aydınlık zemin
  varyyantı (`icon-light-bg.svg` → `/favicon.svg`).
- **Amblem anatomisi:** 'A' harfi + sinematik film şeridi rozeti; rozet
  okyanus yeşili, gövde zemine göre fildişi ya da geceyarısı mavisi.
- **Fontlar:** marka kitinden beş TTF self-hosted (`src/assets/fonts/`);
  CDN'e bağımlılık yok, Pi offline ortamında da tutarlı.

## Components

### Stat Kartı (stat-grid + stat-card)
Panonun özet dili: dörtlü grid (1fr×4 → 2 → 1). Kart = beyaz zemin, 1px
kontur, 10px köşe, kart gölgesi, 16px/18px dolgu. İçerik: 12px arduvaz
etiket + 26px Noto Sans Display 700 değer + 11.5px alt not. `warn`
varyantında değer hardal tonuna döner (Bağlı kanal 0 gibi). Sıfır da
gerçektir ve öyle gösterilir; veri uydurulmaz.

### Başlık Şeritli Panel (ink-panel)
Beyaz kart, içi dolgusuz; üstte h2 başlık şeridi (13px 600, 14px/18px
dolgu, 1px alt çizgi). Gövde öğeleri (tablo hariç) şeridin altında 18px
dolgu alır; tablolar panele kenardan kenara dayanır. İki kullanım: tablo
paneli (Kanallar, Boru hattı) ve meter paneli (Pi kaynakları).

### Durum Hapı (pill)
12px 600 metin, 4px/12px dolgu, 99px köşe; yumuşak zemin + koyu metin.
Varyantlar: `pill--ok` yeşim, `pill--warn` hardal, `pill--run` okyanus
yumşak, `pill--idle` arduvaz açık (zemin #eef2f6), `pill--error` kızıl.
Genel Bakış faz hapı aynı bileşendir: Kurulum/Kanal bekleniyor (warn) veya
Sistem sağlıklı (ok).

### Tablo (info-table)
Canon ince tablosu: th 12px 500 arduvaz, sol hizalı; td 13px gövde, 10px/18px
dolgu, satır ayraçları 1px #eef2f6. Kanal satırında kurdele rengi 10px
yuvarlak kare + isim th'de, durum habı son kolonda. `job-line` (Otomasyon)
aynı tablo dilinin satır formudur: sol etiket + sağ durum habı, 1px ayraç.

### Meter (gauge)
6px yuvarlak dolgu çubuğu: oluk #e2e8f0, normal dolgu okyanus yeşili,
`warn` (%80 üstü) hardal. Üstünde 12px etiket + yüzde değeri (tabular-nums);
role="meter" anlambilimi korunur.

### Buton (btn)
Okyanus yeşili zemin + geceyarısı mavisi metin (vurgu üstü koyu metin
kuralı), 8px köşe, 9px/18px dolgu, 600 13px. Hover'da bir ton açılır
(#2ff8c8). İkincil eylem `btn--ghost`: beyaz zemin, 1px kontur, gövde
mürekkebi.

### Durum Kutusu (state-box)
Boş katmanların temsili: kesikli kart çizgisi konturlu beyaz kutu (10px
köşe), ortada Display 700 20px başlık + 13.5px açıklama (≤52ch) + okyanus
butonu. Hata varyantı düz kızıl kontur + kızıl başlık. Empty-state metni
kullanıcının sıradaki kurulum adımını söyler.

### Yükleme ve Bayat Veri
Yükleme: kart yüzeyinde ölçülü `loading` göstergesi. Bağlantı koptuğunda:
`stale-note` — hardal konturlu ince şerit + tekrar dene butonu; eski veri
ekranda kalır, gizlenmez.

### Navigation (ray)
Sol ray geceyarısı mavisi: marka logosu üstte, altında nokta göstergeli
linkler (7px nokta #3a4a63). Aktif hedef okyanus yeşili blok + geceyarısı
metni + sağda 3px koyu şerit. Hover'da metin fildişiye açılır. Mobil: yatay
kaydırmalı hap sekmeler. Odak her yerde 2px okyanus halkası
(outline-offset 2px). Skip-link vurgu blok + koyu metin.

## Do's and Don'ts

### Do:
- **Do** okyanus yeşilini eylem/seçim için kullan: CTA, aktif nav, odak,
  normal meter dolgusu — başka hiçbir amaç için değil.
- **Do** vurgu üstünde daima geceyarısı mavisi metin kullan; asla beyaz değil.
- **Do** durumları yumuşak zeminli haplarla anlat; ham rengi hap zeminine
  dökme.
- **Do** veri sayılarını tabular-nums ile yaz; stat kartı değerini Display
  700 26px ile ver.
- **Do** boş veri katmanlarını yönlendirici empty-state'lerle göster;
  sentetik/örnek veri ancak "sentetik" etiketiyle görünür.
- **Do** Türkçe mikrocopy kullan; Türkçe karakterler UI'da serbesttir (tüm
  marka fontlarında tam glif desteği doğrulandı).
- **Do** klavye erişimini koru: görünür focus-visible halkası, skip-link,
  role="meter"/role="alert" anlambilimi.
- **Do** ekran başlıklarını cümle case yaz ("Genel Bakış"); uppercase başlık
  yok.

### Don't:
- **Don't** gradient metin, çok katmanlı gölge veya `--card-shadow` dışında
  box-shadow kullanma.
- **Don't** marquee dev sayı, damga veya jenerik blok geri getirme — bu
  bileşenler 2026-10-17 yön değişimiyle kaldırıldı.
- **Don't** kicker/eyebrow etiketi uydurma; panel başlığı h2'si yeter.
- **Don't** Noto Sans Display'i gövde metninde veya uzun paragraflarda
  kullanma.
- **Don't** ham hardalı (#e8a33d) beyaz kart üstünde metin rengi yapma —
  kartta #92610a kullan.
- **Don't** marka dışı renk veya harici font CDN'i katma; yeni yüzey bu
  dünyanın malzemesinden (kart, panel, hap, meter) olur.
- **Don't** API'de olmayan veriyi uydurma; sıfır da gerçektir ve öyle
  gösterilir.
