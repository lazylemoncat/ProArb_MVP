from src.utils.CsvHandler import CsvHandler

def test_check_csv():
    CsvHandler.check_csv("./data2/1.csv", ["a", "b"])