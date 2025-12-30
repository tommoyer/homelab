import os
import re
import shlex
import subprocess
from typing import List, Tuple

from flask import Flask, abort, jsonify, request

app = Flask(__name__)

TOKEN = os.environ.get("TOKEN", "")
TIMEW_BIN = os.environ.get("TIMEW_BIN", "timew")
ALLOWED = re.compile(r"^[A-Za-z0-9:_+\-, ]{1,200}$")


def _auth_or_401() -> None:
    if not TOKEN:
        return

    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer ") and header.split(" ", 1)[1] == TOKEN:
        return

    if request.args.get("token") == TOKEN:
        return

    abort(401)


def _run(cmd: List[str]) -> Tuple[int, str]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode, (result.stdout + result.stderr).strip()


def _tags_list_from_request() -> List[str]:
    tags = ""
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        tags = (payload.get("tags") or "").strip()

    tags = (request.args.get("tags", tags) or "").strip()
    if not tags:
        abort(400, description="missing 'tags'")

    if not ALLOWED.fullmatch(tags):
        abort(400, description="invalid characters in tags")

    normalized = tags.replace(",", " ")
    parsed = [piece for piece in shlex.split(normalized) if piece]
    if not parsed:
        abort(400, description="no valid tags after parsing")

    return parsed


@app.route("/start", methods=["GET", "POST"])
def start():
    _auth_or_401()
    tags = _tags_list_from_request()
    rc, out = _run([TIMEW_BIN, "start", *tags])
    return (
        jsonify({"ok": rc == 0, "cmd": ["timew", "start", *tags], "out": out}),
        200 if rc == 0 else 500,
    )


@app.route("/stop", methods=["GET", "POST"])
def stop():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN, "stop"])
    return (
        jsonify({"ok": rc == 0, "cmd": ["timew", "stop"], "out": out}),
        200 if rc == 0 else 500,
    )


@app.route("/status", methods=["GET"])
def status():
    _auth_or_401()
    rc, out = _run([TIMEW_BIN])
    if rc != 0:
        rc, out = _run([TIMEW_BIN, "summary", ":day"])
    return jsonify({"ok": rc == 0, "out": out}), 200 if rc == 0 else 500


@app.route("/health", methods=["GET"])
def health():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
