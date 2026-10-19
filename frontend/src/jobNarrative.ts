/** İş tiplerini ve aşamalarını doğal Türkçe cümlelere çevirir.
 * Otomasyon ekranı ve boru hattı detay penceresi paylaşır; amaç satır
 * satır teknik log yerine "hangi video ne oluyor" anlatmak. */

/** Yatay medya işleme aşamalarının eylem karşılıkları
 * (backend PIPELINE_STAGES sırasıyla aynıdır). */
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

/** Bitmiş işlerin sonuç cümlesi: tamamlanan/hatalı/iptal. */
export function jobOutcome(status: string): string | null {
  if (status === 'succeeded') return 'tamamlandı'
  if (status === 'failed') return 'başarısız oldu'
  if (status === 'cancelled') return 'iptal edildi'
  return null
}
