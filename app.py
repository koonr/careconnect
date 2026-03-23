import os
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
from sqlalchemy.types import JSON

app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key-change-me")

# ✅ Safe DB config
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///app.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ------------------ MODELS ------------------

class User(db.Model):
    __tablename__ = "py_users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password = db.Column(db.Text, nullable=False)
    full_name = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20), default="")
    role = db.Column(db.String(20), default="parent")
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)


class CaregiverProfile(db.Model):
    __tablename__ = "py_caregiver_profiles"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("py_users.id"), unique=True, nullable=False)
    bio = db.Column(db.Text, nullable=False)
    experience_years = db.Column(db.Integer, nullable=False)

    # ✅ FIXED: JSON instead of ARRAY
    languages = db.Column(JSON, nullable=False)
    age_groups = db.Column(JSON, nullable=False)
    skills = db.Column(JSON, default=list)

    availability = db.Column(db.String(20), nullable=False)
    location = db.Column(db.String(255), nullable=False)
    hourly_rate = db.Column(db.Numeric(10, 2))
    is_available = db.Column(db.Boolean, default=True)
    status = db.Column(db.String(20), default="pending")
    contact_phone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    user = db.relationship("User", backref=db.backref("caregiver_profile", uselist=False))


class ContactRequest(db.Model):
    __tablename__ = "py_contact_requests"
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("py_users.id"), nullable=False)
    caregiver_id = db.Column(db.Integer, db.ForeignKey("py_caregiver_profiles.id"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    phone = db.Column(db.String(20))
    status = db.Column(db.String(20), default="pending")
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow)

    parent = db.relationship("User", backref="sent_requests")
    caregiver = db.relationship("CaregiverProfile", backref="received_requests")


# ------------------ HELPERS ------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "error")
            return redirect(url_for("login"))
        user = db.session.get(User, session["user_id"])
        if not user or user.role != "admin":
            flash("Admin access required.", "error")
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    if "user_id" in session:
        return db.session.get(User, session["user_id"])
    return None


@app.context_processor
def inject_globals():
    return {"current_user": get_current_user(), "now": datetime.utcnow}


# ------------------ ROUTES ------------------

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"]
        full_name = request.form["full_name"].strip()
        phone = request.form.get("phone", "").strip()

        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "error")
            return render_template("auth.html", mode="register")

        user = User(
            email=email,
            password=generate_password_hash(password),
            full_name=full_name,
            phone=phone,
            role="parent",
        )
        db.session.add(user)
        db.session.commit()
        session["user_id"] = user.id
        flash("Account created!", "success")
        return redirect(url_for("parent_dashboard"))

    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            session["user_id"] = user.id
            flash("Logged in!", "success")
            if user.role == "admin":
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("parent_dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("auth.html", mode="login")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("home"))


@app.route("/caregivers")
def browse():
    query = CaregiverProfile.query.filter_by(status="approved", is_available=True)

    location = request.args.get("location")
    language = request.args.get("language")
    age_group = request.args.get("age_group")
    availability = request.args.get("availability")

    if location:
        query = query.filter(CaregiverProfile.location.ilike(f"%{location}%"))

    # ✅ FIXED JSON filtering
    if language:
        query = query.filter(
            func.json_extract(CaregiverProfile.languages, '$').like(f'%{language}%')
        )

    if age_group:
        query = query.filter(
            func.json_extract(CaregiverProfile.age_groups, '$').like(f'%{age_group}%')
        )

    if availability:
        query = query.filter_by(availability=availability)

    caregivers = query.all()

    return render_template("browse.html", caregivers=caregivers,
                           filters={"location": location or "", "language": language or "",
                                    "age_group": age_group or "", "availability": availability or ""})


@app.route("/caregivers/<int:cid>")
def caregiver_detail(cid):
    cg = CaregiverProfile.query.get_or_404(cid)
    if cg.status != "approved":
        return redirect(url_for("browse"))
    return render_template("caregiver.html", cg=cg)


@app.route("/caregivers/<int:cid>/contact", methods=["POST"])
@login_required
def send_contact(cid):
    user = get_current_user()
    if user.role != "parent":
        flash("Only parents can send requests.", "error")
        return redirect(url_for("caregiver_detail", cid=cid))

    message = request.form["message"].strip()
    phone = request.form.get("phone", "").strip()

    if not message:
        flash("Please enter a message.", "error")
        return redirect(url_for("caregiver_detail", cid=cid))

    cr = ContactRequest(parent_id=user.id, caregiver_id=cid, message=message, phone=phone)
    db.session.add(cr)
    db.session.commit()
    flash("Contact request sent!", "success")
    return redirect(url_for("parent_dashboard"))


@app.route("/dashboard")
@login_required
def parent_dashboard():
    user = get_current_user()
    requests = ContactRequest.query.filter_by(parent_id=user.id).order_by(ContactRequest.created_at.desc()).all()
    return render_template("dashboard.html", requests=requests)


@app.route("/admin")
@admin_required
def admin_dashboard():
    stats = {
        "total_users": User.query.count(),
        "total_parents": User.query.filter_by(role="parent").count(),
        "total_caregivers": User.query.filter_by(role="caregiver").count(),
        "pending": CaregiverProfile.query.filter_by(status="pending").count(),
        "approved": CaregiverProfile.query.filter_by(status="approved").count(),
        "total_requests": ContactRequest.query.count(),
    }
    pending_cgs = CaregiverProfile.query.filter_by(status="pending").all()
    all_requests = ContactRequest.query.order_by(ContactRequest.created_at.desc()).all()
    return render_template("admin.html", stats=stats, pending_cgs=pending_cgs, all_requests=all_requests)


@app.route("/admin/caregivers/<int:cid>/<action>", methods=["POST"])
@admin_required
def admin_caregiver_action(cid, action):
    cg = CaregiverProfile.query.get_or_404(cid)
    if action == "approve":
        cg.status = "approved"
        flash(f"{cg.user.full_name} approved!", "success")
    elif action == "reject":
        cg.status = "rejected"
        flash(f"{cg.user.full_name} rejected.", "success")
    db.session.commit()
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/requests/<int:rid>/<action>", methods=["POST"])
@admin_required
def admin_request_action(rid, action):
    cr = ContactRequest.query.get_or_404(rid)
    if action in ("accepted", "rejected"):
        cr.status = action
        flash(f"Request {action}.", "success")
    db.session.commit()
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/add-caregiver", methods=["POST"])
@admin_required
def admin_add_caregiver():
    email = request.form["email"].strip()
    if User.query.filter_by(email=email).first():
        flash("Email already registered.", "error")
        return redirect(url_for("admin_dashboard"))

    user = User(
        email=email,
        password=generate_password_hash(request.form["password"]),
        full_name=request.form["full_name"].strip(),
        phone=request.form.get("phone", ""),
        role="caregiver",
    )
    db.session.add(user)
    db.session.flush()

    langs = [s.strip() for s in request.form["languages"].split(",") if s.strip()]
    ages = [s.strip() for s in request.form["age_groups"].split(",") if s.strip()]
    skills = [s.strip() for s in request.form.get("skills", "").split(",") if s.strip()]

    # ✅ FIXED numeric parsing
    hourly_rate = request.form.get("hourly_rate")
    hourly_rate = float(hourly_rate) if hourly_rate else None

    profile = CaregiverProfile(
        user_id=user.id,
        bio=request.form["bio"].strip(),
        experience_years=int(request.form["experience_years"]),
        languages=langs,
        age_groups=ages,
        availability=request.form["availability"],
        location=request.form["location"].strip(),
        hourly_rate=hourly_rate,
        skills=skills,
        is_available=True,
        status="approved",
        contact_phone=request.form.get("contact_phone", ""),
    )
    db.session.add(profile)
    db.session.commit()
    flash(f"Caregiver {user.full_name} created and approved!", "success")
    return redirect(url_for("admin_dashboard"))


def seed_data():
    if User.query.first():
        return

    admin = User(email="admin@careconnect.com", password=generate_password_hash("admin123"),
                 full_name="Admin User", phone="9876543210", role="admin")
    parent = User(email="parent@example.com", password=generate_password_hash("parent123"),
                  full_name="Priya Sharma", phone="9876543211", role="parent")
    cg1_user = User(email="anita@example.com", password=generate_password_hash("caregiver123"),
                    full_name="Anita Reddy", phone="9876543212", role="caregiver")
    cg2_user = User(email="lakshmi@example.com", password=generate_password_hash("caregiver123"),
                    full_name="Lakshmi Devi", phone="9876543213", role="caregiver")

    db.session.add_all([admin, parent, cg1_user, cg2_user])
    db.session.flush()

    cg1 = CaregiverProfile(
        user_id=cg1_user.id,
        bio="Experienced nanny with 8 years in childcare.",
        experience_years=8,
        languages=["Telugu", "Hindi", "English"],
        age_groups=["Infant", "Toddler"],
        availability="full_time",
        location="Hyderabad",
        hourly_rate=350,
        skills=["First Aid", "Cooking"],
        status="approved",
    )

    db.session.add(cg1)
    db.session.commit()


with app.app_context():
    db.create_all()
    seed_data()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)