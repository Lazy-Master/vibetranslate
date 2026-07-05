import os
import json
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

class StoryContextData(BaseModel):
    running_summary: str = ""
    chapter_summaries: Dict[str, str] = {}
    last_chapter_ending_state: str = ""
    last_chapter_tail_paragraphs: List[str] = []

class ContextUpdateSchema(BaseModel):
    chapter_summary: str = Field(description="A brief 1-2 sentence summary of this chapter.")
    updated_running_summary: str = Field(description="The updated rolling summary of the entire novel so far, incorporating the events of this chapter. Keep it concise (max 300 words).")
    ending_state: str = Field(description="Narrative state at the very end of this chapter. List the location, characters present in the scene, and the last active cliffhanger or action.")

class ContextManager:
    def __init__(self, filepath: str, client: Optional[genai.Client] = None, model: str = "gemini-3.1-flash-lite"):
        self.filepath = filepath
        self.client = client or genai.Client()
        self.model = model
        self.context_data = StoryContextData()
        self.load()

    def load(self):
        """Loads story context from json file if it exists."""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.context_data = StoryContextData.model_validate(data)
            except Exception as e:
                print(f"[Warning] Failed to load story context at {self.filepath}: {e}. Starting fresh.")
        else:
            os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
            self.save()

    def save(self):
        """Saves story context to json file."""
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write(self.context_data.model_dump_json(indent=2))

    def get_translation_context(self) -> str:
        """Formats the context information to be fed into the translation prompt."""
        context_str = "## STORY NARRATIVE CONTEXT (For consistency across chapters)\n"
        if self.context_data.running_summary:
            context_str += f"- **Running Novel Summary:** {self.context_data.running_summary}\n"
        else:
            context_str += "- **Running Novel Summary:** This is the beginning of the translation.\n"

        if self.context_data.last_chapter_ending_state:
            context_str += f"- **Previous Chapter Ending State:** {self.context_data.last_chapter_ending_state}\n"
        
        if self.context_data.last_chapter_tail_paragraphs:
            context_str += "- **Last Chapter Final Paragraphs (English style & continuity baseline):**\n"
            for p in self.context_data.last_chapter_tail_paragraphs:
                context_str += f"  > {p}\n"
        
        return context_str

    def update_context(self, chapter_num: int, chapter_title: str, translated_content: str):
        """Calls Gemini to analyze the new chapter and update rolling summaries and ending states."""
        # Extract the last few paragraphs programmatically
        paragraphs = [p.strip() for p in translated_content.split("\n\n") if p.strip()]
        tail_paragraphs = paragraphs[-3:] if len(paragraphs) >= 3 else paragraphs

        prompt = f"""You are a story context manager assistant. Analyze the following newly translated chapter of a novel and update our story context registry.

### CURRENT CONTEXT REGISTER
- **Running Summary:** {self.context_data.running_summary or 'No history yet.'}
- **Previous Ending State:** {self.context_data.last_chapter_ending_state or 'No history yet.'}

### NEW CHAPTER TO PROCESS
**Chapter {chapter_num}: {chapter_title}**

{translated_content}

### TASK
Analyze the chapter and update the context information. You must return your response matching the requested schema.
"""
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ContextUpdateSchema,
                ),
            )
            update = ContextUpdateSchema.model_validate_json(response.text)
            
            # Update internal state
            self.context_data.running_summary = update.updated_running_summary
            self.context_data.chapter_summaries[str(chapter_num)] = update.chapter_summary
            self.context_data.last_chapter_ending_state = update.ending_state
            self.context_data.last_chapter_tail_paragraphs = tail_paragraphs
            
            self.save()
            print(f"[ContextManager] Successfully updated context after Chapter {chapter_num}.")
        except Exception as e:
            print(f"[Error] ContextManager failed to update context for Chapter {chapter_num}: {e}")
            # Fallback update: just grab tail paragraphs, keep others unchanged
            self.context_data.chapter_summaries[str(chapter_num)] = f"Chapter {chapter_num} translated."
            self.context_data.last_chapter_tail_paragraphs = tail_paragraphs
            self.save()
