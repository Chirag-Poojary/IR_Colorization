#!/bin/bash
# Wrapper script for the 3-stage Landsat Pipeline
echo "========================================="
echo "Stage 1: Downloading scenes to Google Drive"
echo "========================================="
python download.py

echo "========================================="
echo "Stage 2: Building Local Dataset Patches"
echo "========================================="
python dataset_builder.py

echo "Pipeline execution finished!"
