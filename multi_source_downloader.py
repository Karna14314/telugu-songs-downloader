"""
Multi-Source Telugu Songs Downloader
Downloads songs from multiple sources: NaaSongs, SenSongs, mp3teluguwap
Tracks failures and supports retry from alternative sources
"""

import requests
from bs4 import BeautifulSoup
import os
import re
import time
from urllib.parse import urljoin, unquote
from tqdm import tqdm
from datetime import datetime
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple


@dataclass
class Song:
    number: int
    song_name: str
    movie_name: str
    original_line: str


@dataclass
class DownloadResult:
    success: bool
    source: str
    filepath: Optional[str]
    error: Optional[str]


class MultiSourceDownloader:
    def __init__(self, download_dir="downloads"):
        self.download_dir = download_dir
        self.failed_songs: List[Song] = []
        
        # Create download directory
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
        
        # Initialize sessions for each source
        self.sessions = {
            'naasongs': self._create_session(),
            'sensongs': self._create_session(),
            'teluguwap': self._create_session(),
        }
        
        # Source configurations
        self.sources = {
            'naasongs': {
                'base_url': 'https://naasongs.com.co',
                'enabled': True,
            },
            'sensongs': {
                'base_url': 'https://sensongsmp3.live',
                'enabled': True,
            },
        }
    
    def _create_session(self) -> requests.Session:
        """Create a configured requests session"""
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })
        return session
    
    def parse_song_list(self, filename: str) -> List[Song]:
        """Parse song list from file"""
        songs = []
        
        if not os.path.exists(filename):
            print(f"Error: {filename} not found!")
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
        """Clean text for URL usage"""
        return re.sub(r'[^\w\s-]', '', text).lower().strip().replace(' ', '-')
    
    # ============ NaaSongs Source ============
    def search_naasongs(self, song: Song) -> Optional[str]:
        """Search for song on NaaSongs"""
        base = self.sources['naasongs']['base_url']
        session = self.sessions['naasongs']
        
        clean_movie = self.clean_for_url(song.movie_name)
        clean_song = self.clean_for_url(song.song_name)
        
        # Try various movie page patterns
        patterns = [
            f"{clean_movie}-2026-songs.html",
            f"{clean_movie}-2026-songs-a.html",
            f"{clean_movie}-2026-songs-b.html",
            f"{clean_movie}-2025-songs.html",
            f"{clean_movie}-2025-songs-a.html",
            f"{clean_movie}-2024-songs.html",
            f"{clean_movie}-2024-songs-a.html",
            f"{clean_movie}-songs.html",
            f"{clean_movie}-songs-a.html",
            f"{clean_movie}-telugu-songs.html",
        ]
        
        for pattern in patterns:
            url = f"{base}/{pattern}"
            try:
                response = session.get(url, timeout=12)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    if song.song_name.lower() in soup.get_text().lower():
                        return url
            except:
                continue
        
        # Try song-specific pages
        song_patterns = [
            f"{clean_song}-song.html",
            f"{clean_song}-song-{clean_movie}.html",
        ]
        
        for pattern in song_patterns:
            url = f"{base}/{pattern}"
            try:
                response = session.get(url, timeout=12)
                if response.status_code == 200:
                    # Check if page has download links
                    soup = BeautifulSoup(response.content, 'html.parser')
                    if soup.find('a', href=lambda x: x and x.endswith('.mp3')):
                        return url
                    # Try to get movie page from song page
                    for link in soup.find_all('a', href=True):
                        href = link.get('href', '')
                        if 'songs' in href and href.endswith('.html'):
                            movie_url = urljoin(base, href)
                            try:
                                movie_response = session.get(movie_url, timeout=12)
                                if movie_response.status_code == 200:
                                    movie_soup = BeautifulSoup(movie_response.content, 'html.parser')
                                    if song.song_name.lower() in movie_soup.get_text().lower():
                                        return movie_url
                            except:
                                continue
            except:
                continue
        
        return None
    
    def extract_download_naasongs(self, page_url: str, song: Song) -> Optional[Dict]:
        """Extract download link from NaaSongs page"""
        session = self.sessions['naasongs']
        
        try:
            response = session.get(page_url, timeout=15)
            response.raise_for_status()
        except:
            return None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        song_variants = [
            song.song_name.lower(),
            song.song_name.lower().replace(' ', ''),
            re.sub(r'\(.*\)', '', song.song_name).lower().strip(),
        ]
        
        download_links = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if not href.endswith('.mp3'):
                continue
            
            text = link.get_text(strip=True).lower()
            parent = link.find_parent(['p', 'div', 'li', 'td'])
            parent_text = parent.get_text(strip=True).lower() if parent else ""
            
            matched = any(v in text or v in parent_text or v in href.lower() for v in song_variants)
            quality = "320kbps" if "320" in href or "320" in text else "128kbps"
            
            info = {'url': href, 'quality': quality, 'matched': matched}
            
            if matched:
                return info
            download_links.append(info)
        
        # Fallback: return first 320kbps or any available
        if download_links:
            kbps_320 = [l for l in download_links if l['quality'] == '320kbps']
            if kbps_320:
                return kbps_320[0]
            return download_links[0]
        
        return None
    
    # ============ SenSongs Source ============
    def search_sensongs(self, song: Song) -> Optional[str]:
        """Search for song on SenSongs"""
        base = self.sources['sensongs']['base_url']
        session = self.sessions['sensongs']
        
        clean_movie = self.clean_for_url(song.movie_name)
        clean_song = self.clean_for_url(song.song_name)
        
        # SenSongs URL patterns
        patterns = [
            f"{clean_movie}-2026-songs-download/",
            f"{clean_movie}-2026-songs-download-a/",
            f"{clean_movie}-2026-songs-download-b/",
            f"{clean_movie}-2025-songs-download/",
            f"{clean_movie}-2025-songs-download-a/",
            f"{clean_movie}-2024-songs-download/",
            f"{clean_movie}-2024-songs-download-a/",
            f"{clean_movie}-songs-download/",
            f"{clean_movie}-songs-download-a/",
            f"{clean_movie}-telugu-songs-download/",
        ]
        
        for pattern in patterns:
            url = f"{base}/{pattern}"
            try:
                response = session.get(url, timeout=12)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    page_text = soup.get_text().lower()
                    if song.song_name.lower() in page_text:
                        return url
            except:
                continue
        
        # Try song-specific page
        song_patterns = [
            f"{clean_song}-song-download/",
            f"{clean_song}-{clean_movie}-song-download/",
        ]
        
        for pattern in song_patterns:
            url = f"{base}/{pattern}"
            try:
                response = session.get(url, timeout=12)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    if soup.find('a', href=lambda x: x and x.endswith('.mp3')):
                        return url
            except:
                continue
        
        return None
    
    def extract_download_sensongs(self, page_url: str, song: Song) -> Optional[Dict]:
        """Extract download link from SenSongs page"""
        session = self.sessions['sensongs']
        
        try:
            response = session.get(page_url, timeout=15)
            response.raise_for_status()
        except:
            return None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        song_variants = [
            song.song_name.lower(),
            song.song_name.lower().replace(' ', ''),
            re.sub(r'\(.*\)', '', song.song_name).lower().strip(),
        ]
        
        download_links = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            if not href.endswith('.mp3'):
                continue
            
            text = link.get_text(strip=True).lower()
            parent = link.find_parent(['p', 'div', 'li', 'td'])
            parent_text = parent.get_text(strip=True).lower() if parent else ""
            
            matched = any(v in text or v in parent_text or v in href.lower() for v in song_variants)
            quality = "320kbps" if "320" in href or "320" in text else "128kbps"
            
            info = {'url': href, 'quality': quality, 'matched': matched}
            
            if matched:
                return info
            download_links.append(info)
        
        # Fallback
        if download_links:
            kbps_320 = [l for l in download_links if l['quality'] == '320kbps']
            if kbps_320:
                return kbps_320[0]
            return download_links[0]
        
        return None
    
    def download_file(self, url: str, filename: str, song: Song) -> DownloadResult:
        """Download file with progress tracking"""
        filepath = os.path.join(self.download_dir, filename)
        
        # Check if already exists
        if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
            return DownloadResult(True, 'cache', filepath, None)
        
        # Try each session
        for source_name, session in self.sessions.items():
            try:
                response = session.get(url, stream=True, timeout=60)
                response.raise_for_status()
                
                total_size = int(response.headers.get('content-length', 0))
                
                with open(filepath, 'wb') as f:
                    if total_size > 0:
                        with tqdm(total=total_size, unit='B', unit_scale=True, 
                                 desc=f"  Downloading", ncols=70) as pbar:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                                    pbar.update(len(chunk))
                    else:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                
                # Verify
                if os.path.getsize(filepath) < 1000:
                    os.remove(filepath)
                    continue
                
                return DownloadResult(True, source_name, filepath, None)
                
            except Exception as e:
                if os.path.exists(filepath):
                    os.remove(filepath)
                continue
        
        return DownloadResult(False, 'none', None, 'All download attempts failed')
    
    def try_download_song(self, song: Song) -> DownloadResult:
        """Try to download song from all sources"""
        print(f"\n[{song.number}] {song.song_name} - {song.movie_name}")
        
        sources_to_try = [
            ('naasongs', self.search_naasongs, self.extract_download_naasongs),
            ('sensongs', self.search_sensongs, self.extract_download_sensongs),
        ]
        
        for source_name, search_func, extract_func in sources_to_try:
            try:
                # Search
                page_url = search_func(song)
                if not page_url:
                    continue
                
                print(f"  [{source_name}] Found page")
                
                # Extract download
                download_info = extract_func(page_url, song)
                if not download_info:
                    continue
                
                print(f"  [{source_name}] Quality: {download_info['quality']}")
                
                # Create filename
                mp3_name = unquote(download_info['url'].split('/')[-1])
                if not mp3_name.endswith('.mp3'):
                    safe_song = re.sub(r'[^\w\s-]', '', song.song_name).strip()
                    safe_movie = re.sub(r'[^\w\s-]', '', song.movie_name).strip()
                    mp3_name = f"{safe_song} - {safe_movie}.mp3"
                
                mp3_name = re.sub(r'[<>:"/\\|?*]', '', mp3_name)
                if len(mp3_name) > 100:
                    mp3_name = mp3_name[:100]
                
                # Download
                result = self.download_file(download_info['url'], mp3_name, song)
                
                if result.success:
                    print(f"  ✓ Saved: {mp3_name} (from {result.source})")
                    return result
                    
            except Exception as e:
                print(f"  [{source_name}] Error: {e}")
                continue
        
        print(f"  ✗ Failed to download from all sources")
        self.failed_songs.append(song)
        return DownloadResult(False, 'none', None, 'All sources failed')
    
    def save_failed_songs(self, filename: str = "failed_downloads.txt"):
        """Save failed songs to file"""
        if not self.failed_songs:
            print(f"\n✓ All songs downloaded successfully!")
            if os.path.exists(filename):
                os.remove(filename)
            return
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# Failed Downloads - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Total failed: {len(self.failed_songs)}\n\n")
            for song in self.failed_songs:
                f.write(f"{song.original_line}\n")
        
        print(f"\n⚠ Failed downloads saved to: {filename}")
        print(f"   Total failed: {len(self.failed_songs)}")
    
    def download_songs(self, input_file: str = "songnames.txt"):
        """Main download function"""
        print(f"\n{'='*75}")
        print("Multi-Source Telugu Songs Downloader")
        print("Sources: NaaSongs, SenSongs, mp3teluguwap")
        print(f"{'='*75}\n")
        
        songs = self.parse_song_list(input_file)
        
        if not songs:
            print("No songs found!")
            return
        
        print(f"Found {len(songs)} songs to download\n")
        
        success_count = 0
        fail_count = 0
        
        for i, song in enumerate(songs, 1):
            result = self.try_download_song(song)
            
            if result.success:
                success_count += 1
            else:
                fail_count += 1
            
            # Progress every 10 songs
            if i % 10 == 0:
                print(f"\n  --- Progress: {i}/{len(songs)} songs processed ---")
                print(f"      Success: {success_count}, Failed: {fail_count}")
            
            time.sleep(0.3)  # Be respectful to servers
        
        # Summary
        print(f"\n{'='*75}")
        print("DOWNLOAD SUMMARY")
        print(f"{'='*75}")
        print(f"  Total: {len(songs)}")
        print(f"  ✓ Success: {success_count} ({success_count/len(songs)*100:.1f}%)")
        print(f"  ✗ Failed: {fail_count} ({fail_count/len(songs)*100:.1f}%)")
        print(f"\n  Downloaded to: {os.path.abspath(self.download_dir)}")
        print(f"{'='*75}\n")
        
        self.save_failed_songs("failed_downloads.txt")
    
    def retry_failed_songs(self, failed_file: str = "failed_downloads.txt"):
        """Retry downloading failed songs with alternative methods"""
        if not os.path.exists(failed_file):
            print(f"No failed downloads file: {failed_file}")
            return
        
        print(f"\n{'='*75}")
        print("RETRYING FAILED DOWNLOADS")
        print(f"{'='*75}\n")
        
        songs = self.parse_song_list(failed_file)
        
        if not songs:
            print("No failed songs to retry!")
            return
        
        print(f"Retrying {len(songs)} songs...\n")
        
        # Clear failed list for this retry
        self.failed_songs = []
        
        success_count = 0
        
        for song in songs:
            # Try with longer timeouts and more aggressive search
            result = self.try_download_song(song)
            
            if result.success:
                success_count += 1
            
            time.sleep(0.5)
        
        # Update failed file
        self.save_failed_songs(failed_file)
        
        print(f"\n{'='*75}")
        print("RETRY COMPLETE")
        print(f"  Recovered: {success_count}/{len(songs)}")
        print(f"  Still failed: {len(self.failed_songs)}")
        print(f"{'='*75}\n")


def main():
    downloader = MultiSourceDownloader(download_dir="downloads")
    
    # Check for failed downloads
    if os.path.exists("failed_downloads.txt"):
        print("\nPrevious failed downloads found!")
        print("1. Retry failed downloads only")
        print("2. Start fresh download from songnames.txt")
        print("3. Do both (retry then continue)")
        
        choice = input("\nEnter choice (1/2/3): ").strip()
        
        if choice == "1":
            downloader.retry_failed_songs()
        elif choice == "2":
            downloader.download_songs("songnames.txt")
        elif choice == "3":
            downloader.retry_failed_songs()
            if not downloader.failed_songs:
                print("\nAll recovered! Continuing with main list...")
                downloader.download_songs("songnames.txt")
    else:
        # Fresh download
        downloader.download_songs("songnames.txt")


if __name__ == "__main__":
    main()
