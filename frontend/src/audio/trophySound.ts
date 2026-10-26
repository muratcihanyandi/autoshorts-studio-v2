/**
 * PlayStation tarzı kupa ses motoru (Web Audio API).
 * Sıfır harici dosya bağımlılığıyla saf sentezleme.
 */

let audioCtx: AudioContext | null = null

function getAudioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null
  const AudioContextClass =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!AudioContextClass) return null

  if (!audioCtx || audioCtx.state === 'closed') {
    audioCtx = new AudioContextClass()
  }
  if (audioCtx.state === 'suspended') {
    void audioCtx.resume()
  }
  return audioCtx
}

export type TrophyTier = 'bronze' | 'silver' | 'gold' | 'platinum'

/**
 * PlayStation standart kupa sesi (Bronz, Gümüş, Altın).
 * Kristal, çift çınlamalı ikonik "ching-pling" tınısı.
 */
export function playStandardTrophySound(): void {
  try {
    const ctx = getAudioContext()
    if (!ctx) return

    const now = ctx.currentTime

    // 1. Kristal ton (Chime 1 - E6 ~1318.5 Hz)
    playChime(ctx, 1318.5, now, 0.9, 0.45)
    playChime(ctx, 2637.0, now, 0.6, 0.15) // Harmonik ışıltı

    // 2. Yükselen ikinci kristal ton (Chime 2 - A6 ~1760 Hz, 85ms sonra)
    const t2 = now + 0.085
    playChime(ctx, 1760.0, t2, 1.4, 0.5)
    playChime(ctx, 3520.0, t2, 0.8, 0.2) // Yüksek parlama
    playChime(ctx, 2200.0, t2, 1.1, 0.18) // Üçüncül zenginlik
  } catch {
    // Ses çalma hatası sessizce yutulur (kullanıcı etkileşimi öncesi tarayıcı kısıtı)
  }
}

/**
 * Tek bir kristal çan osilatörü ve zarfı (envelope).
 */
function playChime(
  ctx: AudioContext,
  freq: number,
  startTime: number,
  duration: number,
  gainLevel: number,
): void {
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()

  osc.type = 'sine'
  osc.frequency.setValueAtTime(freq, startTime)

  // Attack: Çok hızlı (5ms)
  gain.gain.setValueAtTime(0.0001, startTime)
  gain.gain.exponentialRampToValueAtTime(gainLevel, startTime + 0.005)

  // Exponential Decay: Uzun süzülen kristal çınlama
  gain.gain.exponentialRampToValueAtTime(0.0001, startTime + duration)

  osc.connect(gain)
  gain.connect(ctx.destination)

  osc.start(startTime)
  osc.stop(startTime + duration)
}

/**
 * PlayStation Platin Kupa sesi (YouTube Partneri / Para Kazanma Açıldı!).
 * Çok daha görkemli, tok bas temelli, yükselen zafer arpeji ve uzun kristal yankı.
 */
export function playPlatinumTrophySound(): void {
  try {
    const ctx = getAudioContext()
    if (!ctx) return

    const now = ctx.currentTime

    // 1. Derin Tok Bas Darbesi (Derinlik ve ağırlık katar: A2 110Hz + E2 82.4Hz)
    playBassImpact(ctx, 110, now, 2.2, 0.4)
    playBassImpact(ctx, 164.8, now, 1.8, 0.25)

    // 2. Yükselen Görkemli Zafer Arpeji (C5 -> E5 -> G5 -> B5 -> C6 -> E6 -> G6)
    const notes = [
      { f: 523.25, offset: 0.0, d: 1.8, g: 0.25 }, // C5
      { f: 659.25, offset: 0.09, d: 1.8, g: 0.28 }, // E5
      { f: 783.99, offset: 0.18, d: 2.0, g: 0.32 }, // G5
      { f: 987.77, offset: 0.27, d: 2.2, g: 0.35 }, // B5
      { f: 1046.5, offset: 0.36, d: 2.5, g: 0.4 }, // C6
      { f: 1318.51, offset: 0.46, d: 2.7, g: 0.45 }, // E6
      { f: 1567.98, offset: 0.58, d: 3.2, g: 0.5 }, // G6 (Zirve akor)
    ]

    for (const n of notes) {
      playChime(ctx, n.f, now + n.offset, n.d, n.g)
      // Üst oktav ışıltısı
      playChime(ctx, n.f * 2, now + n.offset, n.d * 0.7, n.g * 0.25)
    }

    // 3. Zirve Zafer Akoru (Görkemli yankılanan Majör akor)
    const climaxTime = now + 0.65
    const climaxChords = [1046.5, 1318.51, 1567.98, 2093.0]
    for (const freq of climaxChords) {
      playChime(ctx, freq, climaxTime, 3.2, 0.25)
    }
  } catch {
    // Tarayıcı ses güvenlik kısıtları
  }
}

/**
 * Tok bas darbesi üretici.
 */
function playBassImpact(
  ctx: AudioContext,
  freq: number,
  startTime: number,
  duration: number,
  gainLevel: number,
): void {
  const osc = ctx.createOscillator()
  const gain = ctx.createGain()

  osc.type = 'triangle'
  osc.frequency.setValueAtTime(freq, startTime)
  // Hafif pitch drop (tok davul/patlama hissi)
  osc.frequency.exponentialRampToValueAtTime(freq * 0.7, startTime + duration)

  gain.gain.setValueAtTime(0.0001, startTime)
  gain.gain.exponentialRampToValueAtTime(gainLevel, startTime + 0.02)
  gain.gain.exponentialRampToValueAtTime(0.0001, startTime + duration)

  osc.connect(gain)
  gain.connect(ctx.destination)

  osc.start(startTime)
  osc.stop(startTime + duration)
}

/**
 * İlgili kupa derecesine göre doğru sesi çalar.
 */
export function playTrophySound(tier: TrophyTier): void {
  if (tier === 'platinum') {
    playPlatinumTrophySound()
  } else {
    playStandardTrophySound()
  }
}
