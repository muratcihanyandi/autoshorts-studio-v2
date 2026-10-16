import { EmptyState } from '../components/States'

export function LlmProvidersScreen() {
  return (
    <>
      <div className="screen-head">
        <h1>LLM SAĞLAYICILARI</h1>
        <span className="screen-sub">Ana sağlayıcı + iki yedek, sınırlı geçiş</span>
      </div>
      <EmptyState title="Sağlayıcı yapılandırılmadı">
        Altyazı düzeltme ve metaveri üretimi için üç sağlayıcı
        yapılandırılabilecek: bir ana, iki yedek. Ana sağlayıcı hata verirse
        sistem otomatik yedeğe geçer; API anahtarları maskeli gösterilir ve
        asla loglara yazılmaz.
      </EmptyState>
    </>
  )
}
