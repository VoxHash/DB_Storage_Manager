#!/usr/bin/env python3
"""
DB Storage Manager - Setup Script
A professional desktop application for managing database storage and backups.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_file = Path(__file__).parent / "README.md"
long_description = (
    readme_file.read_text(encoding="utf-8") if readme_file.exists() else ""
)

setup(
    name="db-storage-manager",
    version="1.0.0",
    description="Professional desktop application for database storage management and backups",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="VoxHash",
    author_email="",
    url="https://github.com/voxhash/db-storage-manager",
    license="MIT",
    packages=find_packages(exclude=["tests", "*.tests", "*.tests.*", "tests.*"]),
    python_requires=">=3.10",
    install_requires=[
        "PyQt6>=6.6.0",
        "PyQt6-Charts>=6.6.0",
        "psycopg2-binary>=2.9.9",
        "pymysql>=1.1.0",
        "aiosqlite>=0.19.0",
        "pymongo>=4.6.0",
        "redis>=5.0.0",
        "boto3>=1.34.0",
        "google-api-python-client>=2.100.0",
        "google-auth-httplib2>=0.1.1",
        "google-auth-oauthlib>=1.1.0",
        "cryptography>=41.0.0",
        "pynacl>=1.5.0",
        "python-dotenv>=1.0.0",
        "schedule>=1.2.0",
        "paramiko>=3.4.0",
        "pandas>=2.1.0",
        "numpy>=1.26.0",
        "matplotlib>=3.8.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.4.0",
            "pytest-qt>=4.2.0",
            "black>=23.11.0",
            "flake8>=6.1.0",
            "mypy>=1.7.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "db-storage-manager=db_storage_manager.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Database",
        "Topic :: System :: Archiving :: Backup",
    ],
)
