import { useCallback } from 'react'
import { usePolling } from '../hooks/usePolling'
import { fetchOverview } from '../api/overview'
import { StaleNote } from '../components/States'

/**
 * Kurulum rehberi: bağlantı ve yapılandırma adımlarının tek adresi.
 * İçerik statiktir; arka ucun ayakta olup olmadığı yalnızca üstteki
 * staleness notuyla belirtilir.
 */
export function GuideScreen() {
  const fetcher = useCallback(() => fetchOverview(), [])
  const { state, retry } = usePolling(fetcher, 30000)

  return (
    <>
      <div className="screen-head">
        <h1>Rehber</h1>
        <span className="screen-sub">Nerede ne yapılır — adım adım</span>
      </div>

      {state.status === 'ok' && state.stale && <StaleNote onRetry={retry} />}

      <div className="stack">
        <section className="plate">
          <h2 className="panel-title">1. YouTube Kanalını Bağlama</h2>
          <p className="plate-note">
            Amaç: stüdyo kanalının, Google onayıyla kendi YouTube hesabınıza
            bağlanması. Client ID ve Secret dışında Google’dan alınacak hazır
            bir şey yoktur; aşağıdaki adımlar tek seferlik yapılır.
          </p>
          <ol className="guide-steps">
            <li>
              <b>Google Cloud Console’da proje açın:</b>{' '}
              <a
                href="https://console.cloud.google.com/"
                target="_blank"
                rel="noreferrer"
              >
                console.cloud.google.com
              </a>{' '}
              → sol menüden <b>APIs &amp; Services → Library</b> →{' '}
              <b>YouTube Data API v3</b>’ü arayıp <b>Enable</b> deyin. (Analytics
              ve Reporting API’leri gerekmez.)
            </li>
            <li>
              <b>OAuth onay ekranını hazırlayın:</b> APIs &amp; Services →{' '}
              <b>OAuth consent screen</b>. User type <b>External</b>. Uygulama
              adı ve destek e-postasını doldurun. Yayın durumu{' '}
              <b>In production</b> olmalı: Testing modunda Google, verdiği
              yenileme anahtarlarını 7 günde düşürür ve bağlantı kopar. In
              production’da kendi hesabınız için “doğrulanmamış uygulama”
              uyarısı görünür; Advanced → devam ederek geçebilirsiniz (kendi
              uygulamanızdır).
            </li>
            <li>
              <b>OAuth istemcisi oluşturun:</b> APIs &amp; Services →{' '}
              <b>Credentials</b> → <b>+ Create Credentials → OAuth client
              ID</b> → tür <b>Web application</b>. Elde ettiğiniz{' '}
              <b>Client ID</b> ve <b>Client Secret</b> stüdyonun Ayarlar
              ekranına girilir.
            </li>
            <li>
              <b>Yetkili yönlendirme URI’sini kaydedin (kritik adım):</b>{' '}
              İstemcinin <b>Authorized redirect URIs</b> bölümüne,{' '}
              <b>bağlanacak her stüdyo kanalı için</b> tam adresi satır satır
              ekleyin:
              <code className="guide-code">
                http://localhost:1478/api/channels/KANAL_ID/oauth/callback
              </code>
              <b>KANAL_ID</b>, Kanallar ekranındaki kaydın numarasıdır (ilk
              kanal genelde 1). Emin olmak için tarayıcıda{' '}
              <code className="guide-code">http://PI_ADRESI:1478/api/channels</code>{' '}
              adresini açın; JSON içindeki <b>id</b> alanı kanal numarasıdır.
              Adres, son karakterine kadar birebir aynı olmalıdır — port, yol
              ve kanal numarası dahil.
            </li>
            <li>
              <b>Neden localhost?</b> Google, yönlendirme adreslerinde{' '}
              <b>HTTP’yi yalnızca localhost / 127.0.0.1 için</b> kabul eder;
              LAN adresi (<code>http://192.168.x.x:1478/…</code>) reddedilir.
              Bu yüzden onay adımı stüdyoya “localhost” üzerinden yapılır.
              Gerçek bir alan adınız varsa HTTPS’li adres de
              kullanabilirsiniz; yoksa localhost yeterlidir.
            </li>
            <li>
              <b>Stüdyonun Ayarlar ekranını doldurun:</b>{' '}
              <table className="guide-table">
                <tbody>
                  <tr>
                    <th>Google Client ID / Secret</th>
                    <td>3. adımda aldığınız değerler</td>
                  </tr>
                  <tr>
                    <th>Token Şifreleme Anahtarı</th>
                    <td>
                      Üretilmiş Fernet anahtarı (32 bayt urlsafe base64).
                      Kaybolduğunda kanalları yeniden bağlamanız gerekir;
                      kanallar bağlandıktan sonra değiştirmeyin.
                    </td>
                  </tr>
                  <tr>
                    <th>OAuth Yönlendirme Adresi</th>
                    <td>http://localhost:1478</td>
                  </tr>
                  <tr>
                    <th>Arayüz Adresi</th>
                    <td>
                      http://PI_ADRESI:1478 — stüdyoyu tarayıcıda açtığınız
                      gerçek adres (var olmayan bir alan adı yazmayın)
                    </td>
                  </tr>
                  <tr>
                    <th>YouTube API Anahtarı</th>
                    <td>
                      İsteğe bağlı; yalnızca kaynak kanal izleme için. Credentials
                      → Create Credentials → API key.
                    </td>
                  </tr>
                </tbody>
              </table>
            </li>
            <li>
              <b>Bağlanma anı (SSH tüneli):</b> Google sizi{' '}
              <code>localhost:1478</code>’e geri yönlendireceği için, onay
              verirken tarayıcınızın olduğu makineden Pi’ye tünel açın:
              <code className="guide-code">
                ssh -N -L 1478:localhost:1478 KULLANICI@PI_ADRESI
              </code>
              Sonra tarayıcıda <b>http://localhost:1478</b> → Kanallar →
              kanalın <b>Bağla</b> düğmesi → Google hesabınızı seçip onaylayın.
              Onay tamamlanınca izinler sunucuya kaydedilir; tünel yalnızca
              bağlantı (ve ileride yeniden bağlama) anında gereklidir. Normal
              kullanıma Pi’nin LAN adresiyle devam edersiniz.
            </li>
          </ol>
        </section>

        <section className="plate">
          <h2 className="panel-title">2. LLM Sağlayıcısı Ekleme</h2>
          <p className="plate-note">
            Altyazı düzeltme ve metaveri üretimi için en fazla üç sağlayıcı:
            öncelik 1 ana, 2 ve 3 yedektir. Ana sağlayıcı hata verirse sistem
            otomatik yedeğe geçer.
          </p>
          <ol className="guide-steps">
            <li>
              <b>Türü belirleyin:</b> API’nizin hangi uç noktayı kullandığını
              sağlayıcınızın dokümanından kontrol edin:
              <table className="guide-table">
                <tbody>
                  <tr>
                    <th>OpenAI uyumlu</th>
                    <td>…/chat/completions</td>
                  </tr>
                  <tr>
                    <th>Anthropic uyumlu</th>
                    <td>…/messages</td>
                  </tr>
                  <tr>
                    <th>Google uyumlu</th>
                    <td>…/models/&#123;model&#125;:generateContent</td>
                  </tr>
                </tbody>
              </table>
            </li>
            <li>
              <b>API Adresi’ne yalnızca kök adresi yazın:</b> uç nokta yolu
              seçtiğiniz türe göre otomatik eklenir. Yanlış:{' '}
              <code>https://api.ornek.com/v1/chat/completions</code> — doğru:{' '}
              <code>https://api.ornek.com/v1</code>. Formun altındaki “İstek
              adresi” satırı gönderilecek tam adresi canlı gösterir.
            </li>
            <li>
              <b>Model Kimliği</b> sağlayıcınızın model adıdır (örn.{' '}
              <code>gemma-4-31b</code>). Ekledikten sonra <b>Dene</b> ile
              bağlantıyı kontrol edin; sonuç “Son İstekler” bölümüne kaydedilir.
            </li>
            <li>
              <b>Aynı sağlayıcıdan başka model:</b> kayıtlı sağlayıcının{' '}
              <b>Kopyala</b> düğmesi satırı anahtarıyla birlikte kopyalar
              (devre dışı olarak eklenir). <b>Düzenle</b> ile model adını
              değiştirip etkinleştirin.
            </li>
          </ol>
        </section>

        <section className="ink-panel" style={{ maxWidth: 760 }}>
          <h2>Sık Karşılaşılan Hatalar</h2>
          <table className="info-table">
            <tbody>
              <tr>
                <th>Bağla → “Erişim engellendi: istek geçersiz”</th>
                <td>
                  Google, gönderilen yönlendirme adresini istemcide kayıtlı
                  bulamadı. Console’daki URI ile stüdyonun gönderdiği URI
                  birebir aynı olmalı: tam yol, doğru kanal numarası, port
                  dahil (1. bölüm, 4. adım).
                </td>
              </tr>
              <tr>
                <th>Console URI kaydetmiyor</th>
                <td>
                  HTTP yalnızca localhost için geçerli; LAN IP reddedilir.
                  HTTPS’li gerçek bir alan adı da kullanılabilir.
                </td>
              </tr>
              <tr>
                <th>“Token şifreleme anahtarı yapılandırılmamış / geçersiz”</th>
                <td>
                  Ayarlar → Token Şifreleme Anahtarı alanına geçerli bir Fernet
                  anahtarı girip kaydedin.
                </td>
              </tr>
              <tr>
                <th>Dene → HTTP 404</th>
                <td>
                  API Adresi uç nokta yolu içeriyor (otomatik eklenir) veya
                  adres/tür yanlış. “İstek adresi” önizlemesini kontrol edin.
                </td>
              </tr>
              <tr>
                <th>Onaydan sonra arayüz açılmıyor</th>
                <td>
                  Ayarlar’daki Arayüz Adresi yanlış. Stüdyoyu tarayıcıda
                  açtığınız gerçek adresi yazın.
                </td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </>
  )
}
