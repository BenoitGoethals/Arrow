MAP
  NAME "Arrow"
  STATUS ON
  SIZE 800 600
  EXTENT -180 -90 180 90
  UNITS DD

  PROJECTION
    "init=epsg:4326"
  END

  WEB
    METADATA
      "wms_title"           "Arrow Tactical WMS"
      "wms_onlineresource"  "http://mapserver/cgi-bin/mapserv?"
      "wms_srs"             "EPSG:4326 EPSG:3857"
      "wms_enable_request"  "*"
      "ows_enable_request"  "*"
    END
  END

  OUTPUTFORMAT
    NAME "png"
    DRIVER "AGG/PNG"
    MIMETYPE "image/png"
    IMAGEMODE RGBA
    EXTENSION "png"
    FORMATOPTION "INTERLACE=OFF"
  END

  # ── Operators ──────────────────────────────────────────────────────────────
  LAYER
    NAME "operators"
    STATUS ON
    TYPE POINT
    CONNECTIONTYPE POSTGIS
    CONNECTION "host=postgres dbname=arrow user=arrow password=${POSTGRES_PASSWORD}"
    DATA "geom FROM ms_operators USING UNIQUE id USING srid=4326"
    METADATA
      "wms_title"           "Operators"
      "wms_include_items"   "all"
      "gml_include_items"   "all"
    END
    CLASS
      NAME "Online"
      EXPRESSION ("[status]" = "ONLINE")
      STYLE
        SYMBOL "circle"
        SIZE 10
        COLOR 0 200 0
        OUTLINECOLOR 0 0 0
      END
    END
    CLASS
      NAME "Offline"
      STYLE
        SYMBOL "circle"
        SIZE 8
        COLOR 128 128 128
        OUTLINECOLOR 0 0 0
      END
    END
  END

  # ── Tactical Objects ───────────────────────────────────────────────────────
  LAYER
    NAME "tactical_objects"
    STATUS ON
    TYPE POINT
    CONNECTIONTYPE POSTGIS
    CONNECTION "host=postgres dbname=arrow user=arrow password=${POSTGRES_PASSWORD}"
    DATA "geom FROM ms_tactical_objects USING UNIQUE id USING srid=4326"
    METADATA
      "wms_title"           "Tactical Objects"
      "wms_include_items"   "all"
      "gml_include_items"   "all"
    END
    CLASS
      NAME "Enemy"
      EXPRESSION ("[affiliation]" = "ENEMY")
      STYLE SYMBOL "circle" SIZE 10 COLOR 200 0 0 OUTLINECOLOR 80 0 0 END
    END
    CLASS
      NAME "Unknown"
      EXPRESSION ("[affiliation]" = "UNKNOWN")
      STYLE SYMBOL "circle" SIZE 10 COLOR 200 200 0 OUTLINECOLOR 80 80 0 END
    END
    CLASS
      NAME "Friendly"
      STYLE SYMBOL "circle" SIZE 10 COLOR 0 100 200 OUTLINECOLOR 0 40 80 END
    END
  END

  # ── CoT Tracks ────────────────────────────────────────────────────────────
  LAYER
    NAME "cot_tracks"
    STATUS ON
    TYPE POINT
    CONNECTIONTYPE POSTGIS
    CONNECTION "host=postgres dbname=arrow user=arrow password=${POSTGRES_PASSWORD}"
    DATA "geom FROM ms_cot_tracks USING UNIQUE id USING srid=4326"
    METADATA
      "wms_title"           "CoT Tracks"
      "wms_include_items"   "all"
      "gml_include_items"   "all"
    END
    CLASS
      NAME "CoT Track"
      STYLE SYMBOL "circle" SIZE 8 COLOR 255 165 0 OUTLINECOLOR 100 60 0 END
    END
  END

  # ── Alerts ────────────────────────────────────────────────────────────────
  LAYER
    NAME "alerts"
    STATUS ON
    TYPE POINT
    CONNECTIONTYPE POSTGIS
    CONNECTION "host=postgres dbname=arrow user=arrow password=${POSTGRES_PASSWORD}"
    DATA "geom FROM ms_alerts USING UNIQUE id USING srid=4326"
    METADATA
      "wms_title"           "Alerts"
      "wms_include_items"   "all"
      "gml_include_items"   "all"
    END
    CLASS
      NAME "Active"
      EXPRESSION ("[status]" = "ACTIVE")
      STYLE SYMBOL "circle" SIZE 12 COLOR 255 0 0 OUTLINECOLOR 100 0 0 END
    END
    CLASS
      NAME "Resolved"
      STYLE SYMBOL "circle" SIZE 8 COLOR 200 100 100 END
    END
  END

  # ── Fire Missions ─────────────────────────────────────────────────────────
  LAYER
    NAME "fire_missions"
    STATUS ON
    TYPE POINT
    CONNECTIONTYPE POSTGIS
    CONNECTION "host=postgres dbname=arrow user=arrow password=${POSTGRES_PASSWORD}"
    DATA "geom FROM ms_fire_missions USING UNIQUE id USING srid=4326"
    METADATA
      "wms_title"           "Fire Missions"
      "wms_include_items"   "all"
      "gml_include_items"   "all"
    END
    CLASS
      NAME "Fire Mission"
      STYLE SYMBOL "circle" SIZE 10 COLOR 255 100 0 OUTLINECOLOR 100 40 0 END
    END
  END

  # ── Supply Points ─────────────────────────────────────────────────────────
  LAYER
    NAME "supply_points"
    STATUS ON
    TYPE POINT
    CONNECTIONTYPE POSTGIS
    CONNECTION "host=postgres dbname=arrow user=arrow password=${POSTGRES_PASSWORD}"
    DATA "geom FROM ms_supply_points USING UNIQUE id USING srid=4326"
    METADATA
      "wms_title"           "Supply Points"
      "wms_include_items"   "all"
      "gml_include_items"   "all"
    END
    CLASS
      NAME "Supply Point"
      STYLE SYMBOL "square" SIZE 10 COLOR 0 180 120 OUTLINECOLOR 0 60 40 END
    END
  END

END
