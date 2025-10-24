#!/usr/bin/env python3
"""
Sea Ice Image Downloader
Downloads Arctic sea ice images from various sources for web visualization

Usage:
    python download_seaice.py --years 2017 2021 2024 --output ./public/images/sea-ice/
    python download_seaice.py --config custom_config.json
    python download_seaice.py --source gibs --layer MODIS_Terra_Sea_Ice_Extent
"""

import requests
import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
import time
from typing import Dict, List, Optional, Tuple
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SeaIceDownloader:
    """Flexible sea ice image downloader supporting multiple sources"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'SeaIceDownloader/1.0 (Research Project)'
        })
        
        # Default configurations for different sources
        self.sources = {
            'gibs': {
                'name': 'NASA GIBS',
                'base_url': 'https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi',
                'format': 'image/png',
                'layers': {
                    'sea_ice_extent': 'MODIS_Terra_Sea_Ice_Extent',
                    'sea_ice_aqua': 'MODIS_Aqua_Sea_Ice_Extent',
                    'amsr2': 'AMSR2_Sea_Ice_Concentration_12km',
                    'nsidc': 'NSIDC_Sea_Ice_Index_Concentration'
                }
            },
            'nsidc': {
                'name': 'NSIDC Sea Ice Charts', 
                'base_url': 'https://seaice.uni-bremen.de/data/amsr2/asi_daygrid_swath/n6250',
                'format': 'image/png'
            },
            'noaa': {
                'name': 'NOAA Ice Charts',
                'base_url': 'https://www.natice.noaa.gov/products/weekly_products/arctic_weekly',
                'format': 'image/png'
            }
        }

    def build_gibs_url(self, 
                       layer: str, 
                       date: str, 
                       bbox: Tuple[float, float, float, float] = (-180, 60, 180, 90),
                       width: int = 1024, 
                       height: int = 512) -> str:
        """Build NASA GIBS WMS URL"""
        params = {
            'SERVICE': 'WMS',
            'REQUEST': 'GetMap',
            'VERSION': '1.1.1',  # Use 1.1.1 for better compatibility
            'LAYERS': layer,
            'STYLES': '',
            'FORMAT': 'image/png',
            'TRANSPARENT': 'true',
            'SRS': 'EPSG:4326',
            'BBOX': f'{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}',
            'WIDTH': str(width),
            'HEIGHT': str(height),
            'TIME': date
        }
        
        url = f"{self.sources['gibs']['base_url']}?{urlencode(params)}"
        logger.info(f"Built GIBS URL: {url}")
        return url

    def build_nsidc_url(self, date: str) -> str:
        """Build NSIDC Bremen URL"""
        dt = datetime.strptime(date, '%Y-%m-%d')
        year = dt.year
        month = dt.strftime('%b').lower()
        date_str = dt.strftime('%Y%m%d')
        
        url = f"{self.sources['nsidc']['base_url']}/{year}/{month}/asi-AMSR2-n6250-{date_str}-v5.4.png"
        logger.info(f"Built NSIDC URL: {url}")
        return url

    def build_noaa_url(self, date: str) -> str:
        """Build NOAA Arctic Chart URL"""
        dt = datetime.strptime(date, '%Y-%m-%d')
        year = dt.year
        date_str = dt.strftime('%Y%m%d')
        
        url = f"{self.sources['noaa']['base_url']}/{year}/arctic{date_str}.png"
        logger.info(f"Built NOAA URL: {url}")
        return url

    def download_image(self, 
                      url: str, 
                      output_path: Path, 
                      max_retries: int = 3) -> bool:
        """Download image with retry logic"""
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Downloading: {url} (attempt {attempt + 1}/{max_retries})")
                
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                
                # Check if response is actually an image
                content_type = response.headers.get('content-type', '')
                if not content_type.startswith('image/'):
                    logger.warning(f"Response is not an image: {content_type}")
                    if attempt == max_retries - 1:
                        return False
                    continue
                
                # Save image
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'wb') as f:
                    f.write(response.content)
                
                logger.info(f"Successfully downloaded: {output_path}")
                return True
                
            except requests.exceptions.RequestException as e:
                logger.error(f"Download failed (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    
        return False

    def download_seaice_year(self, 
                            year: int,
                            month: int = 3,
                            day: int = 1,
                            output_dir: Path = Path("./public/images/sea-ice"),
                            source: str = "gibs",
                            layer: str = "sea_ice_extent") -> Dict[str, bool]:
        """Download sea ice data for a specific year"""
        
        date_str = f"{year}-{month:02d}-{day:02d}"
        results = {}
        
        # Try multiple sources/layers
        sources_to_try = []
        
        if source == "gibs":
            # Try multiple GIBS layers
            for layer_name, layer_id in self.sources['gibs']['layers'].items():
                if layer == "all" or layer == layer_name:
                    url = self.build_gibs_url(layer_id, date_str)
                    filename = f"ice-{year}-{month:02d}-{day:02d}-{layer_name}.png"
                    sources_to_try.append((url, filename, f"GIBS-{layer_name}"))
        
        elif source == "nsidc":
            url = self.build_nsidc_url(date_str)
            filename = f"ice-{year}-{month:02d}-{day:02d}-nsidc.png"
            sources_to_try.append((url, filename, "NSIDC"))
            
        elif source == "noaa":
            url = self.build_noaa_url(date_str)
            filename = f"ice-{year}-{month:02d}-{day:02d}-noaa.png"
            sources_to_try.append((url, filename, "NOAA"))
            
        elif source == "all":
            # Try all sources
            sources_to_try.extend([
                (self.build_gibs_url(self.sources['gibs']['layers']['sea_ice_extent'], date_str),
                 f"ice-{year}-{month:02d}-{day:02d}-gibs.png", "GIBS"),
                (self.build_nsidc_url(date_str),
                 f"ice-{year}-{month:02d}-{day:02d}-nsidc.png", "NSIDC"),
                (self.build_noaa_url(date_str),
                 f"ice-{year}-{month:02d}-{day:02d}-noaa.png", "NOAA")
            ])
        
        # Download from each source
        for url, filename, source_name in sources_to_try:
            output_path = output_dir / filename
            success = self.download_image(url, output_path)
            results[f"{year}-{source_name}"] = success
            
            if success:
                # Create symlink with simple name for StaticSeaIceScene compatibility
                simple_name = output_dir / f"ice-{year}-{month:02d}-{day:02d}.png"
                if not simple_name.exists():
                    try:
                        simple_name.symlink_to(filename)
                        logger.info(f"Created symlink: {simple_name} -> {filename}")
                    except OSError:
                        # Fallback: copy file if symlink fails (Windows)
                        import shutil
                        shutil.copy2(output_path, simple_name)
                        logger.info(f"Copied file: {simple_name}")
        
        return results

    def download_batch(self, config: Dict) -> Dict:
        """Download batch of images based on configuration"""
        
        results = {}
        years = config.get('years', [2017, 2021, 2024])
        output_dir = Path(config.get('output_dir', './public/images/sea-ice'))
        source = config.get('source', 'gibs')
        layer = config.get('layer', 'sea_ice_extent')
        
        logger.info(f"Starting batch download for years: {years}")
        logger.info(f"Output directory: {output_dir}")
        logger.info(f"Source: {source}, Layer: {layer}")
        
        for year in years:
            logger.info(f"\n--- Downloading data for {year} ---")
            year_results = self.download_seaice_year(
                year=year,
                output_dir=output_dir,
                source=source,
                layer=layer
            )
            results.update(year_results)
            
            # Small delay between years
            time.sleep(1)
        
        return results

    def create_fallback_images(self, output_dir: Path):
        """Create fallback SVG images if downloads fail"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            import io
            
            logger.info("Creating fallback images...")
            
            for year in [2017, 2021, 2024]:
                # Create simple visualization showing ice coverage trend
                ice_coverage = 0.8 if year == 2017 else (0.6 if year == 2021 else 0.4)
                
                # Create image
                img = Image.new('RGBA', (1024, 512), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                
                # Draw ice coverage
                ice_color = (173, 216, 230, int(200 * ice_coverage))  # Light blue
                draw.ellipse([
                    512 - 400 * ice_coverage, 100 - 150 * ice_coverage,
                    512 + 400 * ice_coverage, 100 + 150 * ice_coverage
                ], fill=ice_color)
                
                # Add year label
                try:
                    font = ImageFont.truetype("arial.ttf", 36)
                except:
                    font = ImageFont.load_default()
                
                draw.text((50, 50), f"Sea Ice {year}", fill=(255, 255, 255, 255), font=font)
                draw.text((50, 90), f"Coverage: {int(ice_coverage * 100)}%", 
                         fill=(255, 255, 255, 200), font=font)
                
                # Save
                output_path = output_dir / f"ice-{year}-03-01-fallback.png"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                img.save(output_path, 'PNG')
                logger.info(f"Created fallback image: {output_path}")
                
        except ImportError:
            logger.warning("PIL not available, skipping fallback image creation")

def main():
    parser = argparse.ArgumentParser(description='Download sea ice images for visualization')
    parser.add_argument('--years', nargs='+', type=int, default=[2017, 2021, 2024],
                       help='Years to download (default: 2017 2021 2024)')
    parser.add_argument('--output', type=str, default='./public/images/sea-ice',
                       help='Output directory (default: ./public/images/sea-ice)')
    parser.add_argument('--source', choices=['gibs', 'nsidc', 'noaa', 'all'], 
                       default='gibs', help='Data source (default: gibs)')
    parser.add_argument('--layer', type=str, default='sea_ice_extent',
                       help='Layer type for GIBS (default: sea_ice_extent)')
    parser.add_argument('--config', type=str, help='JSON config file')
    parser.add_argument('--create-fallback', action='store_true',
                       help='Create fallback images if downloads fail')
    
    args = parser.parse_args()
    
    downloader = SeaIceDownloader()
    
    # Load configuration
    if args.config and os.path.exists(args.config):
        with open(args.config, 'r') as f:
            config = json.load(f)
        logger.info(f"Loaded config from {args.config}")
    else:
        config = {
            'years': args.years,
            'output_dir': args.output,
            'source': args.source,
            'layer': args.layer
        }
    
    # Download images
    results = downloader.download_batch(config)
    
    # Report results
    success_count = sum(1 for success in results.values() if success)
    total_count = len(results)
    
    logger.info(f"\n--- Download Summary ---")
    logger.info(f"Successful: {success_count}/{total_count}")
    
    for key, success in results.items():
        status = "✓" if success else "✗"
        logger.info(f"{status} {key}")
    
    # Create fallback images if requested or if all downloads failed
    if args.create_fallback or success_count == 0:
        downloader.create_fallback_images(Path(config['output_dir']))
    
    # Save config for future reference
    config_path = Path(config['output_dir']) / 'download_config.json'
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w') as f:
        json.dump({**config, 'results': results, 'timestamp': datetime.now().isoformat()}, f, indent=2)
    
    logger.info(f"Saved configuration to: {config_path}")

if __name__ == "__main__":
    main()

# Example usage and configuration examples:
"""
# Basic usage
python download_seaice.py

# Custom years and output
python download_seaice.py --years 2015 2020 2023 --output ./assets/ice-data/

# Try all sources
python download_seaice.py --source all

# Use config file
echo '{
  "years": [2017, 2021, 2024],
  "output_dir": "./public/images/sea-ice",
  "source": "gibs",
  "layer": "all",
  "bbox": [-180, 60, 180, 90],
  "resolution": {"width": 2048, "height": 1024}
}' > seaice_config.json

python download_seaice.py --config seaice_config.json

# For other data types, extend the sources dictionary:
downloader.sources['custom'] = {
    'name': 'Custom Data Source',
    'base_url': 'https://your-api.com/data',
    'format': 'image/png'
}
"""