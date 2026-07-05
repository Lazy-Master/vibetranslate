import os
import re
import requests
from bs4 import BeautifulSoup
from typing import Optional

class Extractor:
    def __init__(self, temp_dir: str):
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)

    def extract_chapter(self, chapter_num: int, url: Optional[str] = None) -> str:
        """
        Extracts chapter content.
        First, looks for a local file `ch[NNN]_raw.txt` in temp_dir.
        If not found and url is provided, scrapes the URL and saves it.
        """
        local_filename = f"ch{chapter_num}_raw.txt"
        local_path = os.path.join(self.temp_dir, local_filename)

        # Check local file first (local-first ingestion)
        if os.path.exists(local_path):
            print(f"[Extractor] Found local raw file for Chapter {chapter_num} at {local_path}.")
            with open(local_path, "r", encoding="utf-8") as f:
                return f.read()

        if not url:
            raise FileNotFoundError(
                f"Local raw chapter file {local_filename} not found in {self.temp_dir}, "
                f"and no source URL was provided for scraping."
            )

        print(f"[Extractor] Local raw file not found. Fetching from URL: {url}")
        content = self.scrape_url(url)
        
        # Save raw content locally for future runs and debugging
        with open(local_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[Extractor] Saved raw chapter content to {local_path}.")
        
        return content

    def scrape_url(self, url: str) -> str:
        """Scrapes text content from a web novel page, removing ads, banners, script elements."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # Detect encoding correctly (especially for GBK/GB2312 commonly used in older Chinese sites)
            if response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding
                
            html = response.text
            soup = BeautifulSoup(html, "html.parser")
            
            # Remove scripts, styles, comments, and nav headers
            for element in soup(["script", "style", "nav", "footer", "iframe", "header", "noscript"]):
                element.decompose()
                
            # Common web novel content containers on popular sites
            content_div = None
            potential_ids = ["content", "chaptercontent", "chapterContent", "booktxt", "novelcontent", "txt"]
            potential_classes = ["content", "read-content", "chapter-content", "txt"]
            
            for pid in potential_ids:
                content_div = soup.find(id=pid)
                if content_div:
                    break
            
            if not content_div:
                for pclass in potential_classes:
                    content_div = soup.find(class_=pclass)
                    if content_div:
                        break
            
            # Fallback to body if no content container is found
            target = content_div if content_div else soup.body
            if not target:
                raise ValueError("Could not locate text body on the page.")
                
            # Extract text block paragraphs
            paragraphs = []
            for p in target.find_all(["p", "br"]):
                # Handle direct sibling text around <br> tags
                if p.name == "br":
                    continue
                txt = p.get_text().strip()
                if txt:
                    # Filter out common ad markers
                    if any(ad in txt for ad in ["点击下一页", "本章未完", "推荐阅", "加入书签"]):
                        continue
                    paragraphs.append(txt)
            
            # If find_all('p') didn't yield much, fall back to split text lines
            if not paragraphs or len(paragraphs) < 3:
                text_lines = target.get_text(separator="\n").split("\n")
                for line in text_lines:
                    line = line.strip()
                    if line and not any(ad in line for ad in ["点击下一页", "本章未完", "推荐阅", "加入书签"]):
                        paragraphs.append(line)
                        
            if not paragraphs:
                raise ValueError("Extraction yielded empty text paragraphs.")
                
            return "\n\n".join(paragraphs)
            
        except Exception as e:
            raise RuntimeError(f"Failed to scrape content from {url}: {e}")
