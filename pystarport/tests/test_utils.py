from pystarport.utils import parse_amount


def test_parse_amount():
    assert parse_amount("1000000.01uatom") == 1000000.01
    assert parse_amount({"amount": "1000000.01", "denom": "uatom"}) == 1000000.01
