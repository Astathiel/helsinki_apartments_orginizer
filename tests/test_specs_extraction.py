import unittest
from api.index import clean_street_address, extract_specs_from_text, generate_dossier

class TestSpecsExtraction(unittest.TestCase):
    def test_clean_street_address_hyphen_pattern(self):
        title = "Vuokrataan Kerrostalo 3 huonetta - Helsinki Ruoholahti Selkamerenkatu 12"
        self.assertEqual(clean_street_address(title, "Ruoholahti"), "Selkamerenkatu 12")

    def test_clean_street_address_suffix_pattern(self):
        title = "Valoisa koti Kiillekuja 3"
        self.assertEqual(clean_street_address(title, "Kruunuvuori"), "Kiillekuja 3")

    def test_clean_street_address_fallback(self):
        title = "Upea koti hyvien kulkuyhteyksien varrella"
        self.assertEqual(clean_street_address(title, "Kamppi"), "Kamppi")

    def test_extract_specs_full(self):
        text = """
        Vuokrataan 3h+k. Kerros 4/6, talossa on hissi.
        Vesimaksu sisältyy vuokraan. Lemmikit ovat sallittu.
        Lasitettu oma parveke puistonäkymin. Oma sauna.
        """
        specs = extract_specs_from_text(text)
        self.assertEqual(specs["floor"], 4)
        self.assertEqual(specs["total_floors"], 6)
        self.assertEqual(specs["floor_str"], "4/6")
        self.assertTrue(specs["has_elevator"])
        self.assertTrue(specs["water_included"])
        self.assertEqual(specs["water_fee"], "Sisältyy vuokraan")
        self.assertTrue(specs["pets_allowed"])
        self.assertTrue(specs["has_balcony"])
        self.assertEqual(specs["balcony_type"], "Lasitettu parveke")
        self.assertTrue(specs["has_sauna"])
        self.assertEqual(specs["sauna_type"], "Oma sauna")

    def test_extract_specs_partial_and_negatives(self):
        text = """
        Kerros 1/3, ei hissiä.
        Vesimaksu: 22 € / hlö / kk.
        Ei lemmikkejä, lemmikit kielletty.
        Ei parveketta. Taloyhtiön sauna löytyy pohjakerroksesta.
        """
        specs = extract_specs_from_text(text)
        self.assertEqual(specs["floor"], 1)
        self.assertEqual(specs["total_floors"], 3)
        self.assertFalse(specs["has_elevator"])
        self.assertFalse(specs["water_included"])
        self.assertEqual(specs["water_fee"], "22 €/hlö/kk")
        self.assertFalse(specs["pets_allowed"])
        self.assertFalse(specs["has_balcony"])
        self.assertEqual(specs["balcony_type"], "Ei parveketta")
        self.assertFalse(specs["has_sauna"])
        self.assertEqual(specs["sauna_type"], "Taloyhtiön sauna")

    def test_generate_dossier(self):
        text = "Kerros 5/5, hissi: kyllä. Vesi sisältyy vuokraan. Oma sauna ja lasitettu parveke."
        dossier = generate_dossier(
            price=1200.0,
            size_m2=60.0,
            asuinalue="Töölö",
            raw_text=text
        )
        self.assertIn("pros", dossier)
        self.assertIn("cons", dossier)
        self.assertTrue(any("neliöhinta" in p for p in dossier["pros"]))
        self.assertTrue(any("Ylin kerros" in p for p in dossier["pros"]))

if __name__ == "__main__":
    unittest.main()
