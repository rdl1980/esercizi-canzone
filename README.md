# Esercizi canzone – "completa la parola con l'immagine"

Web app che, a partire da una canzone per bambini su YouTube e dal suo testo, produce un esercizio in PDF:
il testo stampato a caratteri grandi in cui alcune parole sono sostituite da un fotogramma del video, con sotto
i trattini (uno per lettera) su cui scrivere la parola a mano.

Come funziona la generazione:

1. scarica il video con `yt-dlp` (mp4 360p, più i sottotitoli italiani se esistono);
2. estrae un fotogramma ogni 2,5 secondi con `ffmpeg` e compone dei fogli di contatto con il tempo stampato;
3. chiede a Claude (API Anthropic, modello con visione) quali parole concrete sostituire e quale fotogramma usare
   per ciascuna, poi gli fa verificare ogni immagine scelta (se non rappresenta la parola ne sceglie un'altra);
4. comprime i ritornelli non lessicali ripetuti ("Olé", "Lallara…") a una riga per blocco;
5. impagina il PDF A4 (titolo in maiuscolo, Arial 28 pt, immagini alte 3 cm, trattini sotto le immagini).

Ogni utente registrato vede solo i propri esercizi.

## App locale per Windows (senza server)

Oltre al sito con login, lo stesso codice si può usare come **app installata sul PC**: nessun server, nessun
account, i PDF finiscono in `Documenti\Esercizi canzone`. È la soluzione più semplice per un uso in famiglia.

**Installazione (per chi la usa)**

1. Scarica `EserciziCanzone-win64.zip` dall'ultima release su <https://github.com/rdl1980/esercizi-canzone/releases>.
2. Estrai lo zip in una cartella qualsiasi (per esempio `C:\EserciziCanzone`, non in Programmi) e avvia `EserciziCanzone.exe`.
   Windows SmartScreen può mostrare "PC protetto da Windows": clicca *Ulteriori informazioni* e poi *Esegui comunque*.
3. Al primo avvio l'app scarica da sola ffmpeg e yt-dlp (circa 130 MB, una volta sola) e apre il sito nel browser.
4. Vai in **Impostazioni**, incolla la chiave API Anthropic e premi *Salva e prova la chiave*.
5. Lascia aperta la piccola finestra dell'app mentre la usi; per chiudere premi *Esci*.

A ogni avvio l'app controlla su GitHub se c'è una versione nuova: se sì la scarica, la installa e si riavvia da sola.
yt-dlp si aggiorna da solo una volta al giorno (è il pezzo che YouTube rompe più spesso).
Dati, log e strumenti stanno in `%LOCALAPPDATA%\EserciziCanzone` (`avvio.log` per capire cosa è successo).

**Pubblicare una nuova versione (per chi sviluppa)**

```bash
.venv\Scripts\python desktop\rilascio.py 1.0.2 --note "Cosa è cambiato"
```

Lo script aggiorna `app/versione.py`, costruisce l'exe con PyInstaller (`desktop/EserciziCanzone.spec`), crea
`dist/EserciziCanzone-win64.zip`, fa commit e tag `v1.0.2`, e pubblica la release su GitHub con lo zip allegato
(serve `gh auth login`). Le app installate si aggiornano al loro avvio successivo. Senza versione
(`python desktop/rilascio.py`) fa solo la build. Per provare l'app dai sorgenti: `.venv\Scripts\python desktop\avvio.py`.

## Requisiti

* Python 3.11 o superiore (sviluppato con 3.13)
* `ffmpeg` nel PATH
* `yt-dlp` (installato automaticamente con i requisiti Python; va bene anche quello di sistema)
* una chiave API Anthropic
* facoltativo: `node` (o `deno`), usato solo per il secondo tentativo di download se il client "android" di YouTube fallisce
* facoltativo: Arial (su Windows c'è già; su Linux viene usata Liberation Sans o DejaVu, altrimenti Helvetica)

Oppure Docker: l'immagine include ffmpeg, yt-dlp e i font.

## Installazione e avvio in locale (Windows, macOS, Linux)

```bash
cd webapp
python -m venv .venv
# Windows:
.venv\Scripts\pip install -r requirements.txt
# macOS / Linux:
# .venv/bin/pip install -r requirements.txt
```

Crea il file `.env` copiando `.env.example` e inserisci la chiave:

```
ANTHROPIC_API_KEY=sk-ant-...
```

Avvia il server:

```bash
# Windows
.venv\Scripts\python run.py
# macOS / Linux
# .venv/bin/python run.py
```

Apri <http://127.0.0.1:8000>, registrati e crea il primo esercizio.
Per renderlo raggiungibile da altri computer della rete locale: `HOST=0.0.0.0` (variabile d'ambiente) prima di `run.py`.

I dati (database SQLite, video scaricati, immagini e PDF) finiscono nella cartella `data/`.

## Avvio con Docker

```bash
cd webapp
cp .env.example .env     # e inserisci ANTHROPIC_API_KEY
docker compose up --build -d
```

Il sito è su <http://localhost:8000>; i dati restano in `./data` sul computer che ospita il container.

## Uso

1. **Registrati** con email e password (minimo 8 caratteri), poi **Accedi**.
2. **Nuovo esercizio**: incolla il link YouTube e il testo della canzone (una riga per verso, riga vuota tra le strofe:
   serve a riconoscere il ritornello). Scegli:
   * il numero di parole da sostituire (0 = decide l'AI: circa 5-6 per una strofa, 10-12 per il testo intero);
   * il titolo (se vuoto viene usato il titolo del video);
   * "Testo completo" oppure "Prima strofa + ritornello".
3. La generazione dura 1-2 minuti: la pagina mostra la fase in corso (in coda, scarico il video, estraggo i fotogrammi,
   scelgo le parole con l'AI, verifico le immagini, impagino il PDF) e, in caso di errore, il motivo.
4. Quando è pronto: **Scarica il PDF**, guarda l'anteprima della prima pagina, **Rigenera** con altri parametri
   (il video e i fotogrammi già scaricati vengono riutilizzati) oppure **Elimina**.

### Errori mostrati nell'interfaccia

Link non YouTube, video non disponibile/privato/con restrizioni, video troppo lungo (predefinito 15 minuti),
testo troppo corto o troppo lungo, numero di parole fuori dall'intervallo 0-30, email già registrata,
password troppo corta, chiave API mancante o non valida, limite di richieste raggiunto.

## API REST

Tutte le risposte sono JSON; gli errori hanno la forma `{"detail": "messaggio in italiano"}`.
La sessione è un cookie firmato (`sessione`), impostato da login e registrazione.
Documentazione interattiva: <http://127.0.0.1:8000/api/docs>.

| Metodo | Percorso | Descrizione |
|---|---|---|
| POST | `/api/auth/registrazione` | `{"email", "password"}` → 201, imposta il cookie |
| POST | `/api/auth/login` | `{"email", "password"}` → 200, imposta il cookie |
| POST | `/api/auth/logout` | cancella il cookie |
| GET | `/api/auth/me` | utente corrente |
| GET | `/api/esercizi` | elenco dei propri esercizi |
| POST | `/api/esercizi` | `{"url", "testo", "n_parole", "titolo", "modalita"}` → 202, esercizio in coda |
| GET | `/api/esercizi/{id}` | dettaglio con `stato` (`coda`, `in_lavorazione`, `pronto`, `errore`), `fase`, `progresso`, `errore` |
| POST | `/api/esercizi/{id}/rigenera` | stessi campi (tutti facoltativi) → 202 |
| DELETE | `/api/esercizi/{id}` | elimina esercizio e file |
| GET | `/api/esercizi/{id}/pdf` | scarica il PDF (`/pdf/apri` lo apre nel browser) |
| GET | `/api/esercizi/{id}/anteprima.png` | prima pagina in PNG |
| GET | `/api/esercizi/{id}/esercizio.json` | formato interno (righe di testo e oggetti `{"parola", "img"}`) |

Il frontend interroga `GET /api/esercizi/{id}` ogni 3 secondi finché lo stato è `coda` o `in_lavorazione`.

## Struttura del progetto

```
webapp/
  app/
    main.py            API REST e pagine HTML (FastAPI + Jinja2)
    auth.py            bcrypt + cookie di sessione firmato
    db.py              SQLite (tabelle utenti ed esercizi)
    jobs.py            coda in memoria con un thread lavoratore
    config.py          variabili d'ambiente
    pipeline/
      youtube.py       controllo link, info e download con yt-dlp
      frames.py        fotogrammi con ffmpeg (-ss prima di -i) e fogli di contatto con Pillow
      lyrics.py        blocchi, prima strofa + ritornello, compressione dei vocalizzi
      ai.py            chiamate a Claude: scelta parole/fotogrammi e verifica
      layout.py        costruisce esercizio.json (formato di tools/crea_esercizio.py)
      pdf.py           impaginazione con reportlab + anteprima con PyMuPDF
      run.py           orchestrazione delle fasi
    templates/, static/
    versione.py        versione dell'app e repository GitHub delle release
  desktop/
    avvio.py           launcher dell'app locale (finestra di stato, server su 127.0.0.1, browser)
    aggiornamenti.py   controllo e installazione degli aggiornamenti da GitHub Releases
    strumenti.py       download di ffmpeg e yt-dlp, yt-dlp -U
    rilascio.py        build PyInstaller + zip + release su GitHub
    EserciziCanzone.spec
  data/                database e cartelle data/esercizi/<id>/ (video, frames, fogli, immagini, esercizio.json, esercizio.pdf, log.txt)
```

In modalità locale (`MODALITA_LOCALE=1`, impostata dal launcher) non c'è login: un solo utente, chiave API e modello
nella pagina Impostazioni (salvati in `impostazioni.json` dentro la cartella dati), PDF copiati anche in `ESPORTA_PDF_DIR`.

Il file `data/esercizi/<id>/esercizio.json` ha lo stesso formato usato da `tools/crea_esercizio.py`, quindi
si può ottenere anche il `.docx` con: `python tools/crea_esercizio.py data/esercizi/<id>/esercizio.json uscita.docx`.

## Variabili d'ambiente

Vedi `.env.example`: `ANTHROPIC_API_KEY` (obbligatoria), `CLAUDE_MODEL` (predefinito `claude-sonnet-5-5`; si può usare
`claude-opus-5-5` per scelte più accurate a costo maggiore), `SECRET_KEY`, `COOKIE_SICURO`, `DATA_DIR`,
`INTERVALLO_FOTOGRAMMI`, `DURATA_MAX_VIDEO`, `YTDLP_REMOTE_COMPONENTS`, `FFMPEG_BIN`, `YTDLP_BIN`.

## Note tecniche

* `yt-dlp` viene lanciato con `--extractor-args youtube:player_client=android -f 18`: senza un runtime JavaScript
  il client standard fallisce con "video not available". Se anche questo fallisce e `YTDLP_REMOTE_COMPONENTS=true`,
  viene fatto un secondo tentativo con `--remote-components ejs:github` (richiede node o deno).
* I fotogrammi sono estratti uno per uno con `ffmpeg -ss T -i video -frames:v 1`: il filtro `fps=` produceva
  etichette temporali sbagliate. Le etichette sui fogli di contatto sono scritte con Pillow perché `drawtext`
  richiede fontconfig.
* Il PDF è generato direttamente con reportlab, senza Word o LibreOffice. Il titolo va a capo se non entra nella
  pagina e, oltre due righe, viene ridotto di corpo; non viene mai tagliato.
* Se il titolo è lasciato vuoto viene usato il nome della canzone ricavato dal titolo YouTube, ripulito da canale,
  parentesi e suffissi ("Piccolo Coro dell'Antoniano - Il coccodrillo come fa? (cartoon) - 36° Zecchino d'Oro"
  diventa "Il coccodrillo come fa?"). Il titolo scritto dall'utente viene usato così com'è.
* Se il server viene riavviato durante una generazione, l'esercizio passa in errore e basta premere **Rigenera**.
* Il log di ogni generazione è in `data/esercizi/<id>/log.txt`.
