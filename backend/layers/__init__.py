"""Portable layer export/import — overlays, KML layers, OSINT boards.

A single JSON *envelope* (:mod:`backend.layers.envelope`) wraps any of the three
"layer" artifacts so they can be downloaded to a file, re-imported into another
mission, or frozen onto an OPORD as a self-contained attachment.
"""
