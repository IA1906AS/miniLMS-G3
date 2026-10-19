"""Layer 1 (authentication) and layer 7 (brute-force lockout)."""
import time

import bcrypt
import jwt

from .errors import AccountLocked, InvalidCredentials, Unauthenticated

BCRYPT_ROUNDS = 10  # requirement: cost >= 10
MAX_FAILED = 5
LOCK_SECONDS = 15 * 60
_MAX_TRACKED = 10_000
_clock = time.time  # replaceable in tests


# ---- password hashing ----
def hash_password(password):
    data = password.encode("utf-8")
    if len(data) > 72:
        raise ValueError("password too long for bcrypt")
    return bcrypt.hashpw(data, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password, hashed):
    data = password.encode("utf-8")
    try:
        if len(data) > 72:  # bcrypt limit: never match, but still burn similar time
            bcrypt.checkpw(b"x", hashed.encode("ascii"))
            return False
        return bcrypt.checkpw(data, hashed.encode("ascii"))
    except ValueError:
        return False


# ---- tokens ----
def issue_token(user_id, secret, ttl):
    iat = int(_clock())
    payload = {"sub": user_id, "iat": iat, "exp": iat + int(ttl)}  # only sub/iat/exp
    return jwt.encode(payload, secret, algorithm="HS256")


def authenticate(token, secret, state):
    """Return the public actor dict for a valid token, else raise Unauthenticated.
    Role is always re-read from the store, never from the token."""
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "sub"]},
        )
    except (jwt.PyJWTError, ValueError, TypeError):
        raise Unauthenticated()
    sub = claims.get("sub")
    user = state.get_user(sub)
    if user is None:  # user removed since token was issued
        raise Unauthenticated()
    return state.public_user(user)


# ---- login with lockout ----
def _purge(attempts, now):
    if len(attempts) > _MAX_TRACKED:
        for k in [k for k, r in attempts.items() if r["locked_until"] <= now]:
            del attempts[k]


def login(state, email, password, secret, ttl):
    key = email.strip().lower()
    with state.lock:  # serialised so parallel guesses cannot bypass the counter
        now = _clock()
        attempts = state.login_attempts
        rec = attempts.get(key)
        if rec and rec["locked_until"]:
            if rec["locked_until"] > now:
                raise AccountLocked(retry_after=rec["locked_until"] - now)
            del attempts[key]  # lock expired -> fresh start
            rec = None

        user = state.find_user_by_email(key)
        # Always run bcrypt (dummy hash when user is unknown) so both failures look alike.
        hashed = user["password_hash"] if user else state.dummy_hash
        ok = verify_password(password, hashed) and user is not None

        if not ok:
            _purge(attempts, now)
            rec = attempts.setdefault(key, {"fails": 0, "locked_until": 0})
            rec["fails"] += 1
            if rec["fails"] >= MAX_FAILED:
                rec["locked_until"] = now + LOCK_SECONDS
            raise InvalidCredentials()

        attempts.pop(key, None)  # success before threshold resets the counter
        return issue_token(user["id"], secret, ttl)
