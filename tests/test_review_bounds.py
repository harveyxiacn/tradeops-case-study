import unittest
from fastapi import HTTPException
from tradeops.app import calculate
class ReviewBounds(unittest.TestCase):
    def test_nested_non_object_rejected(self):
        for value in [None,[],"bad"]:
            with self.assertRaises(HTTPException) as e:calculate(value)
            self.assertEqual(e.exception.status_code,422)
    def test_extreme_total_rejected_before_database(self):
        b={'currency':'USD','lines':[{'sku':'DEMO-A','qty':1000000,'unit_price':'100000000','unit_cost':'1'}]*50}
        with self.assertRaises(HTTPException) as e:calculate(b,False)
        self.assertEqual(e.exception.status_code,422)
