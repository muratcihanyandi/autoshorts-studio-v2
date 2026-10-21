/**
 * Dikey klip altyazı önizlemesi (temsilî).
 *
 * Arka ucun subtitle_style.build_ass hesabını birebir yansıtır:
 * 1080x1920 kadran, alt bant = üst bölümün altında %68'den başlar,
 * altyazı ALT kenarı konum çapasına bandın içinde oturur. Ölçek
 * 1/4'e küçültülür; yazı boyutu ve konum ayarı değiştikçe canlı
 * güncellenir — kaydetmeden çıktının nasıl görüneceği görülür.
 */
const OUT_W = 1080
const OUT_H = 1920
const SCALE = 0.25
const PREVIEW_W = OUT_W * SCALE
const PREVIEW_H = OUT_H * SCALE
const TEXT_MARGIN_H = 60

// Temsilî üst bölüm oranı: gerçek klipte webcam dikdörtgeninin
// en-boy oranından türür; önizleme tipik bir değerde çizilir.
const REPRESENTATIVE_TOP_H = Math.round(OUT_H * 0.45)
const BAND_Y1 = REPRESENTATIVE_TOP_H + Math.round(
  (OUT_H - REPRESENTATIVE_TOP_H) * 0.68,
)
const BAND_Y2 = OUT_H - 24

// subtitle_style.POSITION_ANCHORS ile aynı tablo.
const POSITION_ANCHORS: Record<string, number> = {
  top: 0.35,
  middle: 0.65,
  bottom: 0.95,
}

const SAMPLE_TEXT = 'İşte günün en heyecanlı anı — kaçırmayın!'

interface SubtitlePreviewProps {
  burn: boolean
  fontSizePx: number
  position: string
}

export function SubtitlePreview({
  burn,
  fontSizePx,
  position,
}: SubtitlePreviewProps) {
  const anchor = POSITION_ANCHORS[position] ?? POSITION_ANCHORS.middle
  // ASS Alignment=2: metin ALT kenarı kadranın altından MarginV
  // piksel yukarıda — önizleme aynı ofseti ölçekleyerek kullanır.
  const marginV =
    OUT_H - (BAND_Y1 + (BAND_Y2 - BAND_Y1) * anchor)

  return (
    <div className="sub-preview">
      <div
        className="sub-preview-frame"
        style={{ width: PREVIEW_W, height: PREVIEW_H }}
        role="img"
        aria-label="Dikey klip altyazı önizlemesi (temsilî)"
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
              bottom: marginV * SCALE,
              width: (OUT_W - 2 * TEXT_MARGIN_H) * SCALE,
              fontSize: Math.max(6, fontSizePx * SCALE),
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
        değişir; altyazı daima alt bantta kalır.
      </span>
    </div>
  )
}
