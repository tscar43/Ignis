# Backend API ownership

This session owns backend/main.py, backend/api/, backend/data.py, backend/models.py,
backend/routing/, backend/shelters/, and backend/tests/.

- Serve engine dictionaries unchanged, including additive fields.
- Use backend.fire.contract.validate; do not duplicate fire validation.
- Do not edit backend/fire/, backend/weather/, demo_data/, or contracts/.
- Live fetches use a TTL cache and retain the last good payload on error.
- Put cache metadata in HTTP headers, outside the payload.
- Tests use injected loaders and clocks, with no network calls.
- Synthetic routing fixtures belong in backend/routing/demo/.
