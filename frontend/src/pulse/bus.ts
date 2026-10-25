import type { LocalPulse } from './PulseProvider'

/** Yerel eylem bildirimleri için minik olay yolu.
 *
 * Ekranlar useRouter/PulseProvider bağımlılığı olmadan notifyPulse()
 * çağırır; sağlayıcı yoksa bildirim sessizce yok olur (testler ve
 * sağlayıcısız render'lar kırılmaz). */

type Listener = (pulse: LocalPulse) => void

const listeners = new Set<Listener>()

export function notifyPulse(pulse: LocalPulse): void {
  for (const listener of listeners) {
    try {
      listener(pulse)
    } catch {
      // Tek bir dinleyicinin hatası diğerlerini etkilemesin.
    }
  }
}

export function subscribePulse(listener: Listener): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
