import type { PulseEvent, PulseTone } from '../api/pulse'
import { jobAction } from '../jobNarrative'

/** Olayları stüdyonun sesine çevirir: her satır bir doğal Türkçe cümle.
 * Teknik terim yerine "hangi video ne oldu" anlatılır; hata metni varsa
 * cümlenin sonunda kısaltılmış girer. */

export interface PulseStory {
  tone: PulseTone
  /** Ana cümle — videolu olaylarda başlık cümlenin içinde gelir. */
  sentence: string
  /** Kısa özne (video/kanal adı); yoksa null. */
  subject: string | null
  /** Yönlenenme hedefi (uyguluma içi yol). */
  link: string | null
  /** İsteğe bağlı kısa not: hata özeti ya da bağlam. */
  note: string | null
  /** Duygusal durum ikonu */
  icon?: string
}

const JOB_SUCCESS: Record<string, string> = {
  media_process: 'işlendi ve stoka alındı',
  clip_render: 'dikey kliplere dönüştürüldü',
  clip_render_full_cut: 'yatay tam keside budandı',
  hype_evaluate: 'klip adayları puanlandı',
  metadata_generate: 'yayın bilgileri hazırlandı',
  subtitle_correct: 'altyazıları düzeltildi',
  publish_due: 'yayın turu tamamlandı',
  publish_clip: 'YouTube’a yüklendi',
  publish_full_cut: 'YouTube’a yüklendi',
  source_discover: 'kaynak taraması tamamlandı',
  ops_summary: 'günlük özet çıkarıldı',
}

const JOB_FAIL: Record<string, string> = {
  media_process: 'işlenemedi',
  clip_render: 'dikey kliplere dönüştürülemedi',
  clip_render_full_cut: 'tam kesit budanamadı',
  subtitle_correct: 'altyazıları düzeltilmedi',
  metadata_generate: 'yayın bilgileri hazırlanamadı',
  publish_due: 'yayın turu tamamlanamadı',
  publish_clip: 'YouTube’a yüklenemedi',
  publish_full_cut: 'YouTube’a yüklenemedi',
  source_discover: 'kaynak taraması yarıda kaldı',
}

const AUDIT_STORY: Record<string, { sentence: string; link?: string }> = {
  'publish.public': {
    sentence: 'YouTube’da herkese açıldı',
    link: '/medya',
  },
  'publish.private': { sentence: 'gizliye alındı', link: '/medya' },
  'publish.done': { sentence: 'yayınlandı', link: '/medya' },
  'publish.rescheduled': { sentence: 'yayın saati güncellendi', link: '/takvim' },
  'publish.no_ready': {
    sentence: 'Yayın saati geldi ama hazır klip yok — sıradaki turu bekliyor',
    link: '/otomasyon',
  },
  'automation.started': { sentence: 'otomasyonu başladı', link: '/otomasyon' },
  'automation.stopped': { sentence: 'otomasyonu durduruldu', link: '/otomasyon' },
  'automation.paused': { sentence: 'otomasyonu beklemeye alındı', link: '/otomasyon' },
  'automation.error': { sentence: 'otomasyonunda bir aksilik oldu', link: '/gunlukler' },
  'media.cleaned': { sentence: 'eski medya dosyaları temizlendi' },
  'media.lost_file_sweep': {
    sentence: 'dosyası kaybolmuş videolar temizlendi',
    link: '/medya',
  },
  'hype.fallback': { sentence: 'hype puanlaması yedek yolla tamamlandı' },
}

function shortError(text: string | undefined | null): string | null {
  if (!text) return null
  const clean = text.trim()
  if (!clean) return null
  return clean.length > 120 ? `${clean.slice(0, 117)}…` : clean
}

export function pulseStory(event: PulseEvent): PulseStory {
  const subject = event.title?.trim() || null
  const channel = event.channel_name?.trim() || null

  if (event.kind === 'job_finished') {
    const jobType = String(event.detail?.job_type ?? '')
    if (event.event_type === 'job.succeeded') {
      const action = JOB_SUCCESS[jobType] ?? 'tamamlandı'
      const icon =
        jobType.includes('publish')
          ? '🚀'
          : jobType.includes('clip_render')
            ? '🎬'
            : jobType === 'media_process'
              ? '✨'
              : '✓'
      return {
        tone: 'ok',
        sentence: subject
          ? `“${subject}” ${action}`
          : cap(jobAction({ job_type: jobType }) || 'Görev tamamlandı'),
        subject,
        link: '/medya',
        note: null,
        icon,
      }
    }
    const failAction = JOB_FAIL[jobType] ?? 'tamamlanamadı'
    return {
      tone: 'error',
      sentence: subject
        ? `“${subject}” ${failAction}`
        : 'Bir görev tamamlanamadı',
      subject,
      link: '/otomasyon',
      note: shortError(event.detail?.last_error as string | undefined),
      icon: '⚠️',
    }
  }

  const known = AUDIT_STORY[event.event_type]
  if (known) {
    const withSubject = subject
      ? `“${subject}” ${known.sentence}`
      : channel
        ? `${channel}: ${known.sentence}`
        : cap(known.sentence)
    const icon =
      event.event_type === 'publish.public'
        ? '🌟'
        : event.event_type === 'publish.private'
          ? '🔒'
          : event.tone === 'ok'
            ? '✨'
            : event.tone === 'error'
              ? '⚠️'
              : '🔔'
    return {
      tone: event.tone,
      sentence: withSubject,
      subject: subject ?? channel,
      link: known.link ?? null,
      note: null,
      icon,
    }
  }

  return {
    tone: event.tone,
    sentence: subject
      ? `“${subject}” — stüdyoda yeni bir gelişme`
      : 'Stüdyoda yeni bir gelişme',
    subject,
    link: null,
    note: null,
    icon: event.tone === 'ok' ? '✨' : event.tone === 'error' ? '⚠️' : '🔔',
  }
}

function cap(text: string): string {
  if (!text) return text
  return text.charAt(0).toLocaleUpperCase('tr-TR') + text.slice(1)
}

/** "3 dk önce" / "2 sa önce" / "dün" gibi göreli zaman. */
export function relativeTime(iso: string | null): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (seconds < 45) return 'az önce'
  if (seconds < 3600) return `${Math.round(seconds / 60)} dk önce`
  if (seconds < 86400) return `${Math.round(seconds / 3600)} sa önce`
  if (seconds < 172800) return 'dün'
  return `${Math.round(seconds / 86400)} gün önce`
}
