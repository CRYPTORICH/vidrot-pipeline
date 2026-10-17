"""Apple passkeys via WebAuthn. Face ID or Touch ID confirms the owner."""
import json
import os
from urllib.parse import urlparse

from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json_dict
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidJSONStructure,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialHint,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from vidrot import db

RP_NAME = "vidrot"
USER_NAME = "owner"
REJECTED = "That passkey was not accepted."
# ES256 first: that is what an Apple passkey creates. RS256 is the other default
# so a browser does not refuse the ceremony.
ALGORITHMS = [
    COSEAlgorithmIdentifier.ECDSA_SHA_256,
    COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
]


def party(host, secure):
    """Origin and relying-party id for this request.

    VIDROT_ORIGIN and VIDROT_RP_ID override the request. On the EC2 host those
    are https://racksrewards.com and racksrewards.com. The path prefix is not
    part of a passkey.
    """
    origin = os.environ.get("VIDROT_ORIGIN", "").strip().rstrip("/")
    rp_id = os.environ.get("VIDROT_RP_ID", "").strip()
    if not origin:
        origin = _origin_from_host(host, secure)
    if not rp_id:
        rp_id = urlparse(origin).hostname or ""
    hostname = urlparse(origin).hostname or ""
    if not origin or not rp_id or not hostname:
        return None
    if hostname != rp_id and not hostname.endswith("." + rp_id):
        return None
    return origin, rp_id


def registration_options(folder, origin, rp_id):
    challenge = _new_challenge(folder, "register", origin, rp_id)
    existing = [
        PublicKeyCredentialDescriptor(id=row["credential_id"])
        for row in db.list_passkeys(folder)
    ]
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_name=USER_NAME,
        user_id=_user_handle(folder),
        user_display_name="vidrot",
        challenge=base64url_to_bytes(challenge),
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=existing,
        supported_pub_key_algs=ALGORITHMS,
        hints=[PublicKeyCredentialHint.CLIENT_DEVICE],
    )
    return {"ok": True, "publicKey": options_to_json_dict(options)}


def authentication_options(folder, origin, rp_id):
    if not db.list_passkeys(folder):
        return {"ok": False, "error": "No passkey is saved yet. Sign in with the password, then save one."}
    challenge = _new_challenge(folder, "login", origin, rp_id)
    options = generate_authentication_options(
        rp_id=rp_id,
        challenge=base64url_to_bytes(challenge),
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return {"ok": True, "publicKey": options_to_json_dict(options)}


def finish_registration(folder, credential):
    stored = _take(folder, credential, "register")
    if stored is None:
        return {"ok": False, "error": REJECTED}
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(stored["challenge"]),
            expected_origin=stored["origin"],
            expected_rp_id=stored["rp_id"],
            require_user_verification=True,
            supported_pub_key_algs=ALGORITHMS,
        )
    except (InvalidRegistrationResponse, InvalidJSONStructure, ValueError):
        return {"ok": False, "error": REJECTED}
    if db.get_passkey(folder, verified.credential_id):
        return {"ok": False, "error": "That passkey is already saved."}
    db.save_passkey(
        folder,
        verified.credential_id,
        verified.credential_public_key,
        verified.sign_count,
        verified.credential_backed_up,
    )
    return {"ok": True}


def finish_authentication(folder, credential):
    prepared = _der_signature(credential)
    stored = _take(folder, prepared, "login")
    if stored is None:
        return {"ok": False, "error": REJECTED}
    credential_id = _credential_id(prepared)
    if credential_id is None:
        return {"ok": False, "error": REJECTED}
    row = db.get_passkey(folder, credential_id)
    if row is None:
        return {"ok": False, "error": REJECTED}
    try:
        verified = verify_authentication_response(
            credential=prepared,
            expected_challenge=base64url_to_bytes(stored["challenge"]),
            expected_origin=stored["origin"],
            expected_rp_id=stored["rp_id"],
            credential_public_key=row["public_key"],
            credential_current_sign_count=row["sign_count"],
            require_user_verification=True,
        )
    except (InvalidAuthenticationResponse, InvalidJSONStructure, ValueError):
        return {"ok": False, "error": REJECTED}
    db.update_passkey_count(folder, verified.credential_id, verified.new_sign_count)
    return {"ok": True}


def passkey_count(folder):
    return len(db.list_passkeys(folder))


def passkey_list(folder):
    return [
        {
            "id": bytes_to_base64url(row["credential_id"]),
            "created_at": row["created_at"],
            "backed_up": row["backed_up"],
        }
        for row in db.list_passkeys(folder)
    ]


def remove_passkey(folder, credential_id_b64):
    try:
        credential_id = base64url_to_bytes(credential_id_b64 or "")
    except Exception:
        return False
    if not credential_id:
        return False
    return db.delete_passkey(folder, credential_id)


def _origin_from_host(host, secure):
    host = (host or "").strip()
    if not host or host.startswith("["):
        return ""
    hostname, sep, port = host.partition(":")
    if not hostname:
        return ""
    proto = "https" if secure else "http"
    if not sep or (proto == "https" and port == "443") or (proto == "http" and port == "80"):
        return f"{proto}://{hostname}"
    return f"{proto}://{hostname}:{port}"


def _user_handle(folder):
    saved = db.get_kv(folder, "passkey_user_id", "")
    if saved:
        return base64url_to_bytes(saved)
    from webauthn.helpers import generate_user_handle

    handle = generate_user_handle()
    db.put_kv(folder, "passkey_user_id", bytes_to_base64url(handle))
    return handle


def _new_challenge(folder, kind, origin, rp_id):
    from webauthn.helpers import generate_challenge

    challenge = bytes_to_base64url(generate_challenge())
    db.save_challenge(folder, challenge, kind, origin, rp_id)
    return challenge


def _take(folder, credential, kind):
    challenge = _challenge_text(credential)
    if not challenge:
        return None
    return db.take_challenge(folder, challenge, kind)


def _challenge_text(credential):
    if not isinstance(credential, dict):
        return ""
    response = credential.get("response")
    if not isinstance(response, dict):
        return ""
    encoded = response.get("clientDataJSON")
    if not isinstance(encoded, str) or not encoded:
        return ""
    try:
        payload = json.loads(base64url_to_bytes(encoded))
    except Exception:
        return ""
    challenge = payload.get("challenge") if isinstance(payload, dict) else ""
    return challenge if isinstance(challenge, str) else ""


def _credential_id(credential):
    raw_id = credential.get("rawId") if isinstance(credential, dict) else ""
    if not isinstance(raw_id, str) or not raw_id:
        return None
    try:
        return base64url_to_bytes(raw_id)
    except Exception:
        return None


def _der_signature(credential):
    """Apple sends a raw 64-byte P-256 signature. Verification wants DER."""
    if not isinstance(credential, dict):
        return credential
    response = credential.get("response")
    if not isinstance(response, dict) or not isinstance(response.get("signature"), str):
        return credential
    try:
        signature = base64url_to_bytes(response["signature"])
    except Exception:
        return credential
    if len(signature) != 64:
        return credential
    der = encode_dss_signature(
        int.from_bytes(signature[:32], "big"),
        int.from_bytes(signature[32:], "big"),
    )
    prepared = dict(credential)
    prepared["response"] = dict(response)
    prepared["response"]["signature"] = bytes_to_base64url(der)
    return prepared
