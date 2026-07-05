import os
import json
from typing import Dict, List, Optional

class Glossary:
    def __init__(self, filepath: str, overrides: Optional[Dict[str, str]] = None):
        self.filepath = filepath
        # Standard glossary categories
        self.data: Dict[str, Dict[str, str]] = {
            "characters": {},
            "techniques": {},
            "locations": {},
            "organizations": {},
            "items": {},
            "others": {}
        }
        self.overrides = overrides or {}
        self.load()
        self.apply_overrides()

    def load(self):
        """Loads the glossary from a JSON file. Creates one if it doesn't exist."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    loaded_data = json.load(f)
                    # Merge loaded categories to prevent missing categories
                    for cat, terms in loaded_data.items():
                        if cat in self.data:
                            self.data[cat].update(terms)
                        else:
                            self.data[cat] = terms
            except json.JSONDecodeError:
                print(f"[Warning] Failed to decode glossary JSON at {self.filepath}. Starting fresh.")
        else:
            # Ensure output directory exists
            os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
            self.save()

    def save(self):
        """Saves the glossary to a JSON file."""
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def apply_overrides(self):
        """Applies manual character name overrides to the character glossary category."""
        for cn_name, en_name in self.overrides.items():
            if cn_name and en_name:
                self.data["characters"][cn_name] = en_name
        self.save()

    def lookup(self, term: str) -> Optional[str]:
        """Looks up a term in all categories."""
        for cat in self.data:
            if term in self.data[cat]:
                return self.data[cat][term]
        return None

    def add_term(self, category: str, cn_term: str, en_term: str):
        """Adds or updates a term in the specified category."""
        if category not in self.data:
            self.data[category] = {}
        self.data[category][cn_term] = en_term
        self.save()

    def to_markdown(self) -> str:
        """Generates a human-readable markdown representation of the glossary."""
        md = "# Novel Glossary\n\n"
        for category, terms in self.data.items():
            if terms:
                md += f"## {category.capitalize()}\n"
                for cn, en in sorted(terms.items()):
                    md += f"- **{cn}**: {en}\n"
                md += "\n"
        return md

    def save_markdown(self, filepath: str):
        """Saves a markdown version of the glossary."""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(self.to_markdown())
