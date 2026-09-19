# Geospatial modeling agent rules

- Only edit files in backend/fire/, backend/weather/, and demo_data/risk_* / fuel_overlay.png.
- Never edit contracts/ without the team agreeing first.
- Output must match contracts/ exactly: EPSG:4326 GeoJSON, bands cumulative (h6 ⊇ h3 ⊇ h1 ⊇ current), timestamps included.
- Model in a projected CRS (meters); convert to EPSG:4326 only at export.
- Wind direction from NWS is where wind comes FROM. Spread direction = (from + 180) % 360.
- Never commit .env, .tif files, or anything over 10 MB.
- Before pushing: run tests and validate output against the contract schema.
