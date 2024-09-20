#!/usr/bin/python3
import argparse
import feedparser
import opml
import os
import requests
import signal
import sys
from threading import Event
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from pathlib import Path

# References
# https://dusty.phillips.codes/2018/08/13/python-loading-pathlib-paths-with-argparse/

# Globals
default_podcasts = [
    "https://www.patreon.com/rss/darknetdiaries?auth=AGjk3H83-m6SXXOSdN1Ewt3QuIrvU0i6",
    "https://darknetdiaries.com/feedfree.xml",
    "https://realpython.com/podcasts/rpp/feed",
    "https://feeds.megaphone.fm/darknetdiaries",
    "https://feeds.eff.org/howtofixtheinternet",
    "https://malicious.life/feed/podcast/",
    "https://headstuff.org/tag/fireside-podcast/feed/",
    "https://www.aclu.org/podcast/feed/",
    "https://feeds.soundcloud.com/users/soundcloud:users:40330678/sounds.rss",
    "http://www.2600.com/oth-broadband.xml",
    ]

# Define our rich console object
console = Console()

progress = Progress(
    TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
    BarColumn(bar_width=None),
    "[progress.percentage]{task.percentage:>3.1f}%",
    "•",
    DownloadColumn(),
    "•",
    TransferSpeedColumn(),
    "•",
    TimeRemainingColumn(),
)

# Define our event object
done_event = Event()

def handle_sigint(signum, frame):
    done_event.set()


signal.signal(signal.SIGINT, handle_sigint)


def parse_rss_url(rss_url: str) -> dict | None:
    ''' Parse RSS feed URL and return custom FeedParser Dict object '''
    feed = feedparser.parse(rss_url)

    if feed is not None:
        return feed
    else:
        return None


def format_text(text: str) -> str:
    ''' Replace unacceptable or illegal characters from episode title or podcast title '''

    # Target characters
    unaccepted = [
        ':',
        '-',
        '?',
        '+',
        '@',
        ',',
        '|',
        '[',
        ']',
        '"',
        '>',
        '<',
        '/',
        '\\',
        '*',
        '#',
        '%',
        '^',
    ]

    for char in text:
        for element in unaccepted:
            if char == element:
                text = text.replace(element, '')
                
    return text


def format_title(title: str) -> str:
    ''' Format the Podcast title for Pathlib '''

    if title == "At Liberty Podcast  American Civil Liberties Union":
        return "At Liberty Podcast American Civil Liberties Union"
    
    if title == "Darknet Diaries Bonus Episodes":
        return "Darknet Diaries"
    
    if title == "Fireside Podcast – HeadStuff":
        return "Fireside Podcast"

    else:
        return title


def map_files(directory: str | os.PathLike) -> list:
    ''' 
    Accept a directory and list all files underneath it 
    
    :directory: Pathlib absolute path object
    :returns: List of filenames
    '''

    file_list = []
    for child in directory.iterdir():
        file_list.append(child.name)

    return file_list


def generate_podcast_episode_urls(feed_dict: dict) -> dict:
    ''' Return list of filenames and URLs from list of episodes '''

    episode_dict = {}

    # .entries is easy way to access all individual episodes in an RSS feed
    for episode in feed_dict.entries:
        # .links usually has multiple links, a text/html link with description and a audio/mpeg with actual audio file
        for link in episode.links:
            if link['type'] == 'audio/mpeg':
                    # Format the filename by stripping non-compliant characters
                    filename = format_text(episode.title)
                    filename = filename + '.mp3'
                    url = link['href']
                    episode_dict.update({f'{url}': f'{filename}'})
    return episode_dict


def download_episode(download_path: str | os.PathLike, filename: str, url: str):
    ''' Download podcast episode '''

    # Print to console that we have a new episode to download
    console.print(f'[+] INFO - New episode, downloading [blue]{filename}[/blue]', style="bold green")
    # Use the RSS href value as our request URL and populate the response
    response = requests.get(url)
    # Establish the total size of the download for progress display
    content_size = int(response.headers["Content-Length"])

    # Use context manager to cleanly handle file open and close
    with open(download_path, 'wb') as f:
        # Use iter_content and pass chunk size to load the content in chunks instead of all at once in memory
        for chunk in response.iter_content(chunk_size=32768):
            # Write the chunk to our file handler
            f.write(chunk)


def check_directory(directory: str | os.PathLike) -> None or bool:
    ''' Verify the directory provided exists '''

    if directory.is_dir():
        return True
    else:
        return None


def make_directory(absolute_path: str | os.PathLike):
    ''' Create podcast directory '''

    try:
        absolute_path.mkdir()
    except NotADirectoryError as e:
        console.print(f'[!] Directory name {absolute_path} is invalid! {e}', style="bold red")
        return None
    except FileNotFoundError:
        console.print(f'[!] Parent directory was not found for provided folder name: {absolute_path}', style="bold yellow")
        return None


def parse_opml(file):
    ''' OPML file parser '''

    try:
        outline = opml.parse(file)
    except Exception as e:
        console.print(f"[!] ERROR - Encountered exception during OPML processing: {e}")
        return None
    
    return parse_outlines(outline)


def parse_outlines(outline) -> list:
    ''' Process OPML outline object '''

    # List of podcast URLs
    podcasts = []

    # Outline can have nested lists of other "outlines"
    for outlines in outline:
        # Enumerate the actual RSS feed entries in the outline group
        for outline_entry in outlines:
            podcasts.append(outline_entry.xmlUrl)
    
    return podcasts


def main():
    ''' Download all podcasts episodes not already downloaded '''

    parser = argparse.ArgumentParser(
        description="A simple command-line Podcast downloader",
        epilog="pipenv run python3 download_podcast_episodes.py C:\Podcasts -i sample.opml"
    )
    parser.add_argument("directory", type=Path, action="store", help="Parent directory for your local Podcast files, i.e. C:\Podcasts")
    parser.add_argument("--warnings", "-w", action="store_true", dest="warnings", help="Enable warning messages")
    parser.add_argument("--import", "-i", type=Path, action="store", dest="import_file", help="OPML file to import")
    parser.set_defaults(warnings=False)

    # Parse the arguments from CLI
    args = parser.parse_args()

    # Cleaner variable names
    parent_directory = args.directory
    warnings = args.warnings
    import_file = args.import_file

    # Print help to console and exit if parent directory was not provided by user
    if not parent_directory:
        parser.print_help()
        sys.exit(1)

    # Check if existing directory exists
    existing_directory = check_directory(parent_directory)

    # If the existing directory is None, report to console and exit
    if existing_directory is None:
        console.print(f'[!] Directory {existing_directory} supplied is not a valid existing directory', style="bold yellow")
        sys.exit(1)
    
    # If an opml file is provided to import instead, parse and use this instead of default podcast URL list
    if import_file:
        # Parse the OPML file and either return None or the outline object
        podcasts = parse_opml(import_file)
    else:
        # Use global list if no import flag provided
        podcasts = default_podcasts

    # Iterate over all of the defined podcast RSS URLs
    for podcast in podcasts:
        # Process the RSS feed and get a list of entries for the podcast
        feed = parse_rss_url(podcast)

        # If feed is None, report to console and exit
        if feed is None:
            console.print(f'[!] Error encountered, malformed RSS feed, no feed found for URL: {podcast}!', style="bold red")
            continue

        # Define a directory name as a string from the feed title
        try:
            podcast_directory_name = feed['feed']['title']
        except KeyError:
            console.print(f'[!] Encountered KeyError, problem with RSS feed {podcast}', style="bold red")
        except Exception as e:
            console.print(f'[!] Unknown exception identified with RSS feed {podcast}, {e}', style="bold red")
    
        # Strip characters from podcast directory name
        tmp_directory = format_text(podcast_directory_name)
        podcast_directory = format_title(tmp_directory)

        # Create a Pathlib path object for the directory (not an absolute path yet)
        podcast_directory = Path(podcast_directory)

        # Join the podcast directory name with parent provided by user
        podcast_absolute_path = parent_directory.joinpath(podcast_directory)
        #console.print(f'[+] Podcast absolute path: {podcast_absolute_path}', style="bold yellow")

        # Check if the new podcast directory already exists or not
        is_existing = check_directory(podcast_absolute_path)
        #console.print(f'[+] Does the {podcast_directory} already exist? {is_existing}', style="bold yellow")

        # If the podcast directory does not exist, create it
        if is_existing is None:
            make_directory(podcast_absolute_path)
        
        # Generate a list of all the files in the existing directory
        existing_files = map_files(podcast_absolute_path)

        # Generate list of tuples with feed URL and filename
        episodes = generate_podcast_episode_urls(feed)

        # Generate list of tuples that we do not already have downloaded
        new_episodes = {}
        for item in episodes.items():
            if item[1] in existing_files:
                if warnings:
                    console.print(f'[!] File [cyan]{item[1]}[/cyan] already downloaded', style="bold yellow")
            else:
                new_episodes[item[0]] = item[1]

        # Iterate over new episodes and create our download path objects and download
        for item in new_episodes.items():
            # Generate joined path for output
            download_path = podcast_absolute_path.joinpath(item[1])

            # Download the episode by supplying the fully qualified path on the filesystem, the filename, and the URL
            download_episode(download_path, item[1], item[0])


if __name__ == "__main__":
    main()