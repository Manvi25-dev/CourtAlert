import unittest
from case_parser import parse_case_number

class TestCaseParser(unittest.TestCase):
    
    def test_standard_formats(self):
        """Test standard Delhi High Court formats"""
        cases = {
            "CRL.M.C. 320/2026": "CRL.M.C. 320/2026",
            "W.P.(C) 1234/2025": "W.P.(C) 1234/2025",
            "CS(COMM) 567/2024": "CS(COMM) 567/2024",
            "FAO(OS) 89/2023": "FAO(OS) 89/2023",
            "CRL.A. 12/2022": "CRL.A. 12/2022",
            "CM(M) 45/2021": "CM(M) 45/2021"
        }
        for input_text, expected in cases.items():
            self.assertEqual(parse_case_number(input_text), expected)

    def test_contextual_sentences(self):
        """Test extraction from sentences"""
        sentences = {
            "Please add case CRL.M.C. 320/2026 to my list": "CRL.M.C. 320/2026",
            "Track W.P.(C) 1234/2025 for me": "W.P.(C) 1234/2025",
            "What is the status of CS(COMM) 567/2024?": "CS(COMM) 567/2024",
            "I want to follow FAO(OS) 89/2023": "FAO(OS) 89/2023"
        }
        for text, expected in sentences.items():
            self.assertEqual(parse_case_number(text), expected)

    def test_flexible_spacing_and_separators(self):
        """Test handling of spaces and 'of'/'slash'"""
        variations = {
            "W.P. (C) 1234 / 2025": "W.P.(C) 1234/2025", # Spaces in type and around slash
            "CRL.M.C. 320 of 2026": "CRL.M.C. 320/2026", # 'of' instead of '/'
            "CS(COMM) 567 slash 2024": "CS(COMM) 567/2024", # 'slash' word
            "CRL. A. 12/2022": "CRL.A. 12/2022" # Space in type
        }
        for text, expected in variations.items():
            self.assertEqual(parse_case_number(text), expected)

    def test_invalid_inputs(self):
        """Test that invalid inputs return None"""
        invalid_inputs = [
            "Just some random text",
            "Case 123/20", # Year too short
            "No number here",
            "W.P.(C) /2025", # Missing number
            "1234/2025" # Missing type
        ]
        for text in invalid_inputs:
            self.assertIsNone(parse_case_number(text))

if __name__ == '__main__':
    unittest.main()
