import re
import os
from typing import List, Optional, Tuple
from google import genai
from google.genai import types

# Import the shared sanitizer
from .translator import sanitize_translation


class Editor:
    def __init__(self, client: Optional[genai.Client] = None, model: str = "gemini-2.5-flash"):
        self.client = client or genai.Client()
        self.model = model

    def validate_translation(self, text: str) -> List[str]:
        """
        Runs programmatic checks on the English translation.
        Returns a list of violation descriptions. If empty, QC passed.
        """
        violations = []

        # 1. Chinese character leakage scan
        chinese_leak = re.findall(r'[\u4e00-\u9fff]', text)
        if chinese_leak:
            unique_leaks = list(set(chinese_leak))
            violations.append(f"Chinese characters detected in output: {', '.join(unique_leaks[:10])}")

        # 2. Translation artifact scan (special character clusters)
        artifact_matches = re.findall(r'[%$#&@!^*~]{2,}', text)
        if artifact_matches:
            violations.append(f"Translation artifacts detected: {', '.join(artifact_matches[:5])}")

        # 3. Unicode replacement character scan
        if '\ufffd' in text:
            violations.append("Unicode replacement characters (U+FFFD) detected in output.")

        # Split text into paragraphs (separated by double newlines)
        # Normalize line endings first
        normalized_text = text.replace("\r\n", "\n").strip()
        paragraphs = [p.strip() for p in normalized_text.split("\n\n") if p.strip()]

        # 4. Check header
        if paragraphs and not re.match(r"^(##?\s+)?Chapter \d+:", paragraphs[0], re.IGNORECASE):
            violations.append("Chapter does not begin with correct title format (e.g. 'Chapter X: Title').")

        for idx, para in enumerate(paragraphs):
            para_num = idx + 1
            # Check if this paragraph is a status screen
            is_status_screen = para.startswith("[") and para.endswith("]")

            if is_status_screen:
                # 5. Status screen check: must not contain blank lines inside
                # (Since we split by \n\n, any blank line would split it into two paragraphs,
                # so if it starts with [ and ends with ], it doesn't have blank lines inside, which is good.
                # But let's check if there are unmatched brackets.)
                open_brackets = para.count("[")
                close_brackets = para.count("]")
                if open_brackets != close_brackets:
                    violations.append(f"Paragraph {para_num} (Status Screen) has unmatched square brackets.")
            else:
                # 6. Prose paragraph checks: max 3 sentences per paragraph
                # Simple sentence splitter on punctuation (.?! followed by whitespace or quote)
                # Handles dialogue quotes at the end of a sentence
                sentences = re.split(r'(?<=[.!?])\s+(?=[A-Za-z"\'"\d])', para)
                # Filter out empty strings
                sentences = [s.strip() for s in sentences if s.strip()]
                
                if len(sentences) > 3:
                    violations.append(
                        f"Paragraph {para_num} has {len(sentences)} sentences (exceeds limit of 3). Content: \"{para[:60]}...\""
                    )

                # 7. Check if dialogue and prose are mixed in the same paragraph
                # Dialogue in English fanfiction translations usually starts or ends with quotes
                has_dialogue = '"' in para or '\u201c' in para or '\u201d' in para
                if has_dialogue:
                    # If dialogue is present, check if it is mixed with a lot of non-dialogue prose
                    # or contains multiple dialogue blocks that should be split.
                    quote_count = para.count('"') + para.count('\u201c') + para.count('\u201d')
                    if quote_count >= 4 and len(sentences) > 1:
                        # Likely multiple dialogue segments mixed or prose mixed with dialogue
                        violations.append(f"Paragraph {para_num} appears to mix multiple dialogue exchanges or prose and dialogue in one paragraph.")

        # 8. Verify single newline violations (check if any raw single newlines exist in prose)
        # We split the original normalized text by lines
        lines = normalized_text.split("\n")
        in_status_screen = False
        for line_idx, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            
            # Track status screen block
            if line.startswith("[") and not line.endswith("]"):
                in_status_screen = True
            if in_status_screen and line.endswith("]"):
                in_status_screen = False
                continue
            
            if in_status_screen:
                # Single newlines are allowed inside status screens
                continue
                
            # If not in status screen, check if next line exists and is not empty
            if line_idx + 1 < len(lines):
                next_line = lines[line_idx + 1].strip()
                if next_line and not (line.startswith("[") and line.endswith("]")):
                    # Found a single newline separating two text lines outside a status screen
                    violations.append(
                        f"Single newline found outside status screen around line {line_idx+1}: \"{line[:40]}\" immediately followed by \"{next_line[:40]}\"."
                    )
                    break # Just report the first occurrence to avoid spamming

        return violations

    def run_qc_and_fix(self, raw_chinese: str, initial_translation: str, chapter_num: int) -> str:
        """
        Runs programmatic validation. If violations exist, calls Gemini to correct the text.
        Retries up to 3 times. Returns corrected translation.
        """
        # Always apply sanitization first (catches most artifact issues without API call)
        current_translation = sanitize_translation(initial_translation)
        
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            violations = self.validate_translation(current_translation)
            if not violations:
                if attempt > 1:
                    print(f"[Editor] Chapter {chapter_num} QC passed on attempt {attempt}.")
                else:
                    print(f"[Editor] Chapter {chapter_num} QC passed on first attempt.")
                return current_translation
            
            print(f"[Editor] Chapter {chapter_num} QC failed (Attempt {attempt}/{max_attempts}). Violations found:")
            for v in violations:
                print(f"  - {v}")
                
            # Correct the translation using Gemini
            corrected = self.correct_translation(raw_chinese, current_translation, violations)
            # Re-sanitize after correction (the correction model may also produce artifacts)
            current_translation = sanitize_translation(corrected)
            
        # Final safety check after all attempts
        final_violations = self.validate_translation(current_translation)
        if final_violations:
            print(f"[Warning] Chapter {chapter_num} still has {len(final_violations)} QC violations after {max_attempts} correction attempts.")
            for v in final_violations:
                print(f"  [Remaining] {v}")
        else:
            print(f"[Editor] Chapter {chapter_num} QC passed after correction.")
            
        return current_translation

    def correct_translation(self, raw_chinese: str, translated_text: str, violations: List[str]) -> str:
        """Calls Gemini to fix specific formatting and validation errors."""
        violations_str = "\n".join([f"- {v}" for v in violations])
        
        prompt = f"""You are a professional novel copy-editor and translator.
We translated a Chinese chapter into English Markdown, but the result failed our programmatic Quality Control checklist.

### RAW CHINESE SOURCE (Reference):
{raw_chinese}

### INITIAL ENGLISH TRANSLATION:
{translated_text}

### QC VIOLATIONS TO FIX:
{violations_str}

### INSTRUCTIONS:
Edit and rewrite the initial English translation to fix all of the violations listed above.
You must maintain the original story details, name translations, and narrative tone perfectly.

Remember the formatting rules you MUST enforce:
1. **MAXIMUM 3 SENTENCES PER PARAGRAPH**. If a paragraph exceeds this, split it into smaller paragraphs of 1-3 sentences.
2. **BLANK LINE after every paragraph**. Ensure paragraphs are separated by a double newline (`\\n\\n`). No single newlines are allowed between lines of prose.
3. **Dialogue on separate lines** with blank lines between them.
4. **Status screens and system messages**: wrapped in `[square brackets]`, as a SINGLE block, with NO blank lines inside, and separated from prose by blank lines.
5. **No Chinese characters** allowed in the output.
6. **No special characters or artifacts** like %$#& or decorative symbols. Use only standard English punctuation (periods, commas, quotes, exclamation marks, question marks, colons, semicolons, hyphens, dashes, ellipsis).
7. **Do NOT truncate or summarize** the translation. Every sentence from the original must be present.

Return ONLY the corrected English Markdown text for the chapter. Do not include any chat, explanations, intro, or markdown fences (do not wrap in ```markdown).
"""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1, # Keep it deterministic and focused on correction
                ),
            )
            # Remove any markdown code fences if the model still outputs them
            cleaned_text = response.text.strip()
            if cleaned_text.startswith("```markdown"):
                cleaned_text = cleaned_text[len("```markdown"):]
            if cleaned_text.startswith("```md"):
                cleaned_text = cleaned_text[len("```md"):]
            if cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            return cleaned_text.strip()
        except Exception as e:
            print(f"[Error] Editor correction call failed: {e}")
            return translated_text
