from chibi_audio.audio import _db


def test_db_reference_points():
    assert _db(1.0) == 0.0
    assert _db(0.0) == -160.0
