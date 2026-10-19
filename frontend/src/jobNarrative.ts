/** İş tiplerini ve aşamalarını doğal Türkçe cümlelere çevirir.
 * Otomasyon ekranı ve boru hattı detay penceresi paylaşır; amaç satır
 * satır teknik log yerine "hangi video ne oluyor" anlatmak. */

/** Yatay medya işleme aşamalarının eylem karşılıkları */
const MEDIA_STAGE_ACTION: Record<string, string> = {
  download: 'indiriliyor',
  inspect: 'dosya denetiminden geçiyor',
  transcript: 'yazıya çıkarılıyor',
  analysis: 'analiz ediliyor',
  candidates: 'klip adayları seçiliyor',
}

/** Videolu işlerde kısa eylem, videosuz işlerde kendi özneli tam
 * cümle döner. Başlık varsa arayüz onu eylemin önüne koyar. */
export function jobAction(job: {
  job_type: string
  stage?: string | null
  channel_name?: string | null
}): string {
  switch (job.job_type) {
    case 'media_process':
      return (job.stage && MEDIA_STAGE_ACTION[job.stage]) || 'işleniyor'
    case 'hype_evaluate':
      return 'hype puanlamasından geçiyor'
    case 'clip_render':
      return 'dikey kliplere dönüştürülüyor'
    case 'clip_render_full_cut':
      return 'tam keside budanıyor'
    case 'source_discover':
      return job.channel_name
        ? `${job.channel_name} için yeni videolar aranıyor`
        : 'yetkili kaynaklarda yeni videolar aranıyor'
    case 'publish_due':
      return 'yayın saati gelen klipler yayınlanıyor'
    case 'subtitle_correct':
      return 'altyazıları düzeltiliyor'
    case 'metadata_generate':
      return 'yayın bilgileri hazırlanıyor'
    case 'ops_summary':
      return 'günlük özet hazırlanıyor'
    default:
      return 'işleniyor'
  }
}

/** Detaylı ve anlaşılır aşama açıklaması. */
export function jobStageDetail(job: {
  job_type: string
  stage?: string | null
}): string {
  if (job.job_type === 'media_process') {
    switch (job.stage) {
      case 'download':
        return 'Video yüksek kalitede cihaza indiriliyor.'
      case 'inspect':
        return 'Video çözünürlüğü ve ses kanalları inceleniyor.'
      case 'transcript':
        return 'Whisper yapay zekası video sesini dinleyip metne çeviriyor.'
      case 'analysis':
        return 'Yapay zeka videodaki en etkileyici sahneleri seçiyor.'
      case 'candidates':
        return 'Kısa Shorts videoları için en uygun kesit adayları belirleniyor.'
      default:
        return 'Video işleme boru hattından geçiyor.'
    }
  }
  if (job.job_type === 'hype_evaluate') {
    return 'Seçilen klip adayları yapay zeka ile puanlanıp sıralanıyor.'
  }
  if (job.job_type === 'clip_render') {
    return 'Yatay video 9:16 dikey formatta kırpılıp altyazıları ekleniyor.'
  }
  if (job.job_type === 'source_discover') {
    return 'Yetkili kanallara yeni bir video yüklenip yüklenmediği taranıyor.'
  }
  return 'Sistem görevi yürütülüyor.'
}

/** Bitmiş işlerin sonuç cümlesi: tamamlanan/hatalı/iptal. */
export function jobOutcome(status: string): string | null {
  if (status === 'succeeded') return 'Başarıyla tamamlandı ve stoka eklendi'
  if (status === 'failed') return 'İşlem sırasında hata oluştu'
  if (status === 'cancelled') return 'İşlem kullanıcı tarafından iptal edildi'
  return null
}

