"""Offline-capable PySide6 geographic search and profile management."""
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QCompleter, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .crawlers import crawl
from .geo import Gazetteer, GeoProfile, Listing, Radius, evaluate, normalize_listing
from .storage import Store
from .sources import JsonApiSource, parse_listing


class CrawlWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, sources, profile, gazetteer, store):
        super().__init__()
        self.args = sources, profile, gazetteer, store

    def run(self):
        try:
            self.completed.emit(crawl(*self.args))
        except Exception as exc:
            self.failed.emit(f"Ricerca fallita: {type(exc).__name__}")


class MainWindow(QMainWindow):
    def __init__(self, store, gazetteer, sources=()):
        super().__init__()
        self.store, self.gazetteer, self.sources = store, gazetteer, sources
        self.worker = None
        self.setWindowTitle("JobRadarAICrawler — Filtri geografici")
        self.resize(1280, 850)
        self.radii = []
        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)
        profiles_row = QHBoxLayout()
        self.profile_names = QComboBox()
        self.profile_names.setEditable(True)
        self.profile_names.setPlaceholderText("Nome profilo geografico")
        profiles_row.addWidget(self.profile_names, 1)
        for label, action in (("Carica profilo", self.load_profile), ("Salva profilo", self.save_profile)):
            button = QPushButton(label)
            button.clicked.connect(action)
            profiles_row.addWidget(button)
        layout.addLayout(profiles_row)
        split = QSplitter()
        layout.addWidget(split, 1)
        panel = QWidget()
        controls = QVBoxLayout(panel)
        split.addWidget(panel)
        controls.addWidget(QLabel("Aree in unione (OR). Le esclusioni hanno precedenza."))
        self.kind = QComboBox()
        self.kind.addItems(["Comune", "Provincia", "Regione", "Escludi comune", "Escludi provincia"])
        controls.addWidget(self.kind)
        self.area = QComboBox()
        self.area.setEditable(True)
        self.area.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.area.setMinimumContentsLength(24)
        controls.addWidget(self.area)
        self.kind.currentIndexChanged.connect(self.update_area_choices)
        self.update_area_choices()
        add = QPushButton("Aggiungi area / esclusione")
        add.clicked.connect(self.add_area)
        controls.addWidget(add)
        self.areas = QListWidget()
        controls.addWidget(self.areas)
        remove = QPushButton("Rimuovi elemento selezionato")
        remove.clicked.connect(self.remove_area)
        controls.addWidget(remove)
        form = QFormLayout()
        self.center = QComboBox()
        self.center.setEditable(True)
        self.fill_cities(self.center)
        self.center.setCurrentIndex(-1)
        form.addRow("Centro del raggio (comune)", self.center)
        self.address = QLineEdit()
        self.address.setPlaceholderText("Etichetta indirizzo approssimativo (facoltativa)")
        form.addRow("Indirizzo / riferimento", self.address)
        self.lat = QLineEdit()
        self.lon = QLineEdit()
        self.lat.setPlaceholderText("Latitudine WGS84")
        self.lon.setPlaceholderText("Longitudine WGS84")
        form.addRow("Coordinate indirizzo", self.lat)
        form.addRow("", self.lon)
        self.km = QDoubleSpinBox()
        self.km.setRange(.1, 20000)
        self.km.setValue(25)
        self.km.setSuffix(" km")
        form.addRow("Raggio", self.km)
        controls.addLayout(form)
        note = QLabel("Distanza Haversine in linea d'aria, non percorso stradale.\n"
                      "Per un indirizzo inserire coordinate note; senza coordinate si usa\n"
                      "il punto municipale del comune scelto, non la posizione dell'indirizzo.")
        note.setWordWrap(True)
        controls.addWidget(note)
        add_radius = QPushButton("Aggiungi raggio")
        add_radius.clicked.connect(self.add_radius)
        controls.addWidget(add_radius)
        self.flags = {}
        for name, label, default in [
            ("national", "Tutta Italia", False),
            ("remote_only", "Esclusivamente remoto completo accessibile dall'Italia", False),
            ("include_remote", "Includi remoto completo verificato (anche fuori dalle aree)", True),
            ("include_hybrid", "Includi ibrido nelle aree selezionate", True),
            ("include_onsite", "Includi presenza nelle aree selezionate", True),
            ("include_unknown_mode", "Includi modalità lavorativa non specificata", False),
            ("include_unknown_location", "Includi località non specificata (non le ambigue)", False),
        ]:
            box = QCheckBox(label)
            box.setChecked(default)
            self.flags[name] = box
            controls.addWidget(box)
        self.flags["remote_only"].toggled.connect(self.remote_toggled)
        results = QWidget()
        result_layout = QVBoxLayout(results)
        split.addWidget(results)
        buttons = QHBoxLayout()
        for label, action in (("Filtra archivio", self.refresh), ("Importa annunci JSON", self.import_json)):
            button = QPushButton(label)
            button.clicked.connect(action)
            buttons.addWidget(button)
        self.search_button = QPushButton("Avvia crawler")
        self.search_button.clicked.connect(self.start_crawl)
        buttons.addWidget(self.search_button)
        configure = QPushButton("Configura fonti JSON")
        configure.clicked.connect(self.configure_sources)
        buttons.addWidget(configure)
        result_layout.addLayout(buttons)
        self.status = QLabel("Nessuna fonte crawler configurata." if not sources else f"Fonti configurate: {len(sources)}")
        self.status.setWordWrap(True)
        result_layout.addWidget(self.status)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(["Titolo", "Località originale", "Comune", "Provincia", "Regione",
                                             "Modalità", "km in linea d'aria", "Esito", "Motivo"])
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self.show_detail)
        result_layout.addWidget(self.table)
        result_layout.addWidget(QLabel("Doppio clic per coordinate, restrizioni remote, riferimento e URL originale."))
        split.setSizes([460, 820])
        self.reload_names()

    def remote_toggled(self, checked):
        if checked:
            self.flags["include_remote"].setChecked(True)

    def fill_cities(self, combo):
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(24)
        for label, code in sorted(self.gazetteer.labels.items()):
            combo.addItem(label, code)
        combo.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        combo.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        combo.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)

    def update_area_choices(self):
        self.area.clear()
        kind = self.kind.currentText()
        if "comune" in kind.casefold():
            self.fill_cities(self.area)
        else:
            province = "provincia" in kind.casefold()
            entries = {(c.province_code, c.province) if province else (c.region_code, c.region)
                       for c in self.gazetteer.cities.values()}
            for code, name in sorted(entries, key=lambda p: p[1]):
                self.area.addItem(f"{name} [{code}]", code)
            self.area.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            self.area.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.area.setCurrentIndex(-1)

    def selected_code(self, combo, city=False):
        if city:
            candidates = self.gazetteer.resolve(combo.currentText())
            if len(candidates) != 1:
                raise ValueError("Selezionare un comune univoco con provincia dall'autocompletamento")
            return candidates[0].code
        index = combo.findText(combo.currentText(), Qt.MatchFlag.MatchExactly)
        if index < 0:
            raise ValueError("Selezionare una voce dall'elenco")
        return combo.itemData(index)

    def append_area(self, field, code, label):
        for i in range(self.areas.count()):
            if self.areas.item(i).data(Qt.ItemDataRole.UserRole) == (field, code):
                return
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, (field, code))
        self.areas.addItem(item)

    def add_area(self):
        try:
            fields = ["cities", "provinces", "regions", "excluded_cities", "excluded_provinces"]
            field = fields[self.kind.currentIndex()]
            code = self.selected_code(self.area, "cities" in field)
            self.append_area(field, code, f"{self.kind.currentText()}: {self.area.currentText()}")
        except ValueError as exc:
            self.error(str(exc))

    def add_radius(self):
        try:
            if self.lat.text().strip() or self.lon.text().strip():
                if not self.address.text().strip():
                    raise ValueError("Dare un'etichetta al riferimento con coordinate")
                radius = Radius(self.address.text().strip(), float(self.lat.text().replace(',', '.')),
                                float(self.lon.text().replace(',', '.')), self.km.value())
            else:
                city = self.gazetteer.cities[self.selected_code(self.center, True)]
                if city.latitude is None:
                    raise ValueError("Coordinate non disponibili per questo comune")
                radius = Radius(city.label + " — punto municipale", city.latitude, city.longitude, self.km.value(), city.code)
            index = len(self.radii)
            self.radii.append(radius)
            self.append_area("radii", index, f"Raggio: {radius.label}, {radius.km:g} km")
        except ValueError as exc:
            self.error(str(exc))

    def remove_area(self):
        self.areas.takeItem(self.areas.currentRow())

    def profile(self):
        profile = GeoProfile(**{name: box.isChecked() for name, box in self.flags.items()})
        for i in range(self.areas.count()):
            field, code = self.areas.item(i).data(Qt.ItemDataRole.UserRole)
            getattr(profile, field).append(self.radii[code] if field == "radii" else code)
        profile.validate(self.gazetteer)
        return profile

    def reload_names(self, selected=""):
        self.profile_names.clear()
        self.profile_names.addItems(self.store.profiles())
        self.profile_names.setEditText(selected)

    def save_profile(self):
        try:
            name = self.profile_names.currentText().strip()
            self.store.save_profile(name, self.profile())
            self.reload_names(name)
            self.status.setText(f"Profilo salvato: {name}")
        except ValueError as exc:
            self.error(str(exc))

    def load_profile(self):
        profile = self.store.profiles().get(self.profile_names.currentText())
        if profile is None:
            self.error("Profilo non trovato")
            return
        self.areas.clear()
        self.radii = list(profile.radii)
        for name, box in self.flags.items():
            box.setChecked(getattr(profile, name))
        for field in ("cities", "provinces", "regions", "excluded_cities", "excluded_provinces"):
            for code in getattr(profile, field):
                city = self.gazetteer.cities.get(code)
                label = city.label if city else code
                self.append_area(field, code, f"{field}: {label}")
        for index, radius in enumerate(self.radii):
            self.append_area("radii", index, f"Raggio: {radius.label}, {radius.km:g} km")
        self.refresh()

    def refresh(self):
        try:
            profile = self.profile()
        except ValueError as exc:
            self.error(str(exc))
            return
        jobs = self.store.listings()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(jobs))
        accepted = 0
        for row, job in enumerate(jobs):
            decision = evaluate(job, profile)
            accepted += decision.accepted
            values = [job.title, job.original_location, job.municipality, job.province, job.region,
                      job.work_mode, f"{decision.distance_km:.1f}" if decision.distance_km is not None else None,
                      "Incluso" if decision.accepted else "Escluso", decision.reason]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value) if value is not None else "Non disponibile")
                item.setData(Qt.ItemDataRole.UserRole, (job, decision))
                self.table.setItem(row, column, item)
        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        self.status.setText(f"{len(jobs)} annunci archiviati; {accepted} inclusi, {len(jobs)-accepted} esclusi. Nessun dato dimostrativo.")

    def import_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "Importa annunci strutturati", "", "JSON (*.json)")
        if not path:
            return
        try:
            profile = self.profile()
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError("Il file deve contenere una lista di annunci")
            jobs = [normalize_listing(parse_listing(r), self.gazetteer) for r in data]
            for job in jobs:
                self.store.save_listing(job, profile, evaluate(job, profile))
            self.refresh()
        except (ValueError, TypeError, OSError) as exc:
            self.error(f"Importazione non riuscita: {exc}")

    def configure_sources(self):
        path, _ = QFileDialog.getOpenFileName(self, "Carica configurazione fonti JSON", "", "JSON (*.json)")
        if path:
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                self.sources = [JsonApiSource(**config) for config in data]
                self.status.setText(f"Fonti configurate: {len(self.sources)}")
            except (ValueError, TypeError, OSError) as exc:
                self.error(f"Configurazione non valida: {exc}")

    def start_crawl(self):
        if not self.sources:
            self.error("Nessuna fonte configurata. Collegare un adattatore Source; è disponibile l'importazione JSON.")
            return
        try:
            profile = self.profile()
        except ValueError as exc:
            self.error(str(exc))
            return
        self.search_button.setEnabled(False)
        self.worker = CrawlWorker(self.sources, profile, self.gazetteer, self.store)
        self.worker.completed.connect(self.crawl_completed)
        self.worker.failed.connect(self.error)
        self.worker.finished.connect(lambda: self.search_button.setEnabled(True))
        self.worker.start()

    def crawl_completed(self, report):
        self.refresh()
        self.status.setText(f"Analizzati: {report.analyzed}; inclusi: {report.accepted}; esclusi: {report.rejected}; "
                            f"duplicati: {report.duplicates}; errori: {', '.join(report.errors) or 'nessuno'}")

    def show_detail(self, row, column):
        job, decision = self.table.item(row, column).data(Qt.ItemDataRole.UserRole)
        detail = {**job.__dict__, "distance_km": decision.distance_km, "reference": decision.reference,
                  "accepted": decision.accepted, "reason": decision.reason}
        dialog = QMessageBox(self)
        dialog.setWindowTitle(job.title)
        dialog.setText("Dettagli geografici. Le distanze sono in linea d'aria.")
        dialog.setDetailedText(json.dumps(detail, ensure_ascii=False, indent=2))
        dialog.exec()

    def error(self, message):
        QMessageBox.warning(self, "JobRadar", message)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.status.setText("Attendere il termine del crawler prima di chiudere.")
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    gazetteer = Gazetteer.bundled()
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "JobRadarAICrawler"
    store = Store(base / "jobradar.sqlite3")
    store.seed_gazetteer(gazetteer)
    window = MainWindow(store, gazetteer)
    window.show()
    sys.exit(app.exec())
