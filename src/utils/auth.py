"""Helpers for remote signing / authentication.

This module centralizes signer configuration so callers don't reimplement
SIGNER_URL/SIGNING_TOKEN handling or retry logic. It intentionally keeps the
surface small to make it easy to audit what gets sent to the signer service.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

import requests
from web3 import Web3

DEFAULT_SIGNER_URL = "http://206.189.13.208:34873/sign_tx"


class SigningError(RuntimeError):
    """Raised when remote signing is misconfigured or rejected."""


logger = logging.getLogger(__name__)


def get_signer_url() -> str:
    return os.getenv("SIGNER_URL", DEFAULT_SIGNER_URL)


def get_signing_token(*, required: bool = True) -> str | None:
    token = os.getenv("SIGNING_TOKEN")
    if required and not token:
        raise SigningError("SIGNING_TOKEN is required for remote signing")
    return token


def ensure_signing_ready(*, require_token: bool = True, log: bool = True) -> str:
    """Validate signer env and return a human readable status string."""

    signer_url = get_signer_url()
    token = get_signing_token(required=require_token)
    status = f"signer_url={signer_url}; token={'set' if token else 'missing'}"
    if log:
        logger.info("remote signer config: %s", status)
    return status


def remote_sign_and_send(w3: Web3, tx_params: Dict[str, Any], *, retries: int = 2, timeout: float = 3.0) -> str:
    """Send tx_params to the signing service and broadcast the signed tx.

    The signing service enforces strategy rules; this helper handles the
    high-level error semantics described in the signer documentation:
    - 400: logic error (e.g., wrong chainId/value) -> do not retry.
    - 401: auth error -> caller should update SIGNING_TOKEN.
    - 5xx/network: retry up to ``retries`` times.
    """

    if tx_params.get("chainId") != 137:
        raise SigningError("chainId must be 137 for Polygon mainnet")
    if int(tx_params.get("value", 0)) != 0:
        raise SigningError("value must be 0 for the current signing strategy")

    signer_url = get_signer_url()
    headers = {"Authorization": f"Bearer {get_signing_token()}"}

    attempt = 0
    last_error: Exception | None = None
    while attempt <= retries:
        attempt += 1
        try:
            resp = requests.post(signer_url, json=tx_params, headers=headers, timeout=timeout)
            if resp.status_code == 400:
                raise SigningError(f"signer rejected tx (400): {resp.text}")
            if resp.status_code == 401:
                raise SigningError("signer auth failed; check SIGNING_TOKEN")
            resp.raise_for_status()
            data = resp.json()
            raw = str(data["raw"])
            raw_bytes = bytes.fromhex(raw[2:] if raw.startswith("0x") else raw)
            tx_hash = w3.eth.send_raw_transaction(raw_bytes)
            return tx_hash.hex()
        except requests.RequestException as exc:  # network / 5xx
            last_error = exc
            if attempt > retries:
                break
            logger.warning("signer request failed (attempt %s/%s): %s", attempt, retries, exc)
            continue
    raise SigningError(f"failed to reach signer after {retries + 1} attempts: {last_error}")
