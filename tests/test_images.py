"""Tests for the image downloader — success, failure, edge cases."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from web_clip_helper.images import download_images


# ── Helpers ──────────────────────────────────────────────────────────


def _make_response(
    status_code: int = 200,
    content: bytes = b"\xff\xd8\xff\xe0",  # JPEG magic bytes
    content_type: str = "image/jpeg",
) -> httpx.Response:
    """Build a fake httpx.Response."""
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://img.example.com/test.jpg"),
    )


# ── Success cases ───────────────────────────────────────────────────


class TestDownloadImagesSuccess:
    def test_single_image(self, tmp_path: Path):
        """Download one image successfully."""
        target = tmp_path / "images"
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = _make_response()

            result = download_images(
                ["https://img.example.com/photo.jpg"],
                target,
            )

        assert len(result) == 1
        local = result["https://img.example.com/photo.jpg"]
        assert local.startswith("images/")
        assert local.endswith(".jpg")
        assert (tmp_path / local).exists()

    def test_multiple_images(self, tmp_path: Path):
        """Download multiple images with sequential naming."""
        target = tmp_path / "images"
        urls = [
            "https://img.example.com/a.jpg",
            "https://img.example.com/b.png",
            "https://img.example.com/c.gif",
        ]
        responses = [
            _make_response(content_type="image/jpeg"),
            _make_response(content_type="image/png", content=b"\x89PNG"),
            _make_response(content_type="image/gif", content=b"GIF89a"),
        ]

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = responses

            result = download_images(urls, target)

        assert len(result) == 3
        filenames = list(result.values())
        assert "images/img_001.jpg" in filenames
        assert "images/img_002.png" in filenames
        assert "images/img_003.gif" in filenames

    def test_referer_header_sent(self, tmp_path: Path):
        """Referer header is included in the request when provided."""
        target = tmp_path / "images"
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = _make_response()

            download_images(
                ["https://img.example.com/photo.jpg"],
                target,
                referer="https://example.com/page",
            )

            call_kwargs = mock_client.get.call_args
            assert call_kwargs[1]["headers"]["Referer"] == "https://example.com/page"

    def test_extension_from_url_when_no_content_type(self, tmp_path: Path):
        """Falls back to URL extension when Content-Type is missing."""
        target = tmp_path / "images"
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = _make_response(
                content_type="",  # empty content-type
            )

            result = download_images(
                ["https://img.example.com/photo.png"],
                target,
            )

        local = result["https://img.example.com/photo.png"]
        assert local.endswith(".png")


# ── Failure cases ───────────────────────────────────────────────────


class TestDownloadImagesFailure:
    def test_404_falls_back_to_original_url(self, tmp_path: Path):
        """A 404 response keeps the original URL in the mapping."""
        target = tmp_path / "images"
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = _make_response(status_code=404)

            result = download_images(
                ["https://img.example.com/missing.jpg"],
                target,
            )

        url = "https://img.example.com/missing.jpg"
        assert result[url] == url  # fallback to original

    def test_500_falls_back_to_original_url(self, tmp_path: Path):
        """A 500 response keeps the original URL in the mapping."""
        target = tmp_path / "images"
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = _make_response(status_code=500)

            result = download_images(
                ["https://img.example.com/error.jpg"],
                target,
            )

        url = "https://img.example.com/error.jpg"
        assert result[url] == url

    def test_timeout_falls_back_to_original_url(self, tmp_path: Path):
        """A timeout falls back to original URL."""
        target = tmp_path / "images"
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = httpx.TimeoutException("timed out")

            result = download_images(
                ["https://img.example.com/slow.jpg"],
                target,
            )

        url = "https://img.example.com/slow.jpg"
        assert result[url] == url

    def test_connection_error_falls_back(self, tmp_path: Path):
        """A connection error falls back to original URL."""
        target = tmp_path / "images"
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.side_effect = httpx.ConnectError("refused")

            result = download_images(
                ["https://img.example.com/down.jpg"],
                target,
            )

        url = "https://img.example.com/down.jpg"
        assert result[url] == url


# ── Mixed success/failure ───────────────────────────────────────────


class TestDownloadImagesMixed:
    def test_mixed_success_and_failure(self, tmp_path: Path):
        """Some images succeed, some fail — mapping is correct for both."""
        target = tmp_path / "images"
        urls = [
            "https://img.example.com/ok.jpg",
            "https://img.example.com/missing.jpg",
        ]

        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            # First image: success. Second image: 404 on both retries.
            mock_client.get.side_effect = [
                _make_response(status_code=200),
                _make_response(status_code=404),
                _make_response(status_code=404),
            ]

            result = download_images(urls, target)

        # First succeeded
        assert result["https://img.example.com/ok.jpg"].startswith("images/")
        # Second failed — original URL
        assert result["https://img.example.com/missing.jpg"] == "https://img.example.com/missing.jpg"


# ── Edge cases ──────────────────────────────────────────────────────


class TestDownloadImagesEdgeCases:
    def test_empty_url_list(self, tmp_path: Path):
        """Empty input returns empty mapping."""
        result = download_images([], tmp_path / "images")
        assert result == {}

    def test_duplicate_urls_downloaded_once(self, tmp_path: Path):
        """Duplicate URLs are deduplicated — only downloaded once."""
        target = tmp_path / "images"
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = _make_response()

            result = download_images(
                [
                    "https://img.example.com/dup.jpg",
                    "https://img.example.com/dup.jpg",
                    "https://img.example.com/dup.jpg",
                ],
                target,
            )

        # Only one download, but mapping has one entry
        assert len(result) == 1
        assert mock_client.get.call_count == 1

    def test_creates_target_dir(self, tmp_path: Path):
        """Target directory is created automatically."""
        target = tmp_path / "deep" / "nested" / "images"
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = _make_response()

            download_images(["https://img.example.com/a.jpg"], target)

        assert target.exists()

    def test_default_extension_is_jpg(self, tmp_path: Path):
        """When no extension detectable, defaults to .jpg."""
        target = tmp_path / "images"
        with patch("httpx.Client") as MockClient:
            mock_client = MockClient.return_value.__enter__.return_value
            mock_client.get.return_value = _make_response(content_type="application/octet-stream")

            result = download_images(
                ["https://img.example.com/noext"],
                target,
            )

        local = result["https://img.example.com/noext"]
        assert local.endswith(".jpg")
