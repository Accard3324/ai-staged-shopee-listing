from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shopee_listing_app.candidate_selector import CandidateSKU
from shopee_listing_app.listing_builder import build_variations, normalize_price


class VariationBuilderTests(unittest.TestCase):
    def test_variations_use_excel_prices_stock_and_sku_code(self):
        candidate = CandidateSKU(
            row=8,
            sku_spec="28g",
            store_status="未上架",
            price_1box="9.90",
            price_2box="18.80",
            price_3box="27.50",
            sales_rank_15d_avg="1.2",
            sku_code="SKU-001",
            product_name="Toothpaste",
            brand="BrandA",
            overseas_available_stock="88",
        )

        variations = build_variations(candidate)

        self.assertEqual([item["name"] for item in variations], ["28g /1box", "2x 28g /2box", "3x 28g /3box"])
        self.assertEqual([item["price"] for item in variations], ["9.90", "18.80", "27.50"])
        self.assertEqual({item["stock"] for item in variations}, {"88"})
        self.assertEqual({item["item_code"] for item in variations}, {"SKU-001"})
        self.assertTrue(all(item["gtin"] == "" and item["no_gtin"] for item in variations))

    def test_excel_formula_price_is_normalized_to_two_decimal_places(self):
        self.assertEqual(normalize_price(50.6296296296296), "50.63")

    def test_missing_or_zero_excel_stock_defaults_to_one_hundred(self):
        for stock in ("", None, 0, "0"):
            with self.subTest(stock=stock):
                candidate = CandidateSKU(
                    row=8,
                    sku_spec="28g",
                    store_status="未上架",
                    price_1box="9.90",
                    price_2box="18.80",
                    price_3box="27.50",
                    sales_rank_15d_avg="1.2",
                    sku_code="SKU-001",
                    product_name="Toothpaste",
                    brand="BrandA",
                    overseas_available_stock=stock,
                )

                variations = build_variations(candidate)

                self.assertEqual({item["stock"] for item in variations}, {"100"})


if __name__ == "__main__":
    unittest.main()
