# -*- coding: utf-8 -*-
import unittest
from pathlib import Path


class XdsCommandTest(unittest.TestCase):
    def test_gpiopins_y_options_do_not_contain_spaces(self):
        text = Path("micu_bsl/burner.py").read_text(encoding="utf-8")
        for line in text.splitlines():
            if "gpiopins" in line and '"-Y"' in line:
                self.assertNotIn("gpiopins,", line.replace("gpiopins,config", "gpiopins_config_ok"))
                self.assertNotIn(", config", line)
                self.assertNotIn(", write", line)


if __name__ == "__main__":
    unittest.main()
