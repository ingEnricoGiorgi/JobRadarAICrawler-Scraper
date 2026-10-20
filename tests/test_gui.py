from PySide6.QtWidgets import QApplication

from jobradar.geo import Gazetteer, Listing, WorkMode, evaluate, normalize_listing
from jobradar.gui import MainWindow
from jobradar.storage import Store


def test_gui_profiles_filters_and_results(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "gui.sqlite3")
    gazetteer = Gazetteer.bundled()
    window = MainWindow(store, gazetteer)
    errors = []
    window.error = errors.append
    city = gazetteer.resolve("Fano")[0]
    window.area.setEditText(city.label)
    window.add_area()
    window.add_area()
    assert window.areas.count() == 1
    window.center.setEditText(city.label)
    window.add_radius()
    window.kind.setCurrentIndex(3)
    window.area.setEditText(gazetteer.resolve("Roma")[0].label)
    window.add_area()
    window.profile_names.setEditText("Fixture profilo GUI")
    window.save_profile()
    saved = window.profile()
    assert saved.cities == [city.code] and saved.radii and saved.excluded_cities
    window.areas.clear()
    window.load_profile()
    assert window.profile() == saved
    job = normalize_listing(Listing("fixture", "test", "GUI test fixture", "Fano", work_mode=WorkMode.ONSITE), gazetteer)
    store.save_listing(job, saved, evaluate(job, saved))
    window.refresh()
    assert window.table.rowCount() == 1
    assert window.table.item(0, 7).text() == "Incluso"
    assert not errors
    window.close()
    app.processEvents()


def test_gui_ambiguous_city_and_address_coordinates(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(Store(tmp_path / "gui.sqlite3"), Gazetteer.bundled())
    errors = []
    window.error = errors.append
    window.area.setEditText("Località inesistente fixture")
    window.add_area()
    assert errors and window.areas.count() == 0
    window.address.setText("Indirizzo approssimativo fixture")
    window.lat.setText("43,8")
    window.lon.setText("13,0")
    window.add_radius()
    assert window.profile().radii[0].latitude == 43.8
    assert window.profile().radii[0].municipality_code is None
    window.close()
    app.processEvents()
