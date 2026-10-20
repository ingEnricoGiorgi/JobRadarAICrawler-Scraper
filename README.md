# JobRadarAICrawler-Scraper

Ricerca geografica italiana con GUI PySide6, archivio territoriale offline e SQLite
tramite SQLAlchemy. Il repository iniziale conteneva soltanto licenza e `.gitignore`:
questa implementazione costituisce la base geografica, senza moduli preesistenti da
migrare. L'analisi CV e le altre funzionalità del documento allegato non sono incluse
in questa estensione geografica.

## Avvio su Windows

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[test]"
.venv\Scripts\python.exe -m jobradar
```

In questa copia le dipendenze sono già installate nella `.venv`.
Il database viene creato in `%LOCALAPPDATA%\JobRadarAICrawler\jobradar.sqlite3`.
La GUI funziona senza servizi AI, account o accesso Internet.

## Utilizzo dei filtri

1. Selezionare un comune dall'autocompletamento (nome, provincia, codice ISTAT),
   una provincia o una regione e premere **Aggiungi area / esclusione**. Ripetere per
   combinare più aree. I comuni omonimi richiedono una provincia esplicita.
2. Aggiungere uno o più raggi scegliendo un comune e i chilometri. Per un indirizzo
   approssimativo inserire etichetta e coordinate WGS84 note: non vengono inventate
   coordinate né inviati indirizzi a servizi esterni. Senza coordinate esplicite si
   usa il punto municipale del comune, come segnalato dalla GUI.
3. In alternativa selezionare **Tutta Italia** oppure **Esclusivamente remoto**.
4. Impostare modalità ammesse ed eventuali esclusioni. Salvare il profilo con un
   nome; sono supportati più profili indipendenti e modificabili.
5. Importare annunci JSON, interrogare una fonte configurata o filtrare l'archivio.
   La tabella mostra anche gli scarti con la motivazione; doppio clic per i dettagli.

Le aree si combinano in OR. Le esclusioni di comune/provincia prevalgono anche su
Italia e remoto. Remoto completo verificato è un'alternativa alle aree fisiche;
ibrido e presenza devono rientrare nelle aree. **Solo remoto** esclude ogni altra
modalità. Modalità sconosciuta non viene mai trasformata in remoto. L'opzione per
località non specificate non ammette località ambigue. Una località estera non
rientra nella ricerca nazionale; province/regioni dichiarate senza comune possono
essere filtrate con i relativi codici, senza inventare coordinate.

Le distanze Haversine sono in linea d'aria, **non percorsi stradali**. Per più raggi
si conserva la distanza dal riferimento più vicino; l'inclusione viene verificata
separatamente rispetto a ciascun raggio. Informazioni mancanti rimangono `NULL`.

L'archivio include tutti i 7.894 comuni ISTAT: coordinate integrative verificate
per 7.865 comuni, mancanti per 29. Provenienza e limiti in
[SOURCES.md](jobradar/data/SOURCES.md), hash e data in `jobradar/data/manifest.json`.

## Annunci e accessibilità del remoto

L'importazione richiede una lista JSON con campi `source`, `url`, `title`, eventuale
`original_location`, `work_mode` (`remote`, `hybrid`, `onsite`, `unknown`). Tutti i
campi del dataclass `Listing` sono accettati. Nomi dei comuni risolti esattamente;
per omonimie usare `Nome (XX)` o `municipality_code` ISTAT. Località estere devono
avere `country_code` della fonte. Non si estraggono città da sottostringhe ambigue.

Per verificare il remoto, l'adattatore può fornire `remote_scope` strutturato con
`allowed_countries`, `excluded_countries`, `worldwide`, `evidence`, `original_text`.
Si richiedono evidenze esplicite nella fonte. Esempio di schema (non un annuncio):

```json
{"allowed_countries": ["IT", "FR"], "excluded_countries": [],
 "evidence": "Campo applicantLocationRequirements della fonte originale",
 "original_text": "Testo originale della restrizione"}
```

Se l'Italia è esclusa il remoto viene scartato. Senza ambito o evidenza, l'idoneità
rimane sconosciuta e viene scartata nella ricerca remota. `EU`, `Europe` o un ufficio
in Italia non costituiscono automaticamente prova. Gli adattatori specifici devono
interpretare restrizioni testuali, residenza, fuso e vincoli contrattuali prima di
emettere un esito verificato. L'applicazione non verifica il diritto individuale
al lavoro. Il contratto permette anche `remote_italy_eligible` e
`eligibility_evidence` già verificati da un adattatore della fonte.

## Fonti e crawler

Non sono preconfigurati portali commerciali. **Configura fonti JSON** carica una
lista di configurazioni per API HTTPS che restituiscono il formato `Listing`.
Esempio di sola configurazione, da sostituire con un endpoint reale autorizzato:

```json
[{"name": "Nome fonte", "endpoint": "https://example.invalid/jobs",
  "results_key": "jobs",
  "parameters": {
    "city": {"municipality_istat": "{value}"},
    "province": {"province": "{value}"},
    "region": {"region_istat": "{value}"},
    "radius": {"lat": "{latitude}", "lon": "{longitude}", "km": "{radius_km}"},
    "national": {"country": "IT"},
    "remote": {"country": "IT", "work_mode": "remote"}
  }}]
```

La configurazione deve dichiarare soltanto filtri effettivamente supportati dalla
fonte: città con codice ISTAT comunale, provincia con sigla, regione con codice
ISTAT. Se un filtro manca, il crawler raccoglie un insieme più ampio senza quel
vincolo e applica sempre il secondo filtro locale. Le query delle aree sono separate
per non trasformare un OR in un AND; i risultati vengono deduplicati per fonte/URL.
Il connettore JSON legge una risposta per query; per paginazione, autenticazione,
codifiche proprietarie e HTML implementare un adattatore `Source` in
`jobradar/crawlers.py`, che esegua il mapping e rispetti i vincoli della fonte.
Gli errori di una fonte non interrompono le altre. Nessun aggiramento di restrizioni.
La GUI esegue i crawler in un thread di lavoro; le fonti caricate valgono per la
sessione, mentre i profili geografici sono persistenti.

SQLite conserva località originale, normalizzazione, coordinate, modalità,
restrizioni ed evidenza; ogni valutazione conserva snapshot del filtro, esito,
motivo, distanza e riferimento. Le distanze non diventano un attributo immutabile
dell'annuncio: cambiano con il profilo. Anche gli annunci scartati restano archiviati.
Schema versionato con migrazioni e indici; nessun dato dimostrativo in produzione.

## Verifica e aggiornamento dati

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe tools\update_geodata.py
```

I test usano fixture esplicite e Qt offscreen. Coprono raggio, città, provincia,
regione, Italia, remoto, unioni, esclusioni, omonimie, dati mancanti, persistenza,
GUI e doppio filtro crawler. I test HTTP usano risposte simulate, non portali live.
