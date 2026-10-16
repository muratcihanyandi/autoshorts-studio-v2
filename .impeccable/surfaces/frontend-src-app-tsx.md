---
version: 1
slug: "frontend-src-app-tsx"
primary_target: "frontend/src/App.tsx"
related_targets: []
---

# Surface brief — Studio arayüzü (SPA, frontend/src/App.tsx)

## Scope and visitor mode

Kapsam: Autonomous Creator Studio tek sayfalık uygulamasının tüm ekranları
(Overview, Kanallar, Medya Kütüphanesi, Takvim, Otomasyon, LLM
Sağlayıcıları, Günlükler, Ayarlar). Ziyaretçi modu: **Operate** — kullanıcı
işini yapıp çıkar; durum takibi ağırlıklı, tam otomatik yayınlama.

## Audience, job, action, proof, constraints

- Seyirci: stüdyonun sahibi; LAN'dan tarayıcıyla girer, çoğunlukla akşam.
- İş: 5 saniyede "sorun var mı, ne oluyor" cevabını almak.
- Aksiyon: müdahale istisnadır (duraklat/iptal); onay damga olarak kalır.
- Kanıt: gerçek API verisi (/api/overview, /api/system, /api/health).
- Kısıtlar: Türkçe mikrocopy, klavye erişimi, Pi kaynak göstergeleri,
  boş veri katmanları yönlendirici empty-state'lerle temsil edilir.

## Direction contract

THESIS: Stüdyo panosu bir Yeşilçam baskı odasıdır — günün çıktısı krem
afiş levhaları olarak asılır, durum poster mürekkebiyle basılır; nötr gri
panel + tek vurgu kategori varsayılanı reddedilir.

OWN-WORLD: koyu mürekkep zemini (#171B26) üstünde krem afiş levhaları
(#F2ECDD); poster mürekkepleri durum işi yapar — kırmızı #C93A2E kritik +
damga, hardal #D9A036 uyarı, çamurdan yeşil #2E7F6F sağlıklı, kobalt
#3550C4 seçim/aktif; Anton afiş display'i yalnız başlıklarda ve dev
sayılarda, gövde sistem sans'ı; jenerik blok sıkılığı (ince mürekkep
çizgileriyle ayrılan sıkı büyük-harf satırları).

STORY: kullanıcı odaya girer girmez bugünün sayısını ve hangi aşamada ne
olduğunu okur; otomasyonun imzası kırmızı "ŞİMDİ YAYINDA" damgasıdır;
müdahale ederse onun damgası da panoda kalır; hata vermilyon errata
yapıştırması gibi araya girer ve nasıl düzeltileceğini söyler.

FIRST VIEWPORT: solda koyu nav rayı (marka bloğu + 8 hedef; aktif kobalt
blok, krem metin), sağda ana krem afiş levhası: dev "7 / BUGÜN YAYINLANAN
KLİP" + sağ üstte kırmızı ŞİMDİ YAYINDA damgası (hafif eğik) + altında
jenerik blok (KAYNAK İZLEME…YAYIN satırları, sağda değerler, uyarılar
hardal); sağ kolonda iki koyu panel: Pi kaynak mürekkep göstergeleri
(CPU/RAM/disk/sıcaklık) ve kurdele renkli kanal listesi. Onaylı kompozisyon:
.impeccable/mocks/decision/assigned.html.

FORM: Yeşilçam Baskı Odası — sıralı aday listemde 3. sıra; seed anahtarı
edec7d88; reddedilen rakiplerden alınan yükseltmeler: design-annual'dan
dönen damga (insan müdahalesi), character-goods'tan kanal kurdele rengi,
orienteering'den plan/gerçekleşen katman ayrımı (Takvim), acetate-manual'dan
vermilyon errata hata durumu.

FINISH: unreviewed and undocumented is unfinished; this build ends with
the finish review, the verdict, DESIGN.md, and every shipping raster
carrying its provenance.

## Memorable moment

Marquee levhası + kırmızı damganın basılış anı (tek koreografi edilmiş
motion; prefers-reduced-motion'da kapalı).

## Unresolved decisions

- Günlükler ekranının canlı akışı (log API M6'da); şimdilik empty-state.
