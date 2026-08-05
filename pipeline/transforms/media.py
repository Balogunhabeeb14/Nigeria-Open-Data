"""
pipeline/transforms/media.py
=============================
Media optimization transformers.
Handles image conversion to WebP and audio compression.
"""
from __future__ import annotations
import os
import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

# Proactively try to import PIL for image processing
try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    logger.warning("Pillow library is not installed. Image transformations will fall back to raw copies.")

def optimize_image(local_input_path: str, local_output_path: str, max_width: int = 1200, quality: int = 80) -> bool:
    """Converts image to WebP and resizes if it exceeds max_width."""
    if not HAS_PILLOW:
        shutil.copy2(local_input_path, local_output_path)
        return False
        
    try:
        with Image.open(local_input_path) as img:
            # Maintain aspect ratio
            if img.width > max_width:
                height = int((max_width / img.width) * img.height)
                img = img.resize((max_width, height), Image.Resampling.LANCZOS)
            
            img.save(local_output_path, "WEBP", quality=quality)
            logger.info("Successfully optimized image %s to %s (WebP)", local_input_path, local_output_path)
        return True
    except Exception as e:
        logger.error("Failed to optimize image %s: %s", local_input_path, str(e))
        # Fallback to simple copy to prevent ingestion pipeline crashes
        shutil.copy2(local_input_path, local_output_path)
        return False

def optimize_audio(local_input_path: str, local_output_path: str, bitrate: str = "64k") -> bool:
    """Compresses audio using ffmpeg CLI via subprocess if available, or falls back to raw copy."""
    try:
        # Check if ffmpeg command exists on the host system
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Run conversion to highly compressed mp3
        cmd = [
            "ffmpeg", "-y",
            "-i", local_input_path,
            "-vn",                      # Remove video track if any
            "-acodec", "libmp3lame",
            "-ab", bitrate,             # Target bitrate (64k is perfect for voice)
            "-ar", "44100",             # CD quality sample rate
            local_output_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info("Successfully optimized audio %s to %s", local_input_path, local_output_path)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning("ffmpeg is not available or failed (%s). Copying raw file instead.", str(e))
        shutil.copy2(local_input_path, local_output_path)
        return False
