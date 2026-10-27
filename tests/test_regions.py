import numpy as np
from PIL import Image

from stub import regions
from tests.fakes import CAFE, FUEL, MM, OFFICE, glass, receipt


def boxes_mm(img, multi=True):
    return [(tuple(round(v / MM) for v in box), edge) for box, edge in regions.find_regions(img, 300, multi)]


def contains(box, x_mm, y_mm, rec):
    w, h = rec.width / MM, rec.height / MM
    return box[0] <= x_mm and box[1] <= y_mm and box[2] >= x_mm + w - 1 and box[3] >= y_mm + h - 1


def test_box_count_matches_naive_window_sum():
    rng = np.random.default_rng(0)
    a = rng.random((30, 40)) > 0.7
    fast = regions.box_count(a, 2)
    padded = np.pad(a, 2)
    naive = np.array([[padded[y:y + 5, x:x + 5].sum() for x in range(40)] for y in range(30)])
    assert (fast == naive).all()


def test_three_receipts_become_three_regions():
    cafe, fuel, office = receipt(CAFE), receipt(FUEL, seed=2), receipt(OFFICE, seed=3)
    found = boxes_mm(glass([(cafe, (20, 20)), (fuel, (115, 20)), (office, (115, 200))]))
    assert len(found) == 3
    assert contains(found[0][0], 20, 20, cafe)
    assert contains(found[1][0], 115, 20, fuel)
    assert contains(found[2][0], 115, 200, office)
    assert not any(edge for _, edge in found)


def test_faded_receipt_with_blank_stretch_stays_whole():
    # verblasster Thermodruck mit 22 mm Leerraum: die alte Maske hat solche Bons zerschnitten
    fuel = receipt(FUEL, ink=170, seed=2)
    found = boxes_mm(glass([(fuel, (60, 60))]))
    assert len(found) == 1
    assert contains(found[0][0], 60, 60, fuel)


def test_dust_is_ignored_in_single_mode():
    cafe = receipt(CAFE)
    (box, edge), = boxes_mm(glass([(cafe, (70, 90))], dust=300), multi=False)
    assert contains(box, 70, 90, cafe)
    assert box[2] - box[0] < cafe.width / MM + 15  # kein Staubkorn hat den Rahmen aufgezogen
    assert not edge


def test_receipt_at_glass_edge_is_flagged():
    (_, edge), = boxes_mm(glass([(receipt(OFFICE), (0, 120))]))
    assert edge


def test_empty_glass_falls_back_to_whole_scan(tmp_path):
    raw = tmp_path / "leer.jpg"
    glass([], dust=0).save(raw)
    img, areas, found = regions.split_scan(raw, 300, True)
    assert not found
    assert areas == [((0, 0, img.width, img.height), False)]


def test_crop_page_writes_jpeg(tmp_path):
    dest = tmp_path / "seite.jpg"
    regions.crop_page(Image.new("RGB", (400, 300), "white"), (10, 20, 210, 120), dest)
    assert Image.open(dest).size == (200, 100)
