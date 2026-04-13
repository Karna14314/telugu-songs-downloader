"""
NaaSongs Downloader Script - Specific Songs Version
Downloads specific songs from songnames.txt with failed download tracking
"""

import requests
from bs4 import BeautifulSoup
import os
import re
import time
from urllib.parse import urljoin, unquote, quote
from tqdm import tqdm
from datetime import datetime


class NaaSongsDownloader:
    def __init__(self, base_url="https://naasongs.com.co", download_dir="downloads"):
        self.base_url = base_url
        self.download_dir = download_dir
        self.failed_songs = []
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })
        
        # Create download directory
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
    
    def parse_song_list(self, filename="songnames.txt"):
        """Parse song list from file with format: number. Song Name - Movie Name"""
        songs = []
        
        if not os.path.exists(filename):
            print(f"Error: {filename} not found!")
            return songs
        
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                # Parse format: "1. Song Name - Movie Name" or "206. Song - Movie"
                match = re.match(r'^(\d+)\.\s*(.+?)\s*-\s*(.+)$', line)
                if match:
                    number = match.group(1)
                    song_name = match.group(2).strip()
                    movie_name = match.group(3).strip()
                    
                    songs.append({
                        'number': int(number),
                        'song_name': song_name,
                        'movie_name': movie_name,
                        'original_line': line
                    })
        
        return songs
    
    def get_movie_page_from_song_page(self, song_page_url):
        """Extract movie page URL from a song page - looks for 'Download' links to movie page"""
        try:
            response = self.session.get(song_page_url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # First look for links with 'Download' text that point to movie pages
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                text = link.get_text(strip=True).lower()
                
                # Look for "Download" link that points to a movie songs page
                if 'download' in text and 'songs' in href and href.endswith('.html'):
                    return urljoin(self.base_url, href)
            
            # Then look for any link with 'songs' in URL
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                if 'songs' in href and href.endswith('.html'):
                    # Make sure it's a naasongs link
                    if 'naasongs' in href or href.startswith('/'):
                        return urljoin(self.base_url, href)
                    
        except:
            pass
        return None
    
    def search_song(self, song_name, movie_name):
        """Search for a song on naasongs using multiple strategies"""
        
        # Clean names for URL construction
        clean_movie = re.sub(r'[^\w\s-]', '', movie_name).lower().strip().replace(' ', '-')
        clean_song = re.sub(r'[^\w\s-]', '', song_name).lower().strip().replace(' ', '-')
        
        # Strategy 1: Try direct movie page URL patterns
        movie_patterns = [
            f"{clean_movie}-2026-songs.html",
            f"{clean_movie}-2026-songs-a.html", 
            f"{clean_movie}-2026-songs-b.html",
            f"{clean_movie}-2026-songs-c.html",
            f"{clean_movie}-2026-songs-d.html",
            f"{clean_movie}-2025-songs.html",
            f"{clean_movie}-2025-songs-a.html",
            f"{clean_movie}-2025-songs-b.html",
            f"{clean_movie}-2025-songs-c.html",
            f"{clean_movie}-2024-songs.html",
            f"{clean_movie}-2024-songs-a.html",
            f"{clean_movie}-songs.html",
            f"{clean_movie}-songs-a.html",
            f"{clean_movie}-telugu-songs.html",
            f"{clean_movie}-telugu-songs-a.html",
        ]
        
        # Try movie pages first
        for variant in movie_patterns:
            url = urljoin(self.base_url, variant)
            try:
                response = self.session.get(url, timeout=12)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    page_text = soup.get_text().lower()
                    
                    # Check if song is on this movie page
                    if song_name.lower() in page_text or self._song_name_match(song_name, page_text):
                        return url
            except:
                continue
        
        # Strategy 2: Try individual song page, then extract movie page
        song_patterns = [
            f"{clean_song}-song.html",
            f"{clean_song}-song-from-{clean_movie}.html",
            f"{clean_song}.html",
            f"{clean_song}-song-{clean_movie}.html",
        ]
        
        for variant in song_patterns:
            url = urljoin(self.base_url, variant)
            try:
                response = self.session.get(url, timeout=12)
                if response.status_code == 200:
                    # Try to get movie page from song page
                    movie_url = self.get_movie_page_from_song_page(url)
                    if movie_url:
                        # Verify the movie page has our song
                        movie_response = self.session.get(movie_url, timeout=12)
                        if movie_response.status_code == 200:
                            soup = BeautifulSoup(movie_response.content, 'html.parser')
                            page_text = soup.get_text().lower()
                            if song_name.lower() in page_text or self._song_name_match(song_name, page_text):
                                return movie_url
                    
                    # If no movie page, check if this page has direct download links
                    soup = BeautifulSoup(response.content, 'html.parser')
                    if soup.find('a', href=lambda x: x and x.endswith('.mp3')):
                        return url
            except:
                continue
        
        return None
    
    def _song_name_match(self, song_name, page_text):
        """Check if song name appears in page text (with variations)"""
        song_lower = song_name.lower()
        # Remove common words for fuzzy matching
        simplified = re.sub(r'\(.*\)|song|full|promo|the', '', song_lower).strip()
        return simplified in page_text or song_lower in page_text
    
    def find_song_on_movie_page(self, movie_url, song_name):
        """Find specific song download link on a movie page"""
        try:
            response = self.session.get(movie_url, timeout=20)
            response.raise_for_status()
        except Exception as e:
            print(f"  Error fetching movie page: {e}")
            return None
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Create multiple variants of song name for matching
        song_variants = [
            song_name.lower(),
            song_name.lower().replace(' ', ''),
            re.sub(r'\(.*\)', '', song_name).lower().strip(),
            song_name.lower().replace('the', '').replace('song', '').strip(),
        ]
        
        # First pass: look for exact match
        download_links = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            text = link.get_text(strip=True).lower()
            
            if href.endswith('.mp3'):
                # Get parent text for context
                parent = link.find_parent(['p', 'div', 'li', 'td'])
                parent_text = parent.get_text(strip=True).lower() if parent else ""
                
                # Check for song match in text, parent text, or URL
                matched = False
                for variant in song_variants:
                    if (variant in text or 
                        variant in parent_text or 
                        variant.replace(' ', '') in parent_text or
                        variant in href.lower()):
                        matched = True
                        break
                
                quality = "320kbps" if "320" in href or "320" in text else "128kbps"
                
                download_info = {
                    'url': href,
                    'quality': quality,
                    'song_name': song_name,
                    'matched': matched,
                    'context': parent_text[:100]
                }
                
                if matched:
                    return download_info
                
                download_links.append(download_info)
        
        # If no specific match found, return the first 320kbps link as fallback
        # (assuming user wants any song from the movie if specific not found)
        if download_links:
            # Sort by quality preference
            kbps_320 = [l for l in download_links if l['quality'] == '320kbps']
            if kbps_320:
                return kbps_320[0]
            return download_links[0]
        
        return None
    
    def download_file(self, url, filename, song_info):
        """Download a file with progress bar and tracking"""
        try:
            response = self.session.get(url, stream=True, timeout=60)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            filepath = os.path.join(self.download_dir, filename)
            
            # Check if file already exists and has content
            if os.path.exists(filepath) and os.path.getsize(filepath) > 1000:
                print(f"  ✓ Already exists: {filename}")
                return filepath
            
            # Download with progress
            with open(filepath, 'wb') as f:
                if total_size > 0:
                    with tqdm(total=total_size, unit='B', unit_scale=True, desc=f"  Downloading", ncols=70) as pbar:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                pbar.update(len(chunk))
                else:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            
            # Verify download
            if os.path.getsize(filepath) < 1000:
                os.remove(filepath)
                raise Exception("Downloaded file too small (likely failed)")
            
            return filepath
            
        except Exception as e:
            print(f"  ✗ Download failed: {e}")
            self.failed_songs.append(song_info)
            return None
    
    def clean_filename(self, filename):
        """Clean filename for saving"""
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        if len(filename) > 100:
            filename = filename[:100]
        return filename
    
    def save_failed_songs(self, filename="failed_downloads.txt"):
        """Save failed songs to file for retry"""
        if not self.failed_songs:
            print(f"\n✓ All songs downloaded successfully! No failures to save.")
            # Clear file if exists
            if os.path.exists(filename):
                os.remove(filename)
            return
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# Failed Downloads - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Total failed: {len(self.failed_songs)}\n\n")
            for song in self.failed_songs:
                f.write(f"{song['original_line']}\n")
        
        print(f"\n⚠ Failed downloads saved to: {filename}")
        print(f"   Total failed: {len(self.failed_songs)}")
    
    def download_specific_songs(self, input_file="songnames.txt", quality_preference="320kbps"):
        """Download songs from input file"""
        print(f"\n{'='*70}")
        print("NaaSongs Downloader - Specific Songs Edition")
        print(f"{'='*70}\n")
        
        # Parse song list
        songs = self.parse_song_list(input_file)
        
        if not songs:
            print("No songs found in input file!")
            return
        
        print(f"Found {len(songs)} songs to download from {input_file}\n")
        
        success_count = 0
        fail_count = 0
        skip_count = 0
        
        for i, song in enumerate(songs, 1):
            print(f"\n[{i}/{len(songs)}] {song['song_name']} - {song['movie_name']}")
            
            # Search for the song
            page_url = self.search_song(song['song_name'], song['movie_name'])
            
            if not page_url:
                print(f"  ✗ Could not find song page")
                self.failed_songs.append(song)
                fail_count += 1
                continue
            
            print(f"  Found page: {page_url}")
            
            # Get download link
            download_info = self.find_song_on_movie_page(page_url, song['song_name'])
            
            if not download_info:
                print(f"  ✗ No download link found on page")
                self.failed_songs.append(song)
                fail_count += 1
                continue
            
            # Create filename
            mp3_name = unquote(download_info['url'].split('/')[-1])
            if not mp3_name.endswith('.mp3'):
                safe_song = re.sub(r'[^\w\s-]', '', song['song_name']).strip()
                safe_movie = re.sub(r'[^\w\s-]', '', song['movie_name']).strip()
                mp3_name = f"{safe_song} - {safe_movie}.mp3"
            
            mp3_name = self.clean_filename(mp3_name)
            
            print(f"  Quality: {download_info['quality']}")
            
            # Download
            filepath = self.download_file(download_info['url'], mp3_name, song)
            
            if filepath:
                print(f"  ✓ Saved: {mp3_name}")
                success_count += 1
            else:
                fail_count += 1
            
            # Small delay to be respectful to server
            time.sleep(0.5)
        
        # Summary
        print(f"\n{'='*70}")
        print("DOWNLOAD SUMMARY")
        print(f"{'='*70}")
        print(f"  Total songs: {len(songs)}")
        print(f"  ✓ Success: {success_count}")
        print(f"  ✗ Failed: {fail_count}")
        print(f"  → Skipped (already exists): {skip_count}")
        print(f"\n  Files saved to: {os.path.abspath(self.download_dir)}")
        print(f"{'='*70}\n")
        
        # Save failed songs
        self.save_failed_songs("failed_downloads.txt")
    
    def retry_failed_songs(self, failed_file="failed_downloads.txt", quality_preference="320kbps"):
        """Retry downloading failed songs from previous run"""
        if not os.path.exists(failed_file):
            print(f"No failed downloads file found: {failed_file}")
            return
        
        print(f"\n{'='*70}")
        print("RETRYING FAILED DOWNLOADS")
        print(f"{'='*70}\n")
        
        # Reset failed list for this retry run
        self.failed_songs = []
        
        # Load failed songs
        songs = self.parse_song_list(failed_file)
        
        if not songs:
            print("No failed songs to retry!")
            return
        
        print(f"Retrying {len(songs)} failed songs...\n")
        
        for i, song in enumerate(songs, 1):
            print(f"\n[Retry {i}/{len(songs)}] {song['song_name']} - {song['movie_name']}")
            
            # Try alternative search strategies
            page_url = self.search_song(song['song_name'], song['movie_name'])
            
            if not page_url:
                # Try simplified movie name
                simple_movie = re.sub(r'[^\w\s]', '', song['movie_name']).strip()
                page_url = self.search_song(song['song_name'], simple_movie)
            
            if not page_url:
                print(f"  ✗ Still could not find")
                self.failed_songs.append(song)
                continue
            
            print(f"  Found: {page_url}")
            
            download_info = self.find_song_on_movie_page(page_url, song['song_name'])
            
            if not download_info:
                print(f"  ✗ Still no download link")
                self.failed_songs.append(song)
                continue
            
            mp3_name = unquote(download_info['url'].split('/')[-1])
            if not mp3_name.endswith('.mp3'):
                safe_song = re.sub(r'[^\w\s-]', '', song['song_name']).strip()
                safe_movie = re.sub(r'[^\w\s-]', '', song['movie_name']).strip()
                mp3_name = f"{safe_song} - {safe_movie}.mp3"
            
            mp3_name = self.clean_filename(mp3_name)
            
            filepath = self.download_file(download_info['url'], mp3_name, song)
            
            if filepath:
                print(f"  ✓ Retry successful: {mp3_name}")
            else:
                print(f"  ✗ Retry failed")
                self.failed_songs.append(song)
            
            time.sleep(0.3)
        
        # Update failed file
        self.save_failed_songs(failed_file)
        
        print(f"\n{'='*70}")
        print("RETRY COMPLETE")
        remaining = len(self.failed_songs)
        recovered = len(songs) - remaining
        print(f"  Recovered: {recovered}")
        print(f"  Still failed: {remaining}")
        print(f"{'='*70}\n")


def main():
    downloader = NaaSongsDownloader(download_dir="downloads")
    
    # Check if we should retry failed downloads or start fresh
    if os.path.exists("failed_downloads.txt"):
        print("\nPrevious failed downloads found!")
        print("1. Retry failed downloads only")
        print("2. Start fresh (download all from songnames.txt)")
        print("3. Do both (retry then continue with remaining)")
        
        choice = input("\nEnter choice (1/2/3): ").strip()
        
        if choice == "1":
            downloader.retry_failed_songs()
        elif choice == "2":
            downloader.download_specific_songs("songnames.txt")
        elif choice == "3":
            downloader.retry_failed_songs()
            # Remove failed file if empty
            if not downloader.failed_songs:
                print("\nAll failed songs recovered! Continuing with main list...")
                downloader.download_specific_songs("songnames.txt")
    else:
        # Fresh run
        downloader.download_specific_songs("songnames.txt")


if __name__ == "__main__":
    main()

