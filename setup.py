"""
Setup script for Duplicate Image Finder package.

Install with:
    pip install -e .

Or build distribution:
    python setup.py sdist bdist_wheel
"""

from setuptools import setup, find_packages
from pathlib import Path
import re

# Read version from __init__.py (single source of truth)
init_path = Path(__file__).parent / "dupefinder" / "__init__.py"
with open(init_path, encoding="utf-8") as f:
    version_match = re.search(r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]', f.read(), re.MULTILINE)
    if not version_match:
        raise RuntimeError("Unable to find version string.")
    version = version_match.group(1)

# Read README for long description
readme_path = Path(__file__).parent / "README.md"
long_description = ""
if readme_path.exists():
    long_description = readme_path.read_text(encoding="utf-8")

setup(
    name="dupefinder",
    version=version,  # Dynamically read from __init__.py (currently 2.1.0)
    author="Zach Daly",
    description="A comprehensive tool for finding duplicate and visually similar images",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Zedidence/DupeFinderGUI.git",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "dupefinder": ["templates/*.html"],
    },
    python_requires=">=3.9",
    install_requires=[
        "Pillow>=9.0.0",
        "imagehash>=4.0.0",
        "flask>=2.0.0",
        "numpy>=1.20.0",
        "pillow-heif>=0.10.0",  # HEIC/HEIF format support
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-cov>=4.0.0",
        ],
        "progress": [
            "tqdm>=4.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "dupefinder=dupefinder.__main__:main",
            "dupefinder-cli=dupefinder.cli:main",
            "dupefinder-gui=dupefinder.app:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Environment :: Web Environment",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Multimedia :: Graphics",
        "Topic :: Utilities",
    ],
    keywords="duplicate image finder photo dedup hash perceptual heic",
)