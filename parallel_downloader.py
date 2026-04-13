"""
Parallel Multi-Source Telugu Songs Downloader
Fast concurrent downloading with threading
Fuzzy matching and aggressive search strategies
"""

import requests
from bs4 import BeautifulSoup
import os
import re
import time
import concurrent.futures
from urllib.parse import urljoin, unquote
from tqdm import tqdm
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional, Set
from threading import Lock
import threading


@dataclass
class Song:
    number: int
    song_name: str
    movie_name: str
    original_line: str


@dataclass  
class DownloadTask:
    song: Song
    download_url: str
    filename: str
    quality: str
    source: str


class ParallelDownloader:
    def __init__(self, download_dir="downloads", max_workers=8):
        self.download_dir = download_dir
        self.max_workers = max_workers
        self.failed_songs: List[Song] = []
        self.success_count = 0
        self.fail_count = 0
        self.lock = Lock()
        
        # Statistics
        self.stats = {
            'naasongs_found': 0,
            'sensongs_found': 0,
            'total_searched': 0,
        }
        
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
        
        # Thread-local sessions
        self.thread_local = threading.local()
    
    def get_session(self) -> requests.Session:
        """Get thread-local session"""
        if not hasattr(self.thread_local, 'session'):
            self.thread_local.session = requests.Session()
            self.thread_local.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            })
        return self.thread_local.session
    
    def parse_song_list(self, filename: str) -> List[Song]:
        """Parse song list"""
        songs = []
        if not os.path.exists(filename):
            return songs
        
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                match = re.match(r'^(\d+)\.\s*(.+?)\s*-\s*(.+)$', line)
                if match:
                    songs.append(Song(
                        number=int(match.group(1)),
                        song_name=match.group(2).strip(),
                        movie_name=match.group(3).strip(),
                        original_line=line
                    ))
        return songs
    
    def clean_for_url(self, text: str) -> str:
        """Clean for URL"""
        return re.sub(r'[^\w\s-]', '', text).lower().strip().replace(' ', '-')
    
    def fuzzy_match(self, search_term: str, text: str) -> bool:
        """Fuzzy matching with variations"""
        search = search_term.lower()
        text_lower = text.lower()
        
        # Direct match
        if search in text_lower:
            return True
        
        # Remove spaces
        if search.replace(' ', '') in text_lower.replace(' ', ''):
            return True
        
        # Remove common words
        simplified = re.sub(r'\(.*\)|song|the|full|promo|part|\d+', '', search).strip()
        if simplified and simplified in text_lower:
            return True
        
        # Word by word match (for partial matches)
        words = search.replace('-', ' ').split()
        matched_words = sum(1 for word in words if len(word) > 2 and word in text_lower)
        if len(words) > 0 and matched_words / len(words) >= 0.6:
            return True
        
        return False
    
    def generate_url_variants(self, movie_name: str, song_name: str, base_url: str, source: str) -> List[str]:
        """Generate all possible URL variants for a movie/song"""
        clean_movie = self.clean_for_url(movie_name)
        clean_song = self.clean_for_url(song_name)
        
        urls = []
        
        if source == 'naasongs':
            # NaaSongs patterns
            patterns = [
                (f"{clean_movie}-{{year}}-songs{{suffix}}.html", [2026, 2025, 2024, 2023], ['', '-a', '-b', '-c']),
                (f"{clean_movie}-songs{{suffix}}.html", [''], ['', '-a', '-b']),
                (f"{clean_movie}-telugu-songs{{suffix}}.html", [''], ['', '-a']),
                (f"{clean_movie}-2-songs.html", [''], ['']),
            ]
            
            for template, years, suffixes in patterns:
                for year in years:
                    for suffix in suffixes:
                        if '{year}' in template:
                            urls.append(f"{base_url}/{template.format(year=year, suffix=suffix)}")
                        else:
                            urls.append(f"{base_url}/{template.format(suffix=suffix)}")
            
            # Song-specific
            song_patterns = [
                f"{base_url}/{clean_song}-song.html",
                f"{base_url}/{clean_song}-song-{clean_movie}.html",
                f"{base_url}/{clean_song}.html",
            ]
            urls.extend(song_patterns)
            
        elif source == 'sensongs':
            # SenSongs patterns
            patterns = [
                (f"{clean_movie}-{{year}}-songs-download{{suffix}}/", [2026, 2025, 2024, 2023], ['', '-a', '-b']),
                (f"{clean_movie}-songs-download{{suffix}}/", [''], ['', '-a', '-b']),
                (f"{clean_movie}-telugu-songs-download/", [''], ['']),
            ]
            
            for template, years, suffixes in patterns:
                for year in years:
                    for suffix in suffixes:
                        if '{year}' in template:
                            urls.append(f"{base_url}/{template.format(year=year, suffix=suffix)}")
                        else:
                            urls.append(f"{base_url}/{template.format(suffix=suffix)}")
            
            song_patterns = [
                f"{base_url}/{clean_song}-song-download/",
                f"{base_url}/{clean_song}-{clean_movie}-download/",
            ]
            urls.extend(song_patterns)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_urls = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return unique_urls
    
    def search_all_sources_concurrent(self, song: Song) -> Optional[DownloadTask]:
        """Search all sources concurrently and return first match"""
        
        sources = [
            ('naasongs', 'https://naasongs.com.co'),
            ('sensongs', 'https://sensongsmp3.live'),
        ]
        
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_to_source = {
                executor.submit(self._search_source, song, source_name, base_url): source_name
                for source_name, base_url in sources
            }
            
            for future in concurrent.futures.as_completed(future_to_source):
                source_name = future_to_source[future]
                try:
                    result = future.result(timeout=20)
                    if result:
                        results.append(result)
                except:
                    pass
        
        # Return best match (prefer 320kbps)
        if results:
            kbps_320 = [r for r in results if r.quality == '320kbps']
            if kbps_320:
                return kbps_320[0]
            return results[0]
        
        return None
    
    def _search_source(self, song: Song, source_name: str, base_url: str) -> Optional[DownloadTask]:
        """Search a single source"""
        session = self.get_session()
        
        urls = self.generate_url_variants(song.movie_name, song.song_name, base_url, source_name)
        
        for url in urls:
            try:
                response = session.get(url, timeout=10)
                if response.status_code != 200:
                    continue
                
                soup = BeautifulSoup(response.content, 'html.parser')
                page_text = soup.get_text()
                
                # Check if song is on this page
                if not self.fuzzy_match(song.song_name, page_text):
                    # If on song-specific page, look for movie link
                    if 'song' in url and source_name == 'naasongs':
                        for link in soup.find_all('a', href=True):
                            href = link.get('href', '')
                            if 'songs' in href and href.endswith('.html'):
                                try:
                                    movie_url = urljoin(base_url, href)
                                    movie_resp = session.get(movie_url, timeout=10)
                                    if movie_resp.status_code == 200:
                                        movie_soup = BeautifulSoup(movie_resp.content, 'html.parser')
                                        if self.fuzzy_match(song.song_name, movie_soup.get_text()):
                                            download = self._extract_from_soup(movie_soup, song, source_name)
                                            if download:
                                                return download
                                except:
                                    continue
                    continue
                
                # Found the page, now extract download
                download = self._extract_from_soup(soup, song, source_name)
                if download:
                    return download
                    
            except Exception as e:
                continue
        
        return None
    
    def _extract_from_soup(self, soup: BeautifulSoup, song: Song, source: str) -> Optional[DownloadTask]:
        """Extract download link from soup"""
        
        song_variants = [
            song.song_name.lower(),
            song.song_name.lower().replace(' ', ''),
            re.sub(r'\(.*\)', '', song.song_name).lower().strip(),
        ]
        
        candidates = []
        
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if not href.endswith('.mp3'):
                continue
            
            text = link.get_text(strip=True).lower()
            parent = link.find_parent(['p', 'div', 'li', 'td', 'tr'])
            parent_text = parent.get_text(strip=True).lower() if parent else ""
            
            # Check match
            matched = any(
                v in text or v in parent_text or v.replace(' ', '') in parent_text or v in href.lower()
                for v in song_variants
            )
            
            quality = "320kbps" if "320" in href or "320" in text else "128kbps"
            
            # Create filename
            mp3_name = unquote(href.split('/')[-1])
            if not mp3_name.endswith('.mp3'):
                safe_song = re.sub(r'[^\w\s-]', '', song.song_name).strip()
                safe_movie = re.sub(r'[^\w\s-]', '', song.movie_name).strip()
                mp3_name = f"{safe_song} - {safe_movie}.mp3"
            
            mp3_name = re.sub(r'[<>:"/\\|?*]', '', mp3_name)
            if len(mp3_name) > 100:
                mp3_name = mp3_name[:100]
            
            candidates.append(DownloadTask(
                song=song,
                download_url=href,
                filename=mp3_name,
                quality=quality,
                source=source
            ))
        
        # Return best candidate
        if candidates:
            matched = [c for c in candidates if c.quality == '320kbps']
            if matched:
                return matched[0]
            return candidates[0]
        
        return None
    
    def download_single(self, task: DownloadTask) -> bool:
        """Download a single file"""
        filepath = os.path.join(self.download_dir, task.filename)
        
        # Check cache
        if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
            with self.lock:
                self.success_count += 1
            return True
        
        session = self.get_session()
        
        try:
            response = session.get(task.download_url, stream=True, timeout=45)
            response.raise_for_status()
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            if os.path.getsize(filepath) < 1000:
                os.remove(filepath)
                return False
            
            with self.lock:
                self.success_count += 1
            return True
            
        except:
            if os.path.exists(filepath):
                os.remove(filepath)
            return False
    
    def process_song(self, song: Song) -> str:
        """Process a single song - search and download"""
        
        # Search
        task = self.search_all_sources_concurrent(song)
        
        if not task:
            with self.lock:
                self.failed_songs.append(song)
                self.fail_count += 1
            return f"[{song.number}] {song.song_name} - NOT FOUND"
        
        # Download
        success = self.download_single(task)
        
        if success:
            return f"[{song.number}] {song.song_name} - ✓ ({task.source} {task.quality})"
        else:
            with self.lock:
                self.failed_songs.append(song)
                self.fail_count += 1
            return f"[{song.number}] {song.song_name} - ✗ DOWNLOAD FAILED"
    
    def download_all(self, input_file: str = "songnames.txt"):
        """Main download with parallel processing"""
        print(f"\n{'='*75}")
        print("PARALLEL MULTI-SOURCE DOWNLOADER")
        print(f"Workers: {self.max_workers} | Sources: NaaSongs, SenSongs")
        print(f"{'='*75}\n")
        
        songs = self.parse_song_list(input_file)
        if not songs:
            print("No songs found!")
            return
        
        print(f"Processing {len(songs)} songs...\n")
        
        # Process with progress bar
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_song = {executor.submit(self.process_song, song): song for song in songs}
            
            with tqdm(total=len(songs), desc="Overall Progress", ncols=75) as pbar:
                for future in concurrent.futures.as_completed(future_to_song):
                    result = future.result()
                    pbar.update(1)
                    
                    # Show some results
                    if pbar.n % 20 == 0 or 'NOT FOUND' in result or 'FAILED' in result:
                        pbar.write(f"  {result}")
        
        # Summary
        print(f"\n{'='*75}")
        print("DOWNLOAD COMPLETE")
        print(f"{'='*75}")
        print(f"  Total: {len(songs)}")
        print(f"  ✓ Success: {self.success_count} ({self.success_count/len(songs)*100:.1f}%)")
        print(f"  ✗ Failed: {self.fail_count} ({self.fail_count/len(songs)*100:.1f}%)")
        print(f"{'='*75}\n")
        
        self.save_failed()
    
    def save_failed(self, filename: str = "failed_downloads.txt"):
        """Save failed songs"""
        if not self.failed_songs:
            print("✓ All songs downloaded!")
            if os.path.exists(filename):
                os.remove(filename)
            return
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# Failed Downloads - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Total failed: {len(self.failed_songs)}\n\n")
            for song in self.failed_songs:
                f.write(f"{song.original_line}\n")
        
        print(f"⚠ Saved {len(self.failed_songs)} failed songs to {filename}")


def main():
    import sys
    
    # Get input file
    input_file = "songnames.txt"
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    elif os.path.exists("failed_downloads.txt"):
        response = input("Use failed_downloads.txt? (y/n): ").strip().lower()
        if response == 'y':
            input_file = "failed_downloads.txt"
    
    # Workers
    workers = 8
    try:
        response = input(f"Number of parallel workers (default {workers}): ").strip()
        if response:
            workers = int(response)
    except:
        pass
    
    downloader = ParallelDownloader(max_workers=workers)
    downloader.download_all(input_file)


if __name__ == "__main__":
    main()
