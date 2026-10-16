# CasaOS Kurulumu (Raspberry Pi 5)

Bu klasör, uygulamayı CasaOS'a eklemek için hazırlanmış dosyaları içerir.

## Kurulum yolları

| Yol | Compose dosyası | Ne zaman? |
|---|---|---|
| **A — Harici PostgreSQL (önerilen)** | `docker-compose.external-db.yml` | Pi'deki mevcut PostgreSQL sunucusunu kullanır; ekstra RAM tüketmez |
| B — Paket içi PostgreSQL | `docker-compose.casaos.yml` | Mevcut sunucuya hiç dokunmak istemezseniz; kendi izole `postgres:17` konteynerini kurar |

Her iki yolda da ortak ön koşul: uygulama imajlarının Pi üzerinde bir kez
derlenmesi (adım 3).

> **Şifre kuralı (pazarlık dışı):** Her kurulum **taze üretilmiş** bir şifre
> kullanır. Daha önce paylaşılmış, sohbete yapıştırılmış veya eski
> projelerde kullanılmış şifreler asla kullanılmaz. Şifre üretimi:
>
> ```bash
> openssl rand -hex 24
> ```

---

## 1. Kaynağı Pi'ye kopyalayın

`autoshorts-studio-src.zip` dosyasını (proje kökünde üretilir) Pi'ye atın:

- **Kolay yol:** CasaOS → Dosyalar uygulaması → `~/` veya `/DATA` içine yükleyin.
- **Terminal yolu (bilgisayarınızdan):**

  ```bash
  scp autoshorts-studio-src.zip murat@192.168.2.170:~/
  ssh murat@192.168.2.170
  unzip autoshorts-studio-src.zip -d ~/autoshorts-studio
  ```

## 2. Veritabanı hazırlığı (yalnızca Yol A)

Pi'de, yönetici erişimiyle (şifre sorulur; şifreyi sohbete/notlara
yazmayın):

```bash
psql -h 192.168.2.170 -p 5432 -U muratcihanyandi -d postgres
```

```sql
-- Taze ve güçlü bir şifre üretin (openssl rand -hex 24) ve buraya yazın:
CREATE ROLE autoshorts_app LOGIN PASSWORD 'YENI_TAZE_SIFRE_BURAYA';
CREATE DATABASE autoshorts_studio OWNER autoshorts_app;
\q
```

Notlar:

- Mevcut `muratcihanyandi` rolünü uygulamada **kullanmayın**; o rol tüm
  sunucuda yetkilidir. `autoshorts_app` yalnızca kendi veritabanına erişir.
- Yol B (paket içi PostgreSQL) seçilirse bu adım atlanır; şifre doğrudan
  compose dosyasına yazılır.

## 3. İmajları derleyin (tek sefer)

```bash
cd ~/autoshorts-studio
sh deploy/casaos/build-on-pi.sh
```

İlk derleme 5–10 dakika sürer (Python/Node imaj indirmeleri + pip/npm).
Bittiğinde `autoshorts-studio-backend:local` ve
`autoshorts-studio-frontend:local` imajları hazır olur.

## 4. CasaOS'a ekleyin

Hazır (şifresi doldurulmuş) dosya: `deploy/casaos/docker-compose.generated.yml`
— bu dosya repoya girmez (gitignore'lu). İçeriğini kopyalayın:

1. CasaOS → **Uygulama Mağazası** → *Install from custom compose*
   (sürüme göre: **Docker** → **+** / "Compose dosyasından kur").
2. `docker-compose.generated.yml` içeriğini yapıştırın → kurun.

Şablonu elle doldurmak isterseniz: `docker-compose.external-db.yml` içindeki
`DB_SIFRE_BURAYA` yazan tek yeri şifreyle değiştirin.

Proje adı `autoshorts-studio` olduğundan CasaOS, aynı yığını ikinci kez
oluşturmaz.

## 5. Doğrulayın

```bash
curl http://localhost:8080/api/health
# {"status":"ok","service":"autoshorts-backend","version":"0.1.0"}

curl http://localhost:8080/api/health/ready
# {"status":"ok","database":"reachable"}
```

`database: reachable` görüyorsanız; uygulama veritabanına bağlanmış ve
migration'lar uygulanmış demektir. Tarayıcıdan: `http://192.168.2.170:8080/`

Ağdaki başka bir cihazdan erişilemiyorsa Pi güvenlik duvarını kontrol edin.

## Güncelleme

```bash
cd ~/autoshorts-studio
# yeni kaynak zip'ini açın (üzerine yazın), sonra:
sh deploy/casaos/build-on-pi.sh
```

CasaOS'tan yığını yeniden başlatın. Migration'lar backend başlarken
otomatik uygulanır; `pgdata` verisi korunur.

## Yedekleme (Yol A)

```bash
# Pi üzerinde:
PGPASSWORD='<autoshorts_app şifresi>' pg_dump \
  -h 192.168.2.170 -U autoshorts_app autoshorts_studio \
  > ~/autoshorts_yedek_$(date +%F).sql
```

## Sorun giderme

| Belirti | Çözüm |
|---|---|
| `pull access denied` / imaj bulunamadı | `build-on-pi.sh` çalıştırılmamış; 3. adımı uygulayın |
| `health/ready` → `not_configured` | `DATABASE_URL` boş kalmış; compose'daki satırı kontrol edin |
| `health/ready` → `unreachable` | Şifre/rol yanlış veya veritabanı erişilemiyor; 2. adımı ve şifreyi kontrol edin |
| `password authentication failed` | Şifre URL içinde özel karakter içeriyor olabilir; yalnızca harf/rakam kullanın |
| 8080 dolu | Compose'daki `"8080:80"` satırında soldaki portu değiştirin |
| Migration hatası | `docker logs autoshorts-backend` — JSON log satırları (şifreler maskeli) |

## Güvenlik hatırlatmaları

- Şifreleri sohbete, ekran görüntüsüne, nota veya repoya **yazmayın**;
  sızma şüphesinde derhal döndürün (rotate).
- Paylaşılan PostgreSQL sunucusunun yönetici şifresini döndürmeniz
  gerekirse önce bağımlı servisleri (n8n, affine vb.) listeleyin — kırılma
  etkisi yüksektir.
- Dağıtım kapıları: `docs/SECURITY.md` (G1: GitHub token iptali,
  G2: şifre döndürme) teyit edilmeden dış entegrasyonları (YouTube, LLM)
  devreye almayın.
