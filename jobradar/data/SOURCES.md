# Provenienza dell'archivio offline

Le denominazioni, i codici comunali, le province e le regioni provengono dall'elenco
ufficiale ISTAT, aggiornamento dichiarato al 21 febbraio 2026, scaricato il 21 ottobre
2026 (Europe/Rome). Il file comprende 7.894 comuni e la ricodifica della Sardegna.

- Elenco: https://www.istat.it/storage/codici-unita-amministrative/Elenco-comuni-italiani.xlsx
- Documentazione: https://www.istat.it/classificazione/codici-dei-comuni-delle-province-e-delle-regioni/
- Condizioni ISTAT: https://www.istat.it/note-legali/

Le coordinate sono una fonte integrativa distinta dall'elenco ufficiale:
Open Data Sicilia, dataset `comuni-italiani`, `coordinate.csv`. Il progetto descrive
questi punti come riferiti al municipio, EPSG:4326. Non sono coordinate di indirizzi
né centroidi calcolati dall'applicazione. Attribuzione: Comunità Open Data Sicilia.

- Dati: https://github.com/opendatasicilia/comuni-italiani
- Definizioni: https://github.com/opendatasicilia/comuni-italiani/blob/main/dati/README.md

L'importatore associa un punto soltanto quando coincidono codice corrente o storico
ufficiale ISTAT e denominazione ufficiale (italiana o bilingue). Nessun abbinamento
approssimato. I 29 comuni senza associazione verificata mantengono coordinate NULL.
Sono disponibili coordinate per 7.865 comuni. La precisione è municipale, non civica;
una distanza fra punti comunali è una stima in linea d'aria.

`manifest.json` conserva URL, data di acquisizione, SHA-256 delle fonti e copertura.
`tools/update_geodata.py` ricostruisce l'archivio con HTTPS verificato tramite i
certificati di sistema. Il programma desktop non effettua download all'avvio.
