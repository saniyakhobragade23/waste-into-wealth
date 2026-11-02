import math
import os
import sqlite3
import uuid
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


ROOT = Path(__file__).resolve().parent
DATABASE = Path(os.environ.get("CROP_CYCLE_DATABASE", ROOT / "crop_cycle.db"))
UPLOAD_FOLDER = ROOT / "static" / "uploads"
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
WASTE_TYPES = (
    "Sugarcane Trash",
    "Wheat Straw",
    "Rice Husk",
    "Cotton Stalks",
    "Corn Stalks",
    "Other Agricultural Residue",
)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("CROP_CYCLE_SECRET") or os.urandom(32),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    database = g.pop("db", None)
    if database is not None:
        database.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            mobile TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('farmer', 'buyer', 'admin')),
            state TEXT NOT NULL DEFAULT '',
            district TEXT NOT NULL DEFAULT '',
            village TEXT NOT NULL DEFAULT '',
            latitude REAL,
            longitude REAL,
            is_demo INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            waste_type TEXT NOT NULL,
            quantity REAL NOT NULL CHECK(quantity > 0),
            price_per_tonne REAL NOT NULL CHECK(price_per_tonne >= 0),
            state TEXT NOT NULL DEFAULT '',
            district TEXT NOT NULL DEFAULT '',
            village TEXT NOT NULL DEFAULT '',
            pickup_location TEXT NOT NULL DEFAULT '',
            latitude REAL,
            longitude REAL,
            available_from TEXT NOT NULL,
            available_until TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            image TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Open'
                CHECK(status IN ('Open', 'Requested', 'Sold', 'Removed')),
            is_verified INTEGER NOT NULL DEFAULT 0,
            is_demo INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS buyer_requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            waste_type TEXT NOT NULL,
            required_quantity REAL NOT NULL CHECK(required_quantity > 0),
            maximum_price REAL NOT NULL CHECK(maximum_price >= 0),
            location TEXT NOT NULL DEFAULT '',
            latitude REAL,
            longitude REAL,
            required_date TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Open',
            is_demo INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS buyer_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            farmer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            requested_quantity REAL NOT NULL CHECK(requested_quantity > 0),
            offered_price REAL NOT NULL CHECK(offered_price >= 0),
            message TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Pending'
                CHECK(status IN ('Pending', 'Accepted', 'Rejected', 'Completed', 'Cancelled')),
            is_demo INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL UNIQUE REFERENCES buyer_requests(id) ON DELETE CASCADE,
            buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            farmer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            quantity REAL NOT NULL,
            final_price REAL NOT NULL,
            transaction_status TEXT NOT NULL DEFAULT 'Accepted'
                CHECK(transaction_status IN ('Accepted', 'Completed', 'Cancelled')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            message TEXT NOT NULL,
            notification_type TEXT NOT NULL DEFAULT 'info',
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_request
            ON buyer_requests(listing_id,buyer_id) WHERE status IN ('Pending','Accepted');
        """
    )
    user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
    listing_columns = {row["name"] for row in db.execute("PRAGMA table_info(listings)")}
    if "is_active" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    if "is_verified" not in listing_columns:
        db.execute("ALTER TABLE listings ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0")
    db.commit()
    seed_demo_data(db)


def seed_demo_data(db):
    users = [
        ("Rahul Patil", "farmer@cropcycle.demo", "9000000001", "farmer", "Maharashtra", "Gondia", "Village A", 21.462, 80.221),
        ("Amit Sharma", "farmer2@cropcycle.demo", "9000000002", "farmer", "Maharashtra", "Bhandara", "Bhandara", 21.170, 79.650),
        ("Green Energy Biogas Plant", "buyer@cropcycle.demo", "9000000003", "buyer", "Maharashtra", "Gondia", "Gondia", 21.480, 80.240),
        ("Eco Brick Industries", "buyer2@cropcycle.demo", "9000000004", "buyer", "Maharashtra", "Bhandara", "Bhandara", 21.185, 79.668),
        ("CROP CYCLE Admin", "admin@cropcycle.demo", "9000000005", "admin", "Maharashtra", "Nagpur", "Nagpur", 21.145, 79.088),
    ]
    for name, email, mobile, role, state, district, village, lat, lon in users:
        db.execute(
            """INSERT OR IGNORE INTO users
               (full_name,email,mobile,password_hash,role,state,district,village,latitude,longitude,is_demo)
               VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
            (name, email, mobile, generate_password_hash("demo123"), role, state, district, village, lat, lon),
        )

    demo_users = {
        row["email"]: row["id"]
        for row in db.execute("SELECT id,email FROM users WHERE is_demo=1").fetchall()
    }
    farmer_a = demo_users["farmer@cropcycle.demo"]
    farmer_b = demo_users["farmer2@cropcycle.demo"]
    buyer_a = demo_users["buyer@cropcycle.demo"]
    buyer_b = demo_users["buyer2@cropcycle.demo"]
    if db.execute("SELECT COUNT(*) FROM listings WHERE is_demo=1").fetchone()[0] == 0:
        today = date.today()
        db.executemany(
            """INSERT INTO listings
               (farmer_id,waste_type,quantity,price_per_tonne,state,district,village,pickup_location,
                latitude,longitude,available_from,available_until,description,status,is_demo)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'Open',1)""",
            [
                (farmer_a, "Sugarcane Trash", 5, 1500, "Maharashtra", "Gondia", "Village A", "Near the village cooperative", 21.462, 80.221, today.isoformat(), (today + timedelta(days=30)).isoformat(), "Clean, dry sugarcane residue, ready for pickup."),
                (farmer_b, "Rice Husk", 8, 1200, "Maharashtra", "Bhandara", "Bhandara", "Bhandara agricultural yard", 21.170, 79.650, today.isoformat(), (today + timedelta(days=21)).isoformat(), "Rice husk stored under cover; bulk pickup available."),
            ],
        )
        db.execute("UPDATE listings SET is_verified=1 WHERE is_demo=1")
    if db.execute("SELECT COUNT(*) FROM buyer_requirements WHERE is_demo=1").fetchone()[0] == 0:
        db.executemany(
            """INSERT INTO buyer_requirements
               (buyer_id,waste_type,required_quantity,maximum_price,location,latitude,longitude,required_date,is_demo)
               VALUES (?,?,?,?,?,?,?,?,1)""",
            [
                (buyer_a, "Sugarcane Trash", 4, 1800, "Gondia", 21.480, 80.240, date.today().isoformat()),
                (buyer_b, "Rice Husk", 6, 1500, "Bhandara", 21.185, 79.668, date.today().isoformat()),
            ],
        )
    db.commit()


def api_error(message, status=400):
    return jsonify({"error": message}), status


def login_required(role=None):
    def decorator(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            user_id = session.get("user_id")
            if not user_id:
                return api_error("Please sign in to continue.", 401)
            user = get_db().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if user is None:
                session.clear()
                return api_error("Your session has expired. Please sign in again.", 401)
            if not user["is_active"]:
                session.clear()
                return api_error("This account is currently disabled. Contact an administrator.", 403)
            if role and user["role"] not in ([role] if isinstance(role, str) else role):
                return api_error("You do not have permission to perform this action.", 403)
            g.user = user
            return function(*args, **kwargs)

        return wrapped
    return decorator


def user_json(user):
    return {key: user[key] for key in ("id", "full_name", "email", "mobile", "role", "state", "district", "village", "latitude", "longitude", "is_demo")}


def haversine_km(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    radius = 6371
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    d_phi = math.radians(float(lat2) - float(lat1))
    d_lambda = math.radians(float(lon2) - float(lon1))
    value = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def parse_coordinates(latitude, longitude):
    if latitude in (None, "") and longitude in (None, ""):
        return None, None
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        raise ValueError("Latitude and longitude must be provided as a valid pair.")
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Latitude or longitude is outside the valid range.")
    return latitude, longitude


def matching_score(listing, required_quantity, maximum_price, origin_lat, origin_lon, waste_type=None, available_until=None):
    if not waste_type or listing["waste_type"] != waste_type:
        return 0, haversine_km(origin_lat, origin_lon, listing["latitude"], listing["longitude"]), "Not compatible", {
            "type": 0, "quantity": 0, "distance": 0, "price": 0, "availability": 0,
        }
    available = float(listing["quantity"])
    required = max(float(required_quantity or 0), 0.01)
    quantity_score = min(available / required, 1) * 25
    distance = haversine_km(origin_lat, origin_lon, listing["latitude"], listing["longitude"])
    distance_score = 20 * max(0, 1 - (distance or 0) / 100) if distance is not None else 10
    price = float(listing["price_per_tonne"])
    if maximum_price is None or float(maximum_price) <= 0:
        price_score = 5
    else:
        price_score = 10 * min(float(maximum_price) / max(price, 0.01), 1)
    end_date = available_until or listing["available_until"]
    availability_score = 5 if not end_date or end_date >= date.today().isoformat() else 0
    total = round(40 + quantity_score + distance_score + price_score + availability_score)
    tier = "Excellent Match" if total >= 85 else "Good Match" if total >= 65 else "Moderate Match"
    return total, distance, tier, {
        "type": 40,
        "quantity": round(quantity_score, 1),
        "distance": round(distance_score, 1),
        "price": round(price_score, 1),
        "availability": availability_score,
    }


def listing_json(row, origin_lat=None, origin_lon=None, required_quantity=1, maximum_price=None, waste_type=None, include_pickup=False):
    data = dict(row)
    if not include_pickup:
        data.pop("pickup_location", None)
    score, distance, tier, breakdown = matching_score(
        row, required_quantity, maximum_price, origin_lat, origin_lon, waste_type
    )
    data.update(
        distance_km=round(distance, 1) if distance is not None else None,
        match_score=score,
        match_tier=tier,
        score_breakdown=breakdown,
    )
    for coordinate in ("latitude", "longitude"):
        if data.get(coordinate) is not None:
            data[coordinate] = round(float(data[coordinate]), 2)
    return data


def request_json(row):
    return dict(row)


@app.route("/")
def home():
    return render_template("index.html")


@app.get("/api/me")
def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"user": None})
    user = get_db().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if user is None:
        session.clear()
        return jsonify({"user": None})
    return jsonify({"user": user_json(user)})


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}
    name = str(data.get("full_name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    role = data.get("role")
    if not name or len(name) > 100 or "@" not in email or len(email) > 254:
        return api_error("Enter a valid name and email address.")
    if len(password) < 8:
        return api_error("Password must contain at least 8 characters.")
    if role not in ("farmer", "buyer"):
        return api_error("Choose a Farmer or Buyer account.")
    try:
        latitude, longitude = parse_coordinates(data.get("latitude"), data.get("longitude"))
    except ValueError as error:
        return api_error(str(error))
    db = get_db()
    try:
        cursor = db.execute(
            """INSERT INTO users (full_name,email,mobile,password_hash,role,state,district,village,latitude,longitude)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                name, email, str(data.get("mobile", "")).strip(), generate_password_hash(password), role,
                str(data.get("state", "")).strip(), str(data.get("district", "")).strip(),
                str(data.get("village", "")).strip(), latitude, longitude,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return api_error("An account with that email already exists.", 409)
    user = db.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone()
    session["user_id"] = user["id"]
    return jsonify({"user": user_json(user)}), 201


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    user = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if user is None or not user["is_active"] or not check_password_hash(user["password_hash"], password):
        return api_error("Email or password is incorrect.", 401)
    session.clear()
    session["user_id"] = user["id"]
    return jsonify({"user": user_json(user)})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.post("/api/demo/reset")
def reset_demo():
    db = get_db()
    db.execute("DELETE FROM buyer_requests WHERE is_demo=1")
    db.execute("DELETE FROM transactions WHERE request_id NOT IN (SELECT id FROM buyer_requests)")
    db.execute("DELETE FROM notifications WHERE user_id IN (SELECT id FROM users WHERE is_demo=1)")
    db.execute("DELETE FROM buyer_requirements WHERE is_demo=1")
    db.execute("DELETE FROM listings WHERE is_demo=1")
    db.execute("UPDATE users SET is_active=1 WHERE is_demo=1")
    db.commit()
    seed_demo_data(db)
    return jsonify({"ok": True, "message": "Demo data has been reset."})


@app.get("/api/public/listings")
def public_listings():
    rows = get_db().execute(
        """SELECT l.*,u.full_name AS farmer_name FROM listings l
           JOIN users u ON u.id=l.farmer_id
           WHERE l.is_demo=1 AND l.status IN ('Open','Requested') AND l.quantity>0"""
    ).fetchall()
    buyers = get_db().execute(
        """SELECT full_name,role,state,district,village,latitude,longitude FROM users
           WHERE is_demo=1 AND role='buyer' AND latitude IS NOT NULL AND longitude IS NOT NULL"""
    ).fetchall()
    return jsonify({
        "listings": [listing_json(row) for row in rows],
        "buyers": [{
            "full_name": buyer["full_name"],
            "role": buyer["role"],
            "state": buyer["state"],
            "district": buyer["district"],
            "village": buyer["village"],
            "latitude": round(float(buyer["latitude"]), 2),
            "longitude": round(float(buyer["longitude"]), 2),
        } for buyer in buyers],
    })


@app.get("/api/map")
@login_required()
def map_data():
    db = get_db()
    query = """SELECT l.*,u.full_name AS farmer_name FROM listings l
               JOIN users u ON u.id=l.farmer_id
               WHERE l.status IN ('Open','Requested') AND l.quantity>0 AND l.available_until>=?"""
    values = [date.today().isoformat()]
    waste_type = request.args.get("waste_type", "").strip()
    district = request.args.get("district", "").strip()
    if waste_type:
        query += " AND l.waste_type=?"
        values.append(waste_type)
    if district:
        query += " AND l.district LIKE ?"
        values.append(f"%{district}%")
    rows = db.execute(query, values).fetchall()
    buyers = db.execute(
        """SELECT full_name,role,state,district,village,latitude,longitude
           FROM users WHERE role='buyer' AND latitude IS NOT NULL AND longitude IS NOT NULL"""
    ).fetchall()
    buyer_points = [{
        "full_name": buyer["full_name"],
        "role": buyer["role"],
        "state": buyer["state"],
        "district": buyer["district"],
        "village": buyer["village"],
        "latitude": round(float(buyer["latitude"]), 2),
        "longitude": round(float(buyer["longitude"]), 2),
    } for buyer in buyers]
    return jsonify({
        "listings": [listing_json(row, g.user["latitude"], g.user["longitude"], waste_type=row["waste_type"]) for row in rows],
        "buyers": buyer_points,
    })


@app.route("/api/listings", methods=["GET", "POST"])
@login_required()
def listings():
    db = get_db()
    if request.method == "POST":
        if g.user["role"] != "farmer":
            return api_error("Only farmer accounts can publish listings.", 403)
        data = request.form if request.form else (request.get_json(silent=True) or {})
        waste_type = str(data.get("waste_type", "")).strip()
        quantity = data.get("quantity")
        price = data.get("price_per_tonne")
        available_from = str(data.get("available_from", ""))
        available_until = str(data.get("available_until", ""))
        try:
            quantity = float(quantity)
            price = float(price)
            if not math.isfinite(quantity) or not math.isfinite(price) or quantity <= 0 or price < 0:
                raise ValueError()
            date.fromisoformat(available_from)
            date.fromisoformat(available_until)
            if available_until < available_from:
                raise ValueError()
        except (TypeError, ValueError):
            return api_error("Check the quantity, price, and availability dates.")
        if waste_type not in WASTE_TYPES:
            return api_error("Choose a supported agricultural residue type.")
        image_path = ""
        image_file = request.files.get("image")
        if image_file and image_file.filename:
            filename = secure_filename(image_file.filename)
            extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if extension not in ALLOWED_IMAGE_EXTENSIONS:
                return api_error("Upload a PNG, JPG, JPEG, or WEBP image.")
            image_name = f"{uuid.uuid4().hex}.{extension}"
            image_file.save(UPLOAD_FOLDER / image_name)
            image_path = f"/static/uploads/{image_name}"
        try:
            latitude, longitude = parse_coordinates(data.get("latitude"), data.get("longitude"))
        except ValueError as error:
            return api_error(str(error))
        cursor = db.execute(
            """INSERT INTO listings
               (farmer_id,waste_type,quantity,price_per_tonne,state,district,village,pickup_location,
                latitude,longitude,available_from,available_until,description,image,is_demo)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                g.user["id"], waste_type, quantity, price,
                str(data.get("state", g.user["state"])).strip(),
                str(data.get("district", g.user["district"])).strip(),
                str(data.get("village", g.user["village"])).strip(),
                str(data.get("pickup_location", "")).strip(), latitude, longitude,
                available_from, available_until, str(data.get("description", "")).strip(), image_path, g.user["is_demo"],
            ),
        )
        db.commit()
        row = db.execute(
            """SELECT l.*,u.full_name AS farmer_name FROM listings l
               JOIN users u ON u.id=l.farmer_id WHERE l.id=?""",
            (cursor.lastrowid,),
        ).fetchone()
        return jsonify({"listing": listing_json(row, include_pickup=True)}), 201

    params = request.args
    query = """SELECT l.*,u.full_name AS farmer_name FROM listings l
               JOIN users u ON u.id=l.farmer_id WHERE 1=1"""
    values = []
    own = params.get("mine") == "1"
    if own:
        if g.user["role"] != "farmer":
            return api_error("Only farmers can view their listings.", 403)
        query += " AND l.farmer_id=? AND l.status!='Removed'"
        values.append(g.user["id"])
    else:
        query += " AND l.status IN ('Open','Requested') AND l.quantity>0 AND l.available_until >= ?"
        values.append(date.today().isoformat())
    filters = [
        ("waste_type", "l.waste_type = ?"),
        ("state", "l.state LIKE ?"),
        ("district", "l.district LIKE ?"),
    ]
    for key, clause in filters:
        value = params.get(key, "").strip()
        if value:
            query += " AND " + clause
            values.append(value if key == "waste_type" else f"%{value}%")
    try:
        required_quantity = float(params.get("quantity") or 1)
        max_distance = float(params["max_distance"]) if params.get("max_distance") else None
        minimum_price = float(params["min_price"]) if params.get("min_price") else None
        maximum_price = float(params["max_price"]) if params.get("max_price") else None
        origin_lat, origin_lon = parse_coordinates(
            params.get("latitude") or g.user["latitude"],
            params.get("longitude") or g.user["longitude"],
        )
    except ValueError as error:
        return api_error(str(error) if str(error) else "Search filters must contain valid numbers.")
    numeric_filters = [required_quantity]
    if max_distance is not None:
        numeric_filters.append(max_distance)
    numeric_filters.extend(value for value in (minimum_price, maximum_price) if value is not None)
    if any(not math.isfinite(value) for value in numeric_filters) or required_quantity <= 0 or (max_distance is not None and max_distance < 0) or (minimum_price is not None and minimum_price < 0) or (maximum_price is not None and maximum_price < 0):
        return api_error("Search quantity, price, and distance filters must be finite non-negative values.")
    if minimum_price is not None:
        query += " AND l.price_per_tonne >= ?"
        values.append(minimum_price)
    if maximum_price is not None:
        query += " AND l.price_per_tonne <= ?"
        values.append(maximum_price)
    match_type = params.get("waste_type", "").strip()
    if not match_type and g.user["role"] == "buyer":
        saved = db.execute(
            """SELECT waste_type,required_quantity,maximum_price,latitude,longitude
               FROM buyer_requirements WHERE buyer_id=? AND status='Open' ORDER BY id DESC LIMIT 1""",
            (g.user["id"],),
        ).fetchone()
        if saved:
            match_type = saved["waste_type"]
            if not params.get("quantity"):
                required_quantity = float(saved["required_quantity"])
            if maximum_price is None:
                maximum_price = float(saved["maximum_price"])
            if not params.get("latitude") and saved["latitude"] is not None:
                origin_lat = saved["latitude"]
                origin_lon = saved["longitude"]
    query += " ORDER BY l.created_at DESC"
    rows = db.execute(query, values).fetchall()
    items = []
    for row in rows:
        raw_distance = haversine_km(origin_lat, origin_lon, row["latitude"], row["longitude"])
        item = listing_json(row, origin_lat, origin_lon, required_quantity, maximum_price, match_type or None, include_pickup=own)
        if match_type and item["match_score"] == 0:
            continue
        if max_distance is not None and (raw_distance is None or raw_distance > max_distance):
            continue
        items.append(item)
    sort = params.get("sort", "match")
    sorters = {
        "nearest": lambda item: (item["distance_km"] is None, item["distance_km"] or float("inf")),
        "price": lambda item: item["price_per_tonne"],
        "quantity": lambda item: -item["quantity"],
        "recent": lambda item: item["created_at"],
        "match": lambda item: -item["match_score"],
    }
    items.sort(key=sorters.get(sort, sorters["match"]))
    return jsonify({"listings": items, "count": len(items)})


@app.route("/api/listings/<int:listing_id>", methods=["GET", "PUT", "DELETE"])
@login_required()
def listing_detail(listing_id):
    db = get_db()
    row = db.execute(
        "SELECT l.*,u.full_name AS farmer_name FROM listings l JOIN users u ON u.id=l.farmer_id WHERE l.id=?",
        (listing_id,),
    ).fetchone()
    if row is None:
        return api_error("Listing not found.", 404)
    if request.method == "GET":
        requirement = None
        if g.user["role"] == "buyer":
            requirement = db.execute(
                """SELECT waste_type,required_quantity,maximum_price,latitude,longitude
                   FROM buyer_requirements WHERE buyer_id=? AND status='Open' ORDER BY id DESC LIMIT 1""",
                (g.user["id"],),
            ).fetchone()
        return jsonify({"listing": listing_json(
            row,
            requirement["latitude"] if requirement and requirement["latitude"] is not None else g.user["latitude"],
            requirement["longitude"] if requirement and requirement["longitude"] is not None else g.user["longitude"],
            requirement["required_quantity"] if requirement else 1,
            requirement["maximum_price"] if requirement else None,
            requirement["waste_type"] if requirement else None,
            include_pickup=(g.user["role"] == "farmer" and row["farmer_id"] == g.user["id"]),
        )})
    if g.user["role"] != "farmer" or row["farmer_id"] != g.user["id"]:
        return api_error("You can only manage your own listings.", 403)
    if request.method == "DELETE":
        active = db.execute(
            "SELECT COUNT(*) FROM buyer_requests WHERE listing_id=? AND status IN ('Pending','Accepted')",
            (listing_id,),
        ).fetchone()[0]
        if active:
            return api_error("This listing has active requests and cannot be removed yet.", 409)
        db.execute("UPDATE listings SET status='Removed' WHERE id=?", (listing_id,))
        db.commit()
        return jsonify({"ok": True})
    data = request.get_json(silent=True) or {}
    allowed = {"description", "price_per_tonne", "available_until"}
    updates = {key: data[key] for key in allowed if key in data}
    if "price_per_tonne" in updates:
        try:
            updates["price_per_tonne"] = float(updates["price_per_tonne"])
            if not math.isfinite(updates["price_per_tonne"]) or updates["price_per_tonne"] < 0:
                raise ValueError()
        except (TypeError, ValueError):
            return api_error("Enter a valid non-negative price.")
    if "available_until" in updates:
        try:
            date.fromisoformat(updates["available_until"])
            if updates["available_until"] < row["available_from"]:
                raise ValueError()
        except (TypeError, ValueError):
            return api_error("Availability end date must be on or after the listing start date.")
    if not updates:
        return api_error("There are no listing changes to save.")
    assignments = ", ".join(f"{key}=?" for key in updates)
    db.execute(f"UPDATE listings SET {assignments} WHERE id=?", (*updates.values(), listing_id))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/listings/<int:listing_id>/sold")
@login_required("farmer")
def mark_listing_sold(listing_id):
    db = get_db()
    row = db.execute("SELECT * FROM listings WHERE id=? AND farmer_id=?", (listing_id, g.user["id"])).fetchone()
    if row is None:
        return api_error("Listing not found.", 404)
    if row["status"] == "Removed":
        return api_error("Removed listings cannot be marked sold.", 409)
    pending = db.execute(
        "SELECT COUNT(*) FROM buyer_requests WHERE listing_id=? AND status='Pending'",
        (listing_id,),
    ).fetchone()[0]
    if pending:
        return api_error("Respond to pending buyer requests before marking this listing sold.", 409)
    db.execute("UPDATE listings SET quantity=0,status='Sold' WHERE id=?", (listing_id,))
    db.commit()
    return jsonify({"ok": True, "status": "Sold"})


@app.post("/api/requests")
@login_required("buyer")
def create_request():
    data = request.get_json(silent=True) or {}
    try:
        listing_id = int(data.get("listing_id"))
        quantity = float(data.get("requested_quantity"))
        price = float(data.get("offered_price"))
        if not math.isfinite(quantity) or not math.isfinite(price) or quantity <= 0 or price < 0:
            raise ValueError()
    except (TypeError, ValueError):
        return api_error("Enter a valid quantity and offered price.")
    db = get_db()
    listing = db.execute("SELECT * FROM listings WHERE id=? AND status IN ('Open','Requested')", (listing_id,)).fetchone()
    if listing is None:
        return api_error("This listing is no longer available.", 404)
    if listing["farmer_id"] == g.user["id"]:
        return api_error("You cannot request your own listing.")
    if listing["waste_type"] != str(data.get("waste_type", listing["waste_type"])):
        return api_error("Only matching residue types can be requested.")
    if quantity > listing["quantity"]:
        return api_error(f"Only {listing['quantity']:g} tonnes are currently available.", 409)
    duplicate = db.execute(
        """SELECT id FROM buyer_requests WHERE listing_id=? AND buyer_id=?
           AND status IN ('Pending','Accepted')""",
        (listing_id, g.user["id"]),
    ).fetchone()
    if duplicate:
        return api_error("You already have an active request for this listing.", 409)
    try:
        cursor = db.execute(
            """INSERT INTO buyer_requests
               (listing_id,farmer_id,buyer_id,requested_quantity,offered_price,message,is_demo)
               VALUES (?,?,?,?,?,?,?)""",
            (listing_id, listing["farmer_id"], g.user["id"], quantity, price,
             str(data.get("message", "")).strip()[:1000], int(bool(listing["is_demo"] or g.user["is_demo"]))),
        )
    except sqlite3.IntegrityError:
        db.rollback()
        return api_error("You already have an active request for this listing.", 409)
    db.execute("UPDATE listings SET status='Requested' WHERE id=?", (listing_id,))
    db.execute(
        "INSERT INTO notifications (user_id,message,notification_type) VALUES (?,?,?)",
        (listing["farmer_id"], f"{g.user['full_name']} sent a request for {quantity:g} tonnes.", "request"),
    )
    db.commit()
    return jsonify({"request_id": cursor.lastrowid, "status": "Pending"}), 201


@app.get("/api/requests")
@login_required()
def get_requests():
    if g.user["role"] == "admin":
        return api_error("Admin requests are available in platform activity.", 403)
    key = "farmer_id" if g.user["role"] == "farmer" else "buyer_id"
    rows = get_db().execute(
        f"""SELECT r.*,l.waste_type,l.village,l.district,l.pickup_location,l.quantity AS listing_quantity,
                   farmer.full_name AS farmer_name,buyer.full_name AS buyer_name
            FROM buyer_requests r JOIN listings l ON l.id=r.listing_id
            JOIN users farmer ON farmer.id=r.farmer_id
            JOIN users buyer ON buyer.id=r.buyer_id
            WHERE r.{key}=? ORDER BY r.created_at DESC""",
        (g.user["id"],),
    ).fetchall()
    request_items = []
    for row in rows:
        item = request_json(row)
        if g.user["role"] == "buyer" and row["status"] not in ("Accepted", "Completed"):
            item.pop("pickup_location", None)
        request_items.append(item)
    return jsonify({"requests": request_items})


@app.post("/api/requests/<int:request_id>/<action>")
@login_required()
def update_request(request_id, action):
    if action not in ("accept", "reject", "complete", "cancel"):
        return api_error("Unsupported request action.")
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    row = db.execute("SELECT * FROM buyer_requests WHERE id=?", (request_id,)).fetchone()
    if row is None:
        db.rollback()
        return api_error("Request not found.", 404)
    farmer_action = action in ("accept", "reject")
    expected_owner = row["farmer_id"] if farmer_action else row["buyer_id"]
    if expected_owner != g.user["id"]:
        db.rollback()
        return api_error("You do not have permission to update this request.", 403)
    if action == "accept":
        if row["status"] != "Pending":
            db.rollback()
            return api_error("Only pending requests can be accepted.", 409)
        listing = db.execute("SELECT * FROM listings WHERE id=?", (row["listing_id"],)).fetchone()
        if listing is None or row["requested_quantity"] > listing["quantity"]:
            db.rollback()
            return api_error("There is not enough available quantity to accept this request.", 409)
        remaining = round(listing["quantity"] - row["requested_quantity"], 4)
        listing_status = "Sold" if remaining <= 0.0001 else "Open"
        db.execute("UPDATE listings SET quantity=?,status=? WHERE id=?", (max(remaining, 0), listing_status, row["listing_id"]))
        db.execute("UPDATE buyer_requests SET status='Accepted' WHERE id=?", (request_id,))
        db.execute(
            """INSERT INTO transactions
               (request_id,buyer_id,farmer_id,listing_id,quantity,final_price,transaction_status)
               VALUES (?,?,?,?,?,?, 'Accepted')""",
            (request_id, row["buyer_id"], row["farmer_id"], row["listing_id"], row["requested_quantity"], row["offered_price"]),
        )
    elif action == "reject":
        if row["status"] != "Pending":
            db.rollback()
            return api_error("Only pending requests can be rejected.", 409)
        db.execute("UPDATE buyer_requests SET status='Rejected' WHERE id=?", (request_id,))
    elif action == "complete":
        if row["status"] != "Accepted":
            db.rollback()
            return api_error("Only accepted requests can be completed.", 409)
        db.execute("UPDATE buyer_requests SET status='Completed' WHERE id=?", (request_id,))
        db.execute("UPDATE transactions SET transaction_status='Completed' WHERE request_id=?", (request_id,))
    else:
        if row["status"] != "Pending":
            db.rollback()
            return api_error("Only pending requests can be cancelled.", 409)
        db.execute("UPDATE buyer_requests SET status='Cancelled' WHERE id=?", (request_id,))
    if action in ("reject", "cancel"):
        active = db.execute(
            "SELECT COUNT(*) FROM buyer_requests WHERE listing_id=? AND status IN ('Pending','Accepted')",
            (row["listing_id"],),
        ).fetchone()[0]
        if active == 0:
            db.execute(
                "UPDATE listings SET status='Open' WHERE id=? AND quantity>0",
                (row["listing_id"],),
            )
    recipient_id = row["buyer_id"] if farmer_action else row["farmer_id"]
    db.execute(
        "INSERT INTO notifications (user_id,message,notification_type) VALUES (?,?,?)",
        (recipient_id, f"Request #{request_id} was {action}ed.", "request"),
    )
    db.commit()
    statuses = {"accept": "Accepted", "reject": "Rejected", "complete": "Completed", "cancel": "Cancelled"}
    return jsonify({"ok": True, "status": statuses[action]})


@app.get("/api/requirements")
@login_required("buyer")
def requirements():
    rows = get_db().execute(
        """SELECT * FROM buyer_requirements WHERE buyer_id=? AND status='Open'
           ORDER BY id DESC""",
        (g.user["id"],),
    ).fetchall()
    return jsonify({"requirements": [dict(row) for row in rows]})


@app.post("/api/requirements")
@login_required("buyer")
def create_requirement():
    data = request.get_json(silent=True) or {}
    try:
        quantity = float(data.get("required_quantity"))
        price = float(data.get("maximum_price"))
        if not math.isfinite(quantity) or not math.isfinite(price) or quantity <= 0 or price < 0:
            raise ValueError()
    except (TypeError, ValueError):
        return api_error("Enter a valid required quantity and maximum price.")
    waste_type = str(data.get("waste_type", ""))
    if waste_type not in WASTE_TYPES:
        return api_error("Choose a supported residue type.")
    db = get_db()
    cursor = db.execute(
        """INSERT INTO buyer_requirements
           (buyer_id,waste_type,required_quantity,maximum_price,location,latitude,longitude,required_date,is_demo)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (g.user["id"], waste_type, quantity, price, str(data.get("location", "")).strip(),
         g.user["latitude"], g.user["longitude"], str(data.get("required_date", "")), g.user["is_demo"]),
    )
    db.commit()
    return jsonify({"id": cursor.lastrowid, "ok": True}), 201


@app.get("/api/dashboard")
@login_required()
def dashboard():
    db = get_db()
    uid = g.user["id"]
    if g.user["role"] == "farmer":
        own_listings = db.execute(
            "SELECT COUNT(*) AS count,COALESCE(SUM(quantity),0) AS quantity FROM listings WHERE farmer_id=? AND status!='Removed'",
            (uid,),
        ).fetchone()
        counts = db.execute(
            """SELECT SUM(CASE WHEN status='Pending' THEN 1 ELSE 0 END) AS pending,
                      SUM(CASE WHEN status='Completed' THEN 1 ELSE 0 END) AS completed
               FROM buyer_requests WHERE farmer_id=?""",
            (uid,),
        ).fetchone()
        earnings = db.execute(
            "SELECT COALESCE(SUM(quantity*final_price),0) FROM transactions WHERE farmer_id=?",
            (uid,),
        ).fetchone()[0]
        return jsonify({
            "stats": {"listings": own_listings["count"], "available_tonnes": round(own_listings["quantity"], 1),
                      "pending_requests": counts["pending"] or 0, "completed_sales": counts["completed"] or 0,
                      "earnings": round(earnings, 2)},
            "earnings_by_month": monthly_earnings(db, "farmer_id", uid),
        })
    if g.user["role"] == "buyer":
        return jsonify({
            "stats": {
                "available_listings": db.execute("SELECT COUNT(*) FROM listings WHERE status IN ('Open','Requested') AND quantity>0 AND available_until>=?", (date.today().isoformat(),)).fetchone()[0],
                "farmers": db.execute("SELECT COUNT(*) FROM users WHERE role='farmer'").fetchone()[0],
                "pending_requests": db.execute("SELECT COUNT(*) FROM buyer_requests WHERE buyer_id=? AND status='Pending'", (uid,)).fetchone()[0],
                "completed_purchases": db.execute("SELECT COUNT(*) FROM buyer_requests WHERE buyer_id=? AND status='Completed'", (uid,)).fetchone()[0],
            }
        })
    return admin_summary(db)


def monthly_earnings(db, owner_key, owner_id):
    rows = db.execute(
        f"""SELECT substr(created_at,1,7) AS month, SUM(quantity*final_price) AS amount
            FROM transactions WHERE {owner_key}=? AND transaction_status IN ('Accepted','Completed')
            GROUP BY month ORDER BY month DESC LIMIT 6""",
        (owner_id,),
    ).fetchall()
    return [{"month": row["month"], "amount": round(row["amount"] or 0, 2)} for row in reversed(rows)]


def admin_summary(db):
    return jsonify({"stats": {
        "farmers": db.execute("SELECT COUNT(*) FROM users WHERE role='farmer'").fetchone()[0],
        "buyers": db.execute("SELECT COUNT(*) FROM users WHERE role='buyer'").fetchone()[0],
        "listings": db.execute("SELECT COUNT(*) FROM listings WHERE status!='Removed'").fetchone()[0],
        "transactions": db.execute("SELECT COUNT(*) FROM transactions WHERE transaction_status='Completed'").fetchone()[0],
        "waste_reused": db.execute("SELECT COALESCE(SUM(quantity),0) FROM transactions WHERE transaction_status='Completed'").fetchone()[0],
        "farmer_earnings": db.execute("SELECT COALESCE(SUM(quantity*final_price),0) FROM transactions").fetchone()[0],
    }})


@app.get("/api/admin")
@login_required("admin")
def admin_data():
    db = get_db()
    users = db.execute("SELECT id,full_name,email,role,district,created_at,is_demo,is_active FROM users ORDER BY created_at DESC LIMIT 100").fetchall()
    listings = db.execute(
        """SELECT l.id,l.waste_type,l.quantity,l.price_per_tonne,l.status,l.district,l.is_verified,u.full_name AS farmer_name
           FROM listings l JOIN users u ON u.id=l.farmer_id ORDER BY l.created_at DESC LIMIT 100"""
    ).fetchall()
    requests = db.execute(
        """SELECT r.id,r.status,r.requested_quantity,r.offered_price,r.created_at,l.waste_type,
                  farmer.full_name AS farmer_name,buyer.full_name AS buyer_name
           FROM buyer_requests r JOIN listings l ON l.id=r.listing_id
           JOIN users farmer ON farmer.id=r.farmer_id JOIN users buyer ON buyer.id=r.buyer_id
           ORDER BY r.created_at DESC LIMIT 100"""
    ).fetchall()
    transactions = db.execute(
        """SELECT t.id,t.quantity,t.final_price,t.transaction_status,t.created_at,l.waste_type,
                  farmer.full_name AS farmer_name,buyer.full_name AS buyer_name
           FROM transactions t JOIN listings l ON l.id=t.listing_id
           JOIN users farmer ON farmer.id=t.farmer_id JOIN users buyer ON buyer.id=t.buyer_id
           ORDER BY t.created_at DESC LIMIT 100"""
    ).fetchall()
    registrations = db.execute(
        """SELECT substr(created_at,1,7) AS month,COUNT(*) AS total
           FROM users GROUP BY month ORDER BY month DESC LIMIT 6"""
    ).fetchall()
    monthly_reuse = db.execute(
        """SELECT substr(created_at,1,7) AS month,SUM(quantity) AS tonnes
           FROM transactions WHERE transaction_status='Completed'
           GROUP BY month ORDER BY month DESC LIMIT 6"""
    ).fetchall()
    waste_distribution = db.execute(
        """SELECT waste_type,SUM(quantity) AS tonnes FROM listings
           WHERE status!='Removed' GROUP BY waste_type ORDER BY tonnes DESC"""
    ).fetchall()
    summary = admin_summary(db).get_json()["stats"]
    return jsonify({
        "stats": summary,
        "users": [dict(row) for row in users],
        "listings": [dict(row) for row in listings],
        "requests": [dict(row) for row in requests],
        "transactions": [dict(row) for row in transactions],
        "analytics": {
            "registrations_by_month": [dict(row) for row in reversed(registrations)],
            "reuse_by_month": [dict(row) for row in reversed(monthly_reuse)],
            "waste_distribution": [dict(row) for row in waste_distribution],
        },
    })


@app.post("/api/admin/users/<int:user_id>/toggle")
@login_required("admin")
def admin_toggle_user(user_id):
    db = get_db()
    user = db.execute("SELECT id,role,is_active FROM users WHERE id=?", (user_id,)).fetchone()
    if user is None:
        return api_error("User not found.", 404)
    if user["role"] == "admin":
        return api_error("Administrator accounts cannot be disabled here.", 409)
    active = 0 if user["is_active"] else 1
    db.execute("UPDATE users SET is_active=? WHERE id=?", (active, user_id))
    db.commit()
    return jsonify({"ok": True, "is_active": active})


@app.post("/api/admin/listings/<int:listing_id>/verify")
@login_required("admin")
def admin_verify_listing(listing_id):
    db = get_db()
    row = db.execute("SELECT id,is_verified FROM listings WHERE id=?", (listing_id,)).fetchone()
    if row is None:
        return api_error("Listing not found.", 404)
    verified = 0 if row["is_verified"] else 1
    db.execute("UPDATE listings SET is_verified=? WHERE id=?", (verified, listing_id))
    db.commit()
    return jsonify({"ok": True, "is_verified": verified})


@app.post("/api/admin/requests/<int:request_id>/cancel")
@login_required("admin")
def admin_cancel_request(request_id):
    db = get_db()
    row = db.execute("SELECT * FROM buyer_requests WHERE id=?", (request_id,)).fetchone()
    if row is None:
        return api_error("Request not found.", 404)
    if row["status"] != "Pending":
        return api_error("Only pending requests can be cancelled by an administrator.", 409)
    db.execute("UPDATE buyer_requests SET status='Cancelled' WHERE id=?", (request_id,))
    active = db.execute(
        "SELECT COUNT(*) FROM buyer_requests WHERE listing_id=? AND status IN ('Pending','Accepted')",
        (row["listing_id"],),
    ).fetchone()[0]
    if active == 0:
        db.execute("UPDATE listings SET status='Open' WHERE id=? AND quantity>0", (row["listing_id"],))
    db.execute(
        "INSERT INTO notifications (user_id,message,notification_type) VALUES (?,?,?)",
        (row["buyer_id"], f"Request #{request_id} was cancelled by an administrator.", "request"),
    )
    db.commit()
    return jsonify({"ok": True, "status": "Cancelled"})


@app.get("/api/notifications")
@login_required()
def notifications():
    rows = get_db().execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 20",
        (g.user["id"],),
    ).fetchall()
    return jsonify({"notifications": [dict(row) for row in rows]})


@app.post("/api/notifications/read")
@login_required()
def mark_notifications_read():
    get_db().execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (g.user["id"],))
    get_db().commit()
    return jsonify({"ok": True})


@app.get("/api/impact")
def impact():
    db = get_db()
    totals = db.execute(
        """SELECT COALESCE(SUM(quantity),0) AS tonnes,COALESCE(SUM(quantity*final_price),0) AS earnings,
                  COUNT(*) AS transactions FROM transactions WHERE transaction_status='Completed'"""
    ).fetchone()
    distance_rows = db.execute(
        """SELECT farmer.latitude AS farmer_lat,farmer.longitude AS farmer_lon,
                  buyer.latitude AS buyer_lat,buyer.longitude AS buyer_lon
           FROM transactions t JOIN users farmer ON farmer.id=t.farmer_id
           JOIN users buyer ON buyer.id=t.buyer_id WHERE t.transaction_status='Completed'"""
    ).fetchall()
    distance = sum(
        haversine_km(row["farmer_lat"], row["farmer_lon"], row["buyer_lat"], row["buyer_lon"]) or 0
        for row in distance_rows
    )
    buyers = db.execute("SELECT COUNT(DISTINCT buyer_id) FROM transactions WHERE transaction_status='Completed'").fetchone()[0]
    return jsonify({"estimated": True, "tonnes_reused": round(totals["tonnes"], 1),
                    "farmer_revenue": round(totals["earnings"], 2), "connections": buyers,
                    "transactions": totals["transactions"], "distance_travelled_km": round(distance, 1),
                    "estimated_diverted_tonnes": round(totals["tonnes"], 1)})


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=os.environ.get("FLASK_DEBUG") == "1")
