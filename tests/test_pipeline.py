import unittest
import os
import json
import shutil
import tempfile
import sys

# Add project root to sys.path to enable imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import extract_chapter_title
from src.glossary import Glossary
from src.translator import sanitize_translation
from src.editor import Editor


class TestVibeTranslatePipeline(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for file-based tests
        self.test_dir = tempfile.mkdtemp()
        self.glossary_path = os.path.join(self.test_dir, "glossary.json")

    def tearDown(self):
        # Clean up temporary directory
        shutil.rmtree(self.test_dir)

    def test_extract_chapter_title(self):
        text_chinese_1 = "第1章 废柴觉醒，天道系统\n\n叶凡睁开双眼时..."
        text_chinese_2 = "第12章 木叶村的新来者 \n\n在接下来的几天里..."
        text_no_match = "Chapter 1: The Awakening\n\nSome content..."
        text_empty = "\n\n  \n"

        self.assertEqual(extract_chapter_title(text_chinese_1), "废柴觉醒，天道系统")
        self.assertEqual(extract_chapter_title(text_chinese_2), "木叶村的新来者")
        self.assertEqual(extract_chapter_title(text_no_match), "Chapter 1: The Awakening")
        self.assertEqual(extract_chapter_title(text_empty), "Untitled")

    def test_glossary_creation_and_overrides(self):
        # Create glossary with some initial overrides
        overrides = {"叶凡": "Ye Fan", "宇智波止水": "Shisui Uchiha"}
        glossary = Glossary(self.glossary_path, overrides=overrides)

        # Check that overrides are applied to the characters category
        self.assertEqual(glossary.data["characters"]["叶凡"], "Ye Fan")
        self.assertEqual(glossary.data["characters"]["宇智波止水"], "Shisui Uchiha")

        # Test lookup
        self.assertEqual(glossary.lookup("叶凡"), "Ye Fan")
        self.assertIsNone(glossary.lookup("NonExistent"))

        # Test add term
        glossary.add_term("locations", "木叶", "Konoha")
        self.assertEqual(glossary.lookup("木叶"), "Konoha")

        # Save and reload check
        glossary.save()
        
        # Load in another instance
        glossary2 = Glossary(self.glossary_path)
        self.assertEqual(glossary2.lookup("叶凡"), "Ye Fan")
        self.assertEqual(glossary2.lookup("木叶"), "Konoha")

        # Test markdown generation
        md = glossary.to_markdown()
        self.assertIn("# Novel Glossary", md)
        self.assertIn("## Characters", md)
        self.assertIn("- **叶凡**: Ye Fan", md)
        self.assertIn("## Locations", md)
        self.assertIn("- **木叶**: Konoha", md)

    def test_sanitize_translation(self):
        # Test code block stripping
        fence_md = "```markdown\nChapter 1: Title\nSome content...\n```"
        self.assertEqual(sanitize_translation(fence_md), "Chapter 1: Title\nSome content...")

        # Test zero-width space and BOM removal
        dirty_chars = "Hello\u200bWorld\ufeff!"
        self.assertEqual(sanitize_translation(dirty_chars), "HelloWorld!")

        # Test decorative unicode symbol removal
        decorations = "★Chapter 1☆ ●Title◆"
        self.assertEqual(sanitize_translation(decorations), "Chapter 1 Title")

        # Test de-duplication of punctuation
        dups = "Really??? Yes!!!"
        self.assertEqual(sanitize_translation(dups), "Really? Yes!")

        # Test quote normalization
        fancy_quotes = "\u201cHello\u201d, he said."
        self.assertEqual(sanitize_translation(fancy_quotes), '"Hello", he said.')

        # Test Chinese character removal safety net
        chinese_leak = "Sentence with 叶凡 Chinese characters."
        self.assertEqual(sanitize_translation(chinese_leak), "Sentence with  Chinese characters.")

    def test_editor_validation(self):
        class DummyClient:
            pass
        editor = Editor(client=DummyClient())

        # 1. Test clean translation passes validation
        clean_text = (
            "Chapter 1: The Awakening\n\n"
            "Ye Fan woke up feeling a burning pain in his meridians. The room was dilapidated with drafty windows.\n\n"
            "He struggled to sit up but coughed up a trail of dark blood. The door creaked in the night wind.\n\n"
            "[System: Heavenly Dao Translation System binding completed.\n"
            "Host Status: Qi Refining Stage 1 (Crippled)\n"
            "Meridian integrity: 12%]\n\n"
            "He took a deep breath. This was his only chance to survive."
        )
        self.assertEqual(editor.validate_translation(clean_text), [])

        # 2. Test Chinese characters leakage detection
        leak_text = "This is a translated sentence containing 叶凡 leakage."
        violations = editor.validate_translation(leak_text)
        self.assertTrue(any("Chinese characters detected" in v for v in violations))

        # 3. Test paragraph sentence limit check (Max 3 sentences)
        long_paragraph = (
            "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five."
        )
        violations = editor.validate_translation(long_paragraph)
        self.assertTrue(any("exceeds limit of 3" in v for v in violations))

        # 4. Test title format check
        invalid_title = "The Awakening\n\nSome text here."
        violations = editor.validate_translation(invalid_title)
        self.assertTrue(any("Chapter does not begin with correct title format" in v for v in violations))

        # 5. Test status screen unmatched brackets
        bad_status = "[System message with missing closing bracket"
        violations = editor.validate_translation(bad_status)
        self.assertTrue(any("unmatched square brackets" in v for v in violations))

        # 6. Test single newline detection outside status screens
        single_newline = "This is line one.\nThis is line two (which should be separated by double newline)."
        violations = editor.validate_translation(single_newline)
        self.assertTrue(any("Single newline found outside status screen" in v for v in violations))

        # 7. Test sentence splitting with quotes (verifying our regex fix!)
        para_with_quotes = 'He said, "No way!" And then he walked away. "Wait!" she called.'
        # This has exactly 3 sentences. With our fix, it splits into 3 sentences and has 0 violations.
        self.assertEqual(editor.validate_translation("Chapter 1: Test\n\n" + para_with_quotes), [])


if __name__ == "__main__":
    unittest.main()
