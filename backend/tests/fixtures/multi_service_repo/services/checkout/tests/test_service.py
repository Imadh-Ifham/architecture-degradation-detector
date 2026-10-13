from checkout.service import start


def test_start() -> None:
    assert start() is None
