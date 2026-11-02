# CROP CYCLE

CROP CYCLE is a local-first crop-residue marketplace prototype. It connects farmers listing agricultural residue with buyers looking for local supply. The project includes a Flask REST API, SQLite persistence, role-based dashboards, weighted match scoring, approximate mapping, and a resettable demo.

## Run locally

1. Install Python 3.10 or later.
2. From this folder, install the dependency:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Start the Flask server from this folder:

   ```powershell
   .\run.bat
   ```

4. Open [http://127.0.0.1:5000](http://127.0.0.1:5000).

Do not open the project folder in a browser or use VS Code Live Server; those serve a directory listing or static files instead of running the Flask API the website needs. Keep the `run.bat` terminal open while using the site. You can also start the app with `python app.py` in the project folder.

SQLite creates `crop_cycle.db` automatically on first startup. Set `CROP_CYCLE_DATABASE` to use a different database file. Set `CROP_CYCLE_SECRET` to a persistent random secret if you need login sessions to survive server restarts. The default generated secret is appropriate for local demonstration only.

## Demo accounts

The demo password is `demo123` for all sample accounts.

| Role | Email |
|---|---|
| Farmer — Rahul Patil | `farmer@cropcycle.demo` |
| Farmer — Amit Sharma | `farmer2@cropcycle.demo` |
| Buyer — Green Energy Biogas Plant | `buyer@cropcycle.demo` |
| Buyer — Eco Brick Industries | `buyer2@cropcycle.demo` |
| Admin | `admin@cropcycle.demo` |

Use **Explore demo** in the footer to reset the sample listings and open the farmer workspace. The reset action preserves registered users and non-demo records.

## Implemented workflows

- Register and sign in as a Farmer or Buyer; passwords are stored as Werkzeug password hashes.
- Farmers publish, edit, remove, and mark residue listings as sold.
- Buyers search and sort available listings, create material requirements, and send purchase requests.
- Farmers accept or decline requests; an accepted request reserves the quantity inside a SQLite transaction. Buyers can then mark the transaction completed.
- The match score is weighted across compatible residue type (40%), quantity (25%), distance (20%), price (10%), and availability (5%). Incompatible residue types are excluded from a targeted match search. Distance uses Haversine and scales linearly to zero at 100 km; when coordinates are unavailable, it contributes a neutral 10/20 points. Each result shows its score breakdown.
- Farmer, buyer, and admin dashboards display values derived from database records.
- Listing locations are approximate; do not enter a private home address. Map tiles and fonts load from OpenStreetMap and Google Fonts when an internet connection is available.
- The earnings calculator is an estimate, not guaranteed profit. Public environmental impact counters report recorded platform activity and do not claim verified emissions reductions.

## Notes

This is a hackathon prototype, not a production marketplace. Before public deployment, configure a strong secret, add HTTPS and CSRF protections, review privacy and retention requirements, and provide finalized privacy and terms documents. Uploads are limited to common image formats and 5 MB.
