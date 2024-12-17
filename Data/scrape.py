import os
import re
import requests
from bs4 import BeautifulSoup
import pandas as pd

# --- Configuration ---
BASE_URL_TEMPLATE = "https://budgetoffice.gov.ng/index.php/resources/internal-resources/budget-documents/{year}-budget"
PAGE_PARAMS = "?layout=columns&start={}"  # Pagination URL pattern
DATA_DIR = "data"  # Base directory to save data
START_INDEX = 0  # Pagination start
STEP = 20         # Pagination step

# --- Utility Functions ---

def is_valid_pdf_url(href):
    """Check if a link is a PDF file."""
    return href and re.search(r'\.pdf$', href, re.IGNORECASE)

def get_absolute_url(base_url, link):
    """Convert relative URL to absolute URL."""
    return requests.compat.urljoin(base_url, link)

def extract_pdf_metadata(file_path):
    """Extract metadata from a PDF file."""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(file_path)
        metadata = reader.metadata
        return {
            "title": metadata.title if metadata and metadata.title else "N/A",
            "author": metadata.author if metadata and metadata.author else "N/A",
            "subject": metadata.subject if metadata and metadata.subject else "N/A",
            "created_date": metadata.creation_date if metadata else "N/A",
            "modified_date": metadata.modification_date if metadata else "N/A",
            "num_pages": len(reader.pages),
        }
    except Exception as e:
        print(f"Failed to extract metadata: {e}")
        return {}

def download_pdf(pdf_url, save_dir):
    """Download a PDF file and return its file path and size."""
    os.makedirs(save_dir, exist_ok=True)
    file_name = pdf_url.split("/")[-1]
    file_path = os.path.join(save_dir, file_name)
    
    try:
        with requests.get(pdf_url, stream=True) as response:
            response.raise_for_status()
            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024):
                    f.write(chunk)
        file_size = os.path.getsize(file_path) / 1024  # File size in KB
        print(f"Downloaded: {file_name} ({file_size:.2f} KB)")
        return file_path, file_size
    except Exception as e:
        print(f"Failed to download {pdf_url}: {e}")
        return None, 0

def scrape_pdfs_for_year(year):
    """Scrape PDFs and save metadata for a specific year."""
    base_url = BASE_URL_TEMPLATE.format(year=year)
    save_dir = os.path.join(DATA_DIR, str(year))
    metadata_file = os.path.join(save_dir, f"metadata_{year}.csv")
    visited = set()
    pdf_data = []

    def crawl_page(url, start_index):
        if url in visited:
            return
        print(f"Visiting: {url}")
        visited.add(url)

        try:
            response = requests.get(url)
            soup = BeautifulSoup(response.content, "html.parser")

            # Find and download all PDF links
            for a_tag in soup.find_all("a", href=True):
                pdf_url = get_absolute_url(base_url, a_tag["href"])
                if is_valid_pdf_url(pdf_url) and pdf_url not in visited:
                    visited.add(pdf_url)
                    file_path, file_size = download_pdf(pdf_url, save_dir)
                    if file_path:
                        metadata = extract_pdf_metadata(file_path)
                        pdf_data.append({
                            "name": os.path.basename(file_path),
                            "url": pdf_url,
                            "size_kb": f"{file_size:.2f}",
                            **metadata
                        })

            # Handle pagination
            next_page_url = f"{base_url}{PAGE_PARAMS.format(start_index + STEP)}"
            if next_page_url not in visited:
                crawl_page(next_page_url, start_index + STEP)

        except Exception as e:
            print(f"Failed to process page {url}: {e}")

    # Start crawling the first page
    crawl_page(base_url + PAGE_PARAMS.format(START_INDEX), START_INDEX)

    # Save metadata to a CSV file
    if pdf_data:
        df = pd.DataFrame(pdf_data)
        df.to_csv(metadata_file, index=False)
        print(f"Metadata saved to {metadata_file}")
    else:
        print(f"No PDFs found for {year}.")

# --- Main Function ---

def scrape_budgets_by_year(years):
    """Scrape budget PDFs and metadata for multiple years."""
    os.makedirs(DATA_DIR, exist_ok=True)
    for year in years:
        print(f"\n--- Scraping Budget Documents for Year: {year} ---")
        scrape_pdfs_for_year(year)

if __name__ == "__main__":
    # List of years to scrape
    YEARS = list(range(2009, 2025))  # From 2009 to 2024
    scrape_budgets_by_year(YEARS)
