"""Thin GitHub fetch layer using raw.githubusercontent.com (or Contents API with token)."""
from __future__ import annotations

import base64
from typing import Optional

import requests

from core.config import (
    GITHUB_BRANCH,
    GITHUB_NOTES_DIR,
    GITHUB_OWNER,
    GITHUB_REPO,
    GITHUB_TOKEN,
)


class GitHubFetchError(RuntimeError):
    pass


def raw_url(filename):
    return (
        f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/"
        f"{GITHUB_BRANCH}/{GITHUB_NOTES_DIR}/{filename}"
    )


def contents_api_url(filename):
    return (
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/"
        f"{GITHUB_NOTES_DIR}/{filename}?ref={GITHUB_BRANCH}"
    )


def fetch_file(filename, timeout=10.0):
    if GITHUB_TOKEN:
        return _fetch_via_contents_api(filename, timeout=timeout)
    return _fetch_via_raw(filename, timeout=timeout)


def _fetch_via_raw(filename, timeout):
    url = raw_url(filename)
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise GitHubFetchError(f"network error fetching {url}: {exc}") from exc
    if resp.status_code == 404:
        raise GitHubFetchError(f"not found (404): {filename}")
    if not resp.ok:
        raise GitHubFetchError(
            f"GitHub returned {resp.status_code} for {filename}: {resp.text[:200]}"
        )
    return resp.text


def _fetch_via_contents_api(filename, timeout):
    url = contents_api_url(filename)
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise GitHubFetchError(f"network error fetching {url}: {exc}") from exc
    if resp.status_code == 404:
        raise GitHubFetchError(f"not found (404): {filename}")
    if not resp.ok:
        raise GitHubFetchError(
            f"GitHub returned {resp.status_code} for {filename}: {resp.text[:200]}"
        )
    payload = resp.json()
    if payload.get("encoding") != "base64":
        raise GitHubFetchError(
            f"unexpected encoding {payload.get('encoding')!r} for {filename}"
        )
    return base64.b64decode(payload["content"]).decode("utf-8", errors="replace")


def probe_file(filename, timeout=5.0):
    try:
        resp = requests.head(raw_url(filename), timeout=timeout)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        return int(resp.headers.get("Content-Length", "0"))
    except ValueError:
        return None
