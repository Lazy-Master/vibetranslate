import re
import json
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types
from .glossary import Glossary

class NewGlossaryTermSchema(BaseModel):
    category: str = Field(description="One of: characters, techniques, locations, organizations, items, others")
    chinese: str = Field(description="The raw Chinese term found in this chapter.")
    english: str = Field(description="The official translation or context-appropriate English translation.")

class TranslationOutputSchema(BaseModel):
    translated_text: str = Field(description="The complete translated chapter in English Markdown.")
    new_terms: List[NewGlossaryTermSchema] = Field(description="List of any new key character/item/location terms found in this chapter that were NOT in the glossary.")


def sanitize_translation(text: str) -> str:
    """
    Post-processing pass to strip common translation artifacts that LLMs
    sometimes inject into structured JSON output. These include stray special
    characters, encoding artifacts, leftover markdown fences, and other junk.
    """
    if not text:
        return text

    # 1. Strip markdown code fences that wrap the entire output
    cleaned = text.strip()
    if cleaned.startswith("```markdown"):
        cleaned = cleaned[len("```markdown"):]
    if cleaned.startswith("```md"):
        cleaned = cleaned[len("```md"):]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    # 2. Remove common encoding/escape artifacts
    #    These patterns match sequences of special symbols that don't belong
    #    in natural English prose (e.g., %$#&, @#$%, ★☆, etc.)
    # Remove clusters of 2+ consecutive special symbols (not inside [] brackets)
    cleaned = re.sub(r'(?<!\[)[%$#&@^*~]{2,}(?!\])', '', cleaned)
    
    # 3. Remove stray unicode replacement characters
    cleaned = cleaned.replace('\ufffd', '')  # U+FFFD replacement character
    cleaned = cleaned.replace('\u200b', '')  # zero-width space
    cleaned = cleaned.replace('\u200c', '')  # zero-width non-joiner
    cleaned = cleaned.replace('\u200d', '')  # zero-width joiner
    cleaned = cleaned.replace('\ufeff', '')  # BOM
    cleaned = cleaned.replace('\u00a0', ' ')  # non-breaking space -> normal space

    # 4. Remove stray backslash-escapes that shouldn't be in prose
    #    e.g., \n literal strings, \t, \\, etc. that got double-escaped
    cleaned = cleaned.replace('\\n', '\n')
    cleaned = cleaned.replace('\\t', ' ')
    cleaned = re.sub(r'\\([^\\])', r'\1', cleaned)  # remove single backslash before chars

    # 5. Remove decorative unicode symbols that LLMs sometimes add
    decorative_chars = ['★', '☆', '●', '○', '◆', '◇', '▶', '◀', '▲', '▼',
                        '♦', '♣', '♠', '♥', '→', '←', '↑', '↓', '⇒', '⇐',
                        '✦', '✧', '✩', '✪', '✫', '✬', '✭', '✮', '✯', '✰']
    for char in decorative_chars:
        cleaned = cleaned.replace(char, '')

    # 6. Clean up doubled/tripled punctuation (but preserve ... ellipsis)
    cleaned = re.sub(r'([!?])\1{2,}', r'\1', cleaned)  # ??? -> ?  !!! -> !
    cleaned = re.sub(r'\.{4,}', '...', cleaned)  # .... -> ...
    cleaned = re.sub(r',{2,}', ',', cleaned)  # ,, -> ,
    cleaned = re.sub(r';{2,}', ';', cleaned)  # ;; -> ;

    # 7. Fix common quote artifacts
    cleaned = cleaned.replace('""', '"')  # doubled quotes
    cleaned = cleaned.replace("''", "'")  # doubled single quotes
    # Normalize fancy quotes to straight quotes for consistency
    cleaned = cleaned.replace('\u201c', '"')  # left double quote
    cleaned = cleaned.replace('\u201d', '"')  # right double quote
    cleaned = cleaned.replace('\u2018', "'")  # left single quote
    cleaned = cleaned.replace('\u2019', "'")  # right single quote

    # 8. Remove any remaining Chinese characters that leaked through
    #    (this is a safety net — the main check is in editor.py)
    cleaned = re.sub(r'[\u4e00-\u9fff]', '', cleaned)
    
    # 9. Clean up multiple blank lines (3+ consecutive -> 2)
    cleaned = re.sub(r'\n{4,}', '\n\n\n', cleaned)
    
    # 10. Clean up trailing whitespace on lines
    cleaned = '\n'.join(line.rstrip() for line in cleaned.split('\n'))
    
    # 11. Remove completely empty lines that only have whitespace
    lines = cleaned.split('\n')
    result_lines = []
    for line in lines:
        result_lines.append(line if line.strip() else '')
    cleaned = '\n'.join(result_lines)

    return cleaned.strip()


class Translator:
    def __init__(self, client: Optional[genai.Client] = None, model: str = "gemini-3.1-flash-lite", config_rules: Optional[dict] = None):
        self.client = client or genai.Client()
        self.model = model
        self.config_rules = config_rules or {}

    def translate_chapter(
        self, 
        chapter_num: int, 
        chapter_title: str, 
        chinese_text: str, 
        glossary: Glossary, 
        story_context_str: str
    ) -> tuple[str, List[dict]]:
        """
        Translates a single chapter using story context and glossary.
        Returns a tuple: (translated_markdown, new_terms_list)
        """
        # Format current glossary entries for the prompt
        glossary_formatted = ""
        for cat, terms in glossary.data.items():
            if terms:
                glossary_formatted += f"### {cat.upper()}:\n"
                for cn, en in terms.items():
                    glossary_formatted += f"- {cn} -> {en}\n"

        # Estimate expected output length based on input
        chinese_char_count = sum(1 for c in chinese_text if '\u4e00' <= c <= '\u9fff')
        expected_word_count = max(800, int(chinese_char_count * 1.2))  # Chinese chars ~= 1.2 English words

        prompt = f"""You are a professional Chinese-to-English translator for fanfiction novels. You produce clean English Markdown.
You work in sessions of 1 chapter at a time to ensure maximum quality and consistency.

### SYSTEM INSTRUCTIONS & TRANSLATION RULES
1. **Chinese Pronouns Resolution**: Chinese text frequently omits pronouns or uses gender-neutral pronouns (他/她/它/他对等). Use the provided Story Narrative Context (active characters in scene) to resolve pronouns correctly to maintain story consistency.
2. **Translation Philosophy**: 
   - Translate the meaning, not just literal words. Keep sentence weights equal.
   - Translate idioms (成语) by contextual meaning, not literal words (e.g. 画蛇添足 -> "gilding the lily").
   - Battle/dramatic scenes: preserve the high tension and drama.
   - Comedy: translate the joke, do not sanitize.
   - Dialogue: Match the character's register (do not over-formalize, but avoid modern slang unless in the source).
   - No archaic English ("behold", "verily", "thus").
   - No padding adjectives ("vast and boundless", "absolutely terrifying", "truly").
   - No forced punchy fragments ("No beasts. No serpents.").
   - No emoji-replacement single words ("BOOM.", "Brutal.").
   - Skip author/translator notes entirely.
3. **Naming Conventions**:
   - Japanese IPs: Use official romanizations (e.g. 宇智波止水 -> Uchiha Shisui, 大蛇丸 -> Orochimaru, 寫輪眼 -> Sharingan, 木葉 -> Konoha). Keep honorifics (-san, -sensei, -sama, -chan, -kun).
   - Western IPs: Use official English names (e.g. 鋼鐵俠 -> Iron Man, 霍格華茲 -> Hogwarts).
   - Chinese IPs: Use Pinyin (e.g. 石昊 -> Shi Hao, 蕭炎 -> Xiao Yan).
   - Fanfic-Original: Use Pinyin and flag them.
4. **Formatting Rules (CRITICAL - VIOLATING = FAIL)**:
   - **MAXIMUM 3 SENTENCES PER PARAGRAPH**. No exceptions.
   - **BLANK LINE after every paragraph**. No exceptions.
   - Dialogue on separate lines with blank lines between them.
   - Status screens and system messages: ONE single block, wrapped in `[square brackets]`, with NO blank lines inside the block, separated from normal prose by blank lines.
   - **No Chinese characters** in the output text. Zero tolerance.
5. **Output Length**: The source text has approximately {chinese_char_count} Chinese characters. Your English translation should be approximately {expected_word_count} words. Do NOT truncate, summarize, or abbreviate. Translate EVERY sentence of the source text. Missing content = FAIL.
6. **Clean Output**: Do NOT include any special characters like %$#& or decorative symbols in your output. Use only standard English punctuation. Do NOT wrap output in markdown code fences.

---

### REFERENCE DATA

{story_context_str}

## ACTIVE GLOSSARY:
{glossary_formatted}

---

### CHAPTER TO TRANSLATE
**Chapter {chapter_num}: {chapter_title}**

{chinese_text}

---

### OUTPUT SCHEMAS
You must structure your response matching the output JSON schema. Ensure `translated_text` contains the full chapter starting with the title:
"Chapter {chapter_num}: {chapter_title}"

IMPORTANT: The `translated_text` field must contain ONLY clean English text. No special characters, no encoding artifacts, no Chinese characters. Use standard ASCII punctuation only (periods, commas, quotes, exclamation marks, question marks, colons, semicolons, dashes, ellipsis).
"""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=TranslationOutputSchema,
                    temperature=0.3,  # Slightly higher for more natural prose
                ),
            )
            
            output = TranslationOutputSchema.model_validate_json(response.text)
            
            # Apply post-processing sanitization to strip artifacts
            clean_text = sanitize_translation(output.translated_text)
            
            # Process new terms
            new_terms = []
            for term in output.new_terms:
                new_terms.append({
                    "category": term.category.lower(),
                    "chinese": term.chinese.strip(),
                    "english": term.english.strip()
                })
                
            return clean_text, new_terms
            
        except Exception as e:
            print(f"[Error] Translation failed for Chapter {chapter_num}: {e}")
            raise e
