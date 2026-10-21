/**
 * Dikey klip altyazı önizlemesi (temsilî).
 *
 * Arka ucun subtitle_style.build_ass hesabını birebir yansıtır:
 * 1080x1920 kadran, altyazı çapası (alt kenar ortası) yüzde
 * kaydırıcılarıyla kadranın herhangi bir noktasına taşınır (Görev 2);
 * stil (Görev 1) ASS preset'lerinin CSS karşılıklarıyla çizilir.
 * Ölçek 1/4'e küçültülür; yazı boyutu, stil ve konum değiştikçe canlı
 * güncellenir — kaydetmeden çıktının nasıl görüneceği görülür.
 */
const OUT_W = 1080
const OUT_H = 1920
const SCALE = 0.25
const PREVIEW_W = OUT_W * SCALE
const PREVIEW_H = OUT_H * SCALE

// Temsilî üst bölüm oranı: gerçek klipte webcam dikdörtgeninin
// en-boy oranından türer; önizleme tipik bir değerde çizilir.
const REPRESENTATIVE_TOP_H = Math.round(OUT_H * 0.45)

const SAMPLE_TEXT = 'İşte günün en heyecanlı anı!'
const STYLE_CSS: Record<
  string,
  {
    label: string
    fontFamily: string
    fontWeight: number
    color: string
    stroke: string
    box?: string
  }
> = {
  klasik: {
    label: 'Klasik Beyaz',
    fontFamily: "'Google Sans', 'Noto Sans', sans-serif",
    fontWeight: 400,
    color: '#ffffff',
    stroke: '#000000',
  },
  shorts_sari: {
    label: 'Shorts Sarı',
    fontFamily: "'Google Sans', 'Noto Sans', sans-serif",
    fontWeight: 700,
    color: '#ffee00',
    stroke: '#000000',
  },
  anton: {
    label: 'Anton',
    fontFamily: "'Anton', 'Noto Sans Display', sans-serif",
    fontWeight: 400,
    color: '#ffffff',
    stroke: '#000000',
  },
  kutu: {
    label: 'Kutulu',
    fontFamily: "'Google Sans', 'Noto Sans', sans-serif",
    fontWeight: 700,
    color: '#ffffff',
    stroke: '#000000',
    box: 'rgba(0, 0, 0, 0.6)',
  },
  noto: {
    label: 'Noto Sans',
    fontFamily: "'Noto Sans', sans-serif",
    fontWeight: 400,
    color: '#ffffff',
    stroke: '#000000',
  },
}

interface SubtitlePreviewProps {
  burn: boolean
  fontSizePx: number
  styleKey: string
  posX: number
  posY: number
}

export function SubtitlePreview({
  burn,
  fontSizePx,
  styleKey,
  posX,
  posY,
}: SubtitlePreviewProps) {
  const css = STYLE_CSS[styleKey] ?? STYLE_CSS.klasik
  const fontSize = Math.max(6, fontSizePx * SCALE)
  // ASS konturu (Outline piksel) ölçeklenmiş text-shadow'a çevrilir;
  // 8 yönlü gölge tek yönlü kontüre göre gerçeğe daha yakındır.
  const stroke = Math.max(1, Math.round((styleKey === 'anton' ? 5 : styleKey === 'noto' ? 3 : 4) * SCALE))
  const shadow = Array.from({ length: 8 }, (_, i) => {
    const angle = (Math.PI / 4) * i
    return `${Math.cos(angle) * stroke}px ${Math.sin(angle) * stroke}px 0 ${css.stroke}`
  }).join(', ')

  return (
    <div className="sub-preview">
      <div
        className="sub-preview-frame"
        style={{ width: PREVIEW_W, height: PREVIEW_H }}
        role="img"
        aria-label={`Dikey klip altyazı önizlemesi — ${css.label} stili, yatayda %${posX}, dikeyde %${posY}`}
      >
        <div
          className="sub-preview-top"
          style={{ height: REPRESENTATIVE_TOP_H * SCALE }}
        >
          <span>Kamera</span>
        </div>
        <div className="sub-preview-bottom">
          <span>Kaynak video</span>
        </div>
        {burn ? (
          <div
            className="sub-preview-text"
            style={{
              left: `${posX}%`,
              bottom: `${100 - posY}%`,
              maxWidth: '86%',
              fontSize,
              fontFamily: css.fontFamily,
              fontWeight: css.fontWeight,
              color: css.color,
              textShadow: shadow,
              background: css.box,
              padding: css.box ? '2px 8px' : undefined,
              borderRadius: css.box ? 4 : undefined,
            }}
          >
            {SAMPLE_TEXT}
          </div>
        ) : (
          <div className="sub-preview-off">Altyazı kapalı</div>
        )}
      </div>
      <span className="field-help">
        Temsilî önizleme — kamera bölümünün yüksekliği klipe göre
        değişir; altyazı çapasını kaydırıcılarla kadranın istediğin
        yerine taşıyabilirsin.
      </span>
    </div>
  )
}
