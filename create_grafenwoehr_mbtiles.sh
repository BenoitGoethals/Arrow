#!/bin/bash
# Create Grafenwoehr Training Area MBTiles with Planetiler

PLANETILER_JAR="planetiler.jar"
OUTPUT="grafenwoehr.mbtiles"

java -jar "$PLANETILER_JAR" \
  --download \
  --area=germany \
  --bounds="11.75,49.63,12.05,49.85" \
  --output="$OUTPUT"
