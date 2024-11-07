from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
from . import mongo, client, db, users_collection, sessions_collection, mail, socketio
from .models import User
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer
from flask_mail import Message
from flask_login import login_user, login_required, logout_user, current_user
import pickle
from bson.objectid import ObjectId
import datetime 
import jwt
from functools import wraps
from os import getenv
from dotenv import load_dotenv

load_dotenv()

auth = Blueprint('auth', __name__)

SECRET_KEY = getenv("SECRET_KEY")

s = URLSafeTimedSerializer(SECRET_KEY) 

def generate_token(user_id):
    token = jwt.encode({
        'user_id': user_id,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }, SECRET_KEY, algorithm='HS256')
    return token

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('x-access-token')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 401
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            current_user_id = data['user_id']
        except:
            return jsonify({'message': 'Token is invalid!'}), 401
        return f(current_user_id, *args, **kwargs)
    return decorated

@auth.route("/register", methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.get_json()
        email = data.get('email')
        firstName = data.get('firstName')
        password1 = data.get('password')
        password2 = data.get('confirm_password')

        user = users_collection.find_one({"email":email})
        if user:
            return jsonify({"error": "Email already exists"}), 400
        elif password1 != password2:
            return jsonify({"error": "Passwords don't match"}), 400
        else:
            token = s.dumps(email, salt='email-confirm')

            msg = Message("Verify email", recipients=[email])
            link = url_for("auth.confirm_email", token=token, _external = True)
            msg.body = f"Please click on the link to verify your email: {link}"
            mail.send(msg)

            new_user = {
                "email": email,
                "firstName": firstName,
                "password": generate_password_hash(password1, method='pbkdf2:sha256'),
                "verified": False
            }
            users_collection.insert_one(new_user)

            # login_user(new_user, remember=True)
            # log_activity("signup", f"User {new_user.firstName} signed up")
            # log_activity("verification_email_sent", f"User {new_user.firstName} was sent the verification email")
            
            return jsonify({"message": "Verification mail sent"}), 201                    

    return jsonify({"message": "Signup endpoint ready"}), 200


@auth.route("/confirm_email/<token>")
def confirm_email(token):
    try:
        email = s.loads(token, salt='email-confirm', max_age=3600)
    except:
        return jsonify({"error": "Invalid or Expired token"}), 400
    
    user = users_collection.find_one({"email": email})
    
    if user:
        if user.get("verified"):
            return jsonify({"message": "Account already confirmed. Please login!"}), 200
        else:
            users_collection.update_one({"email": email}, {"$set": {"verified": True}})    
            user_id = str(user["_id"])
            new_user = User(str(user_id), user["email"])
            # login_user(new_user)    
            jwt_token = generate_token(user_id)                
            # log_activity("user_verified", f"User {user.firstName} verified their email")
            return jsonify({"message": "Email confirmed! You can now login!", "jwt_token": jwt_token}), 200
    else:
        return jsonify({"error": "Invalid email! Please signup"}), 400


@auth.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')

        user = users_collection.find_one({"email": email})

        if user:
            if check_password_hash(user.get("password"), password):
                if user.get("verified"):
                    # login_user(user, remember=True)
                    # log_activity("login", f"User {user.firstName} logged in")
                    user_json = pickle.dumps(user)
                    session['user'] = user_json
                    user_id = str(user["_id"])  
                    jwt_token = generate_token(user_id)
                    return jsonify({"message": "Logged in successfully", "jwt_token": jwt_token}), 200
                else:
                    return jsonify({"error": "Email not verified! Please verify your email"}), 400
            else:
                return jsonify({"error": "Incorrect password"}),400
                # log_activity("failed_login_attempt", f"User {user.firstName} entered incorrect password")
                
        else:
            return jsonify({"error": "User does not exist"}), 400            
            # log_activity("failed_login_attempt", f"User does not exist")

    return jsonify({"message": "Login endpoint ready"}), 200


@auth.route("/logout")
@token_required
def logout(current_user_id):
    token = request.headers.get('x-access-token')
    if not token:
        return jsonify({"message": "Token is missing!"}), 400
    logout_user()
    session.pop('user', None)
    return jsonify({"message": "Logged out successfully"}), 200