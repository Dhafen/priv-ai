# Priv AI: molnbygge och intern TestFlight

Det här projektet byggs på GitHub Actions med macOS 26 och Xcode 26.2.
Windows räcker för att ändra koden och starta byggen. Ingen lokal Mac behövs.
Källkod: https://github.com/Dhafen/priv-ai. Bundle ID: `com.dhafen.privai`.
Appnamnet på telefonen är **Priv AI**.

## Bygga och testa

`Verify iOS and Swiftlet` körs vid relevanta ändringar på `main` och kan även
startas manuellt under Actions. Det hämtar Swiftlet vid revisionen i
`dependencies/swiftlet.json` till `.dependencies/swiftlet`, kör Swiftlets tester,
kontrollerar modellens publicerade metadata och bygger den kompletta iPhone-appen.
GGUF, MLX, Health, Finance, Journal, OCR och Ollama behålls.

Xcode använder den lokala paketreferensen `.dependencies/swiftlet`. En ny klon
förbereds med `python scripts/bootstrap.py`, även på Windows. Paketets källkod
ingår inte i app-repositoryt, men dess exakta Git-revision är låst.

För lokala Xcode-byggen på en Mac: kör bootstrap-kommandot, öppna
`localLLM.xcodeproj`, välj ditt Apple-team och bygg det delade schemat `localLLM`.
Projektet innehåller inget förvalt utvecklarteam.

## Apples engångsinställningar

1. Logga in på https://developer.apple.com/account/ och registrera Bundle ID
   `com.dhafen.privai` på ditt eget team. Aktivera **HealthKit** och
   **Increased Memory Limit**. Behåll båda entitlements i appen.
2. Skapa ett **Apple Distribution**-certifikat med privat nyckel och en
   **App Store Connect**-distributionsprofil för samma Bundle ID. En CSR kan
   skapas på Windows; en lokal Mac krävs inte för detta.
3. Skapa apposten i https://appstoreconnect.apple.com/apps med samma Bundle ID,
   iOS och ett unikt namn, exempelvis `Priv AI Dhafen`. Appikonen på telefonen
   heter fortfarande Priv AI. Skapa ingen offentlig release.
4. Skapa en teamnyckel för App Store Connect API under **Users and Access →
   Integrations → App Store Connect API**. Spara `.p8`-filen säkert. Nyckelns roll
   måste tillåta uppladdning och hantering av TestFlight; provisioning via API
   kräver även behörighet till Certificates, Identifiers & Profiles.
5. Skapa en intern TestFlight-grupp och lägg till ditt Apple-konto som intern
   testare med åtkomst till appen. Välj inte en extern grupp eller offentlig länk.

Webbläsarinloggning ensam ger inte byggservern en signeringsidentitet.
De privata nycklarna och profilen behöver därför sättas upp som GitHub Secrets.
Ingen av dessa filer eller deras innehåll ska klistras in i chatt eller Git.

### Automatisera signeringsinställningarna från Windows

När appidentifieraren och båda capabilities har registrerats, kan
`scripts/apple_setup.py` skapa distributionscertifikat och profil och föra över
privata värden direkt till GitHub Secrets via standard input. Inga privata
värden skrivs till terminalen. Certifikatets privata nyckel cachelagras under
`work/signing/distribution.dpapi`, krypterad med Windows DPAPI för din Windows-
användare. Hela `work/` är undantagen från Git. Använd samma Windows-konto vid
framtida körningar så att certifikatet kan återanvändas.

```powershell
python -m pip install -r scripts/requirements-setup.txt
python scripts/apple_setup.py signing --key-file <lokal-p8-fil> --key-id <key-id> --issuer-id <issuer-id> --team-id <team-id>
python scripts/apple_setup.py connect --key-file <lokal-p8-fil> --key-id <key-id> --issuer-id <issuer-id> --team-id <team-id> --tester-email <ditt-apple-konto>
```

Använd en särskild API-nyckel för Priv AI. En administratörsnyckel behövs om
skriptet även ska skapa certifikat och profiler. Apposten skapas i App Store
Connects webbgränssnitt. Testgruppen heter `Priv AI Personal`; skriptets connect-
steg kan kontrollera att just ditt konto finns i gruppen.

Appens exportdeklaration anger ingen icke undantagen kryptering: nätverkets TLS
och lokal filskyddskryptering använder Apples operativsystem, och Swiftlet
använder CryptoKit för SHA-256-integritet. Om egen kryptering eller andra SDK:er
läggs till, behöver deklarationen omprövas enligt
[Apples dokumentation](https://developer.apple.com/documentation/security/complying-with-encryption-export-regulations).

## Konfiguration i GitHub

Lägg följande **repository secrets** under Settings → Secrets and variables →
Actions. Base64 är transportformat; säkerheten kommer från GitHubs krypterade
Secrets-lagring, inte från Base64.

| Secret | Innehåll |
| --- | --- |
| `ASC_KEY_ID` | App Store Connect API-nyckelns ID |
| `ASC_ISSUER_ID` | Teamnyckelns issuer ID |
| `ASC_PRIVATE_KEY_B64` | Base64 av `.p8`-filen |
| `IOS_DISTRIBUTION_P12_B64` | Base64 av distributionscertifikatet inklusive privat nyckel |
| `IOS_DISTRIBUTION_P12_PASSWORD` | Lösenordet till P12-filen |
| `IOS_PROVISIONING_PROFILE_B64` | Base64 av distributionsprofilen |

Lägg följande **repository variables** på samma sida:

| Variable | Innehåll |
| --- | --- |
| `APPLE_TEAM_ID` | Ditt Apple Developer Team ID |
| `APP_STORE_APP_ID` | Det numeriska Apple-ID:t för den nya apposten |
| `TESTFLIGHT_INTERNAL_GROUP_ID` | ID:t för din interna TestFlight-grupp |

`scripts/prepare-signing.sh` installerar materialet i en tillfällig nyckelring
på byggservern. Det kontrollerar team, Bundle ID, profilens giltighet och båda
entitlements före byggning. Materialet raderas efter körningen. Signerade IPA-
filer publiceras inte som GitHub-releaser eller workflow-artifakter.

## Leverera framtida ändringar

Pusha koden till `main`. När verifieringen är grön, starta **Deliver internal
TestFlight beta** i Actions. Arbetsflödet verifierar konfigurationen, kör tester,
bygger ett signerat arkiv, kontrollerar appens innehåll och laddar upp till Apple.
Byggnumret ökas från det senaste TestFlight-bygget. Versionen finns i Xcode-
projektets `MARKETING_VERSION` och ändras när en ny appversion önskas.

Exporten har `testFlightInternalTestingOnly: true`. Ingen publik App Store-
release eller extern betagranskning begärs. Jobbet väntar på Apples bearbetning
och kontrollerar att bygget är giltigt och finns i den interna testgruppen.
Kontrollera även i App Store Connect att just ditt Apple-konto ingår i gruppen.
Certifikat och profiler behöver förnyas före utgångsdatum.

Använd standardrunnern i det offentliga repositoryt för avgiftsfri körtid.
Inga större betalda runners eller andra betaltjänster behövs. Workflowt lagrar
inga stora byggartifakter; modellvikter hämtas aldrig av signeringsjobbet.

## Installera och testa på iPhone 17 Pro Max

1. Installera Apples **TestFlight** från App Store och logga in på det Apple-
   konto som finns i din interna testgrupp.
2. Öppna Priv AI i TestFlight och välj Installera. Kontrollera versions- och
   byggnummer mot den lyckade workflow-körningen.
3. Ha helst minst **25 GB ledigt** på telefonens interna lagring. Modellpaketet
   är **19 535 719 047 byte**, och appen kräver ytterligare 2 GB marginal.
4. Anslut till Wi-Fi och ström. Öppna **Settings → Experimental Models →
   Qwen 3.6 35B (Experimental) → Download**. Håll appen öppen under hämtningen.
   Tryck Download igen för att återuppta en avbruten hämtning.
5. Välj Qwen-modellen i Chat. Börja med en kort fråga och en ny konversation.
   Qwen QPack är tills vidare endast för Chat. Använd en mindre GGUF-modell för
   Health, Finance och Journal.
6. När modellen är installerad och laddad, slå på flygplansläge och stäng av
   Wi-Fi. Starta en ny lokal chatt och kontrollera att svaret strömmar utan nät.
   Starta även om appen och upprepa för att testa en ny laddning från lagringen.
7. Notera första svarstid, tokens/s, eventuella minnesavbrott och uppvärmning.
   Uppströms prestandasiffror är inga verifierade mätningar av det här bygget.

Modellen ligger i appens lokala `Models`-katalog, normalt under Files → On My
iPhone → Priv AI. Den är inte inbakad i IPA-filen. Ett QPack-paket måste klara
`Qpack.verify` innan appen öppnar `SwiftletSession`. Experterna läses vid behov
med `pread` genom en cache begränsad till **1 GiB**. Den täta kärnan, tokenizern,
konversationstillstånd och Metal-buffertar använder ytterligare minne.

Ett ofullständigt paket eller ett Metal-fel ska visa ett laddningsfel, aldrig
växla till en väg som laddar hela 35B-modellen i RAM. Swiftlets QPack-integritets-
och cachetester täcker motorns logik; faktisk iPhone-körning, jetsam-gräns och
prestanda är **overifierade tills de har testats på telefonen**.

## Verifieringsgränser

En grön Windows-kontroll av YAML, XML eller modellmetadata bevisar inte att appen
bygger. Ett osignerat macOS-bygge bevisar inte signering eller TestFlight. En
lyckad uppladdning bevisar inte att Apple har processat bygget. Ett processat
TestFlight-bygge bevisar inte lyckad modellkörning på en fysisk iPhone.
