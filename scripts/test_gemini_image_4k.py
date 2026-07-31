from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlparse

from curl_cffi.requests import Session
from PIL import Image


MARKDOWN_IMAGE_URL_PATTERN = re.compile(r"!\[[^\]]*\]\((https?://[^\s)]+)\)", re.IGNORECASE)


def clean(value: object) -> str:
    return str(value or "").strip()


def build_generate_url(base_url: str, model: str) -> str:
    normalized_base = base_url.rstrip("/")
    segments = [segment for segment in urlparse(normalized_base).path.split("/") if segment]
    if not segments or segments[-1].lower() not in {"v1", "v1beta", "v1alpha"}:
        normalized_base = f"{normalized_base}/v1beta"
    model_resource = "/".join(quote(part, safe="") for part in model.removeprefix("models/").split("/"))
    return f"{normalized_base}/models/{model_resource}:generateContent/"


def response_diagnostic(payload: object) -> str:
    if not isinstance(payload, dict):
        return f"response_type={type(payload).__name__}"
    details = [f"top_level={','.join(sorted(str(key) for key in payload)) or 'empty'}"]
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        details.append(f"candidates={len(candidates)}")
        part_shapes: list[str] = []
        finish_reasons: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            finish_reason = clean(candidate.get("finishReason") or candidate.get("finish_reason"))
            if finish_reason and finish_reason not in finish_reasons:
                finish_reasons.append(finish_reason)
            content = candidate.get("content")
            parts = content.get("parts") if isinstance(content, dict) else None
            if isinstance(parts, list):
                for part in parts:
                    if isinstance(part, dict):
                        shape = "+".join(sorted(str(key) for key in part)) or "empty"
                        if shape not in part_shapes:
                            part_shapes.append(shape)
        if finish_reasons:
            details.append(f"finish_reason={','.join(finish_reasons)}")
        if part_shapes:
            details.append(f"part_keys={','.join(part_shapes)}")
    usage = payload.get("usageMetadata") or payload.get("usage_metadata")
    if isinstance(usage, dict):
        details.append(
            "usage="
            + json.dumps(
                {key: value for key, value in usage.items() if isinstance(value, (int, float, str, bool))},
                ensure_ascii=True,
                separators=(",", ":"),
            )
        )
    return "; ".join(details)


def candidate_parts(payload: object) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        return []
    result: list[dict[str, object]] = []
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return result
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        if isinstance(parts, list):
            result.extend(part for part in parts if isinstance(part, dict))
    return result


def extract_image(payload: object) -> tuple[bytes | None, str, str]:
    for part in candidate_parts(payload):
        inline_data = part.get("inlineData") or part.get("inline_data")
        if isinstance(inline_data, dict):
            encoded = clean(inline_data.get("data"))
            if encoded:
                mime_type = clean(inline_data.get("mimeType") or inline_data.get("mime_type")) or "image/png"
                return base64.b64decode(encoded), mime_type, "candidates.content.parts.inlineData"
        file_data = part.get("fileData") or part.get("file_data")
        if isinstance(file_data, dict):
            file_uri = clean(file_data.get("fileUri") or file_data.get("file_uri") or file_data.get("url"))
            if file_uri:
                mime_type = clean(file_data.get("mimeType") or file_data.get("mime_type")) or "image/png"
                return None, mime_type, file_uri
        text = clean(part.get("text"))
        markdown_url = MARKDOWN_IMAGE_URL_PATTERN.search(text)
        if markdown_url:
            return None, "image/png", markdown_url.group(1)
        if text.startswith(("http://", "https://")) and not any(character.isspace() for character in text):
            return None, "image/png", text

    if isinstance(payload, dict):
        for key in ("data", "images", "predictions", "generatedImages", "generated_images"):
            items = payload.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                encoded = clean(
                    item.get("b64_json")
                    or item.get("base64")
                    or item.get("imageBase64")
                    or item.get("image_base64")
                )
                if encoded:
                    return base64.b64decode(encoded), "image/png", key
                image_url = clean(item.get("url") or item.get("fileUri") or item.get("file_uri"))
                if image_url:
                    return None, "image/png", image_url
    return None, "", ""


def output_path_for_image(path: Path, mime_type: str) -> Path:
    suffix_by_mime = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    suffix = suffix_by_mime.get(mime_type.lower(), path.suffix or ".png")
    return path.with_suffix(suffix)


def main() -> int:
    parser = argparse.ArgumentParser(description="Directly test a Gemini native image request.")
    parser.add_argument("--base-url", default="https://api.usora.net")
    parser.add_argument("--model", default="gemini-3.1-flash-image")
    parser.add_argument("--aspect-ratio", default="16:9")
    parser.add_argument("--image-size", default="4K", choices=("1K", "2K", "4K"))
    parser.add_argument(
        "--response-format",
        default="base64",
        choices=("base64", "url", "both"),
        help="Map to Gemini responseModalities: IMAGE, TEXT, or IMAGE+TEXT.",
    )
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--prompt",
        default=(
            "Create a clean cinematic landscape of a modern observatory at sunrise, "
            "with crisp architectural detail, natural lighting, and no text."
        ),
    )
    parser.add_argument("--output", type=Path, default=Path("data/gemini-4k-direct-test.png"))
    args = parser.parse_args()

    api_key = clean(os.environ.get("GEMINI_API_KEY"))
    if not api_key:
        print("GEMINI_API_KEY is required", file=sys.stderr)
        return 2

    endpoint = build_generate_url(args.base_url, args.model)
    response_modalities = {
        "base64": ["IMAGE"],
        "url": ["TEXT"],
        "both": ["IMAGE", "TEXT"],
    }[args.response_format]
    request_body = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": args.prompt}],
            }
        ],
        "generationConfig": {
            "responseModalities": response_modalities,
            "imageConfig": {
                "aspectRatio": args.aspect_ratio,
                "imageSize": args.image_size,
            },
        },
    }

    print(f"endpoint={endpoint}", flush=True)
    print(
        f"model={args.model} aspect_ratio={args.aspect_ratio} image_size={args.image_size} "
        f"response_format={args.response_format} response_modalities={','.join(response_modalities)} "
        f"timeout={args.timeout}s",
        flush=True,
    )
    started_at = time.monotonic()
    session = Session()
    session.headers.update(
        {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
    )
    try:
        response = session.post(endpoint, json=request_body, timeout=args.timeout)
    except Exception as exc:
        elapsed = time.monotonic() - started_at
        print(f"request_error={type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"elapsed_seconds={elapsed:.3f}", file=sys.stderr)
        return 1
    finally:
        session.close()

    elapsed = time.monotonic() - started_at
    print(f"http_status={response.status_code} elapsed_seconds={elapsed:.3f}", flush=True)
    if not response.ok:
        print(f"response_body={response.text[:2000]}", file=sys.stderr)
        return 1

    try:
        payload = response.json()
    except Exception as exc:
        print(f"invalid_json={type(exc).__name__}: {exc}", file=sys.stderr)
        print(f"response_body={response.text[:2000]}", file=sys.stderr)
        return 1

    print(response_diagnostic(payload), flush=True)
    image_data, mime_type, source = extract_image(payload)
    if image_data is None and source.startswith(("http://", "https://")):
        download_session = Session()
        try:
            downloaded = download_session.get(source, timeout=120)
        finally:
            download_session.close()
        if not downloaded.ok:
            print(f"image_download_status={downloaded.status_code}", file=sys.stderr)
            return 1
        image_data = bytes(downloaded.content or b"")
        print(f"image_source=url", flush=True)
    elif image_data is not None:
        print(f"image_source={source}", flush=True)

    if not image_data:
        print("response did not contain image data", file=sys.stderr)
        return 1

    output_path = output_path_for_image(args.output.resolve(), mime_type)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_data)
    try:
        with Image.open(io.BytesIO(image_data)) as image:
            image.load()
            width, height = image.size
            image_format = image.format or "unknown"
    except Exception as exc:
        print(f"saved_image_validation_error={type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"image_format={image_format} dimensions={width}x{height} bytes={len(image_data)}", flush=True)
    print(f"saved_to={output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
