"""Image generation extension — pluggable backends for AI-generated images.

Supported backends:
- grok: xAI Grok-2 image generation (api.x.ai)
- openai: DALL-E 3 (api.openai.com)
- comfyui: Local ComfyUI instance
"""

from __future__ import annotations

import base64
import logging
from abc import ABC, abstractmethod
from pathlib import Path

import httpx

log = logging.getLogger(__name__)


class ImageBackend(ABC):
    """Abstract interface for image generation."""

    @abstractmethod
    async def generate(self, prompt: str, output_path: Path) -> Path | None:
        """Generate an image from a prompt, save to output_path. Returns path or None."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        ...


class GrokImageBackend(ImageBackend):
    """xAI Grok image generation via OpenAI-compatible API."""

    def __init__(self, api_key: str, url: str = "https://api.x.ai/v1",
                 model: str = "grok-imagine-image"):
        self.api_key = api_key
        self.url = url.rstrip("/")
        self.model = model

    async def generate(self, prompt: str, output_path: Path) -> Path | None:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self.url}/images/generations",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "n": 1,
                        "response_format": "b64_json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                b64 = data["data"][0]["b64_json"]
                img_bytes = base64.b64decode(b64)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(img_bytes)
                log.info(f"Generated image: {output_path} ({len(img_bytes)} bytes)")
                return output_path

        except Exception as e:
            log.error(f"Grok image generation failed: {e}")
            return None

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return resp.status_code == 200
        except Exception:
            return False


class OpenAIImageBackend(ImageBackend):
    """OpenAI DALL-E image generation."""

    def __init__(self, api_key: str, url: str = "https://api.openai.com/v1",
                 model: str = "dall-e-3"):
        self.api_key = api_key
        self.url = url.rstrip("/")
        self.model = model

    async def generate(self, prompt: str, output_path: Path) -> Path | None:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self.url}/images/generations",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "n": 1,
                        "size": "1024x1024",
                        "response_format": "b64_json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                b64 = data["data"][0]["b64_json"]
                img_bytes = base64.b64decode(b64)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(img_bytes)
                log.info(f"Generated image: {output_path} ({len(img_bytes)} bytes)")
                return output_path

        except Exception as e:
            log.error(f"OpenAI image generation failed: {e}")
            return None

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return resp.status_code == 200
        except Exception:
            return False


class ComfyUIImageBackend(ImageBackend):
    """Local ComfyUI image generation."""

    def __init__(self, url: str = "http://localhost:8188"):
        self.url = url.rstrip("/")

    async def generate(self, prompt: str, output_path: Path) -> Path | None:
        # Simple txt2img via ComfyUI API
        workflow = {
            "prompt": {
                "3": {
                    "class_type": "KSampler",
                    "inputs": {
                        "seed": -1,
                        "steps": 20,
                        "cfg": 7,
                        "sampler_name": "euler",
                        "scheduler": "normal",
                        "denoise": 1,
                        "model": ["4", 0],
                        "positive": ["6", 0],
                        "negative": ["7", 0],
                        "latent_image": ["5", 0],
                    },
                },
                "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
                "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
                "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
                "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "ugly, blurry, low quality", "clip": ["4", 1]}},
                "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
                "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "sentara", "images": ["8", 0]}},
            }
        }

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(f"{self.url}/prompt", json=workflow)
                resp.raise_for_status()
                data = resp.json()
                prompt_id = data.get("prompt_id")

                # Poll for completion
                import asyncio
                for _ in range(60):
                    await asyncio.sleep(5)
                    hist = await client.get(f"{self.url}/history/{prompt_id}")
                    if hist.status_code == 200:
                        hist_data = hist.json()
                        if prompt_id in hist_data:
                            outputs = hist_data[prompt_id].get("outputs", {})
                            for node_id, output in outputs.items():
                                images = output.get("images", [])
                                if images:
                                    img_info = images[0]
                                    img_resp = await client.get(
                                        f"{self.url}/view",
                                        params={"filename": img_info["filename"], "subfolder": img_info.get("subfolder", ""), "type": img_info.get("type", "output")},
                                    )
                                    if img_resp.status_code == 200:
                                        output_path.parent.mkdir(parents=True, exist_ok=True)
                                        output_path.write_bytes(img_resp.content)
                                        log.info(f"ComfyUI generated image: {output_path}")
                                        return output_path

                log.warning("ComfyUI generation timed out")
                return None

        except Exception as e:
            log.error(f"ComfyUI image generation failed: {e}")
            return None

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.url}/system_stats")
                return resp.status_code == 200
        except Exception:
            return False


def create_image_backend(backend: str, **kwargs) -> ImageBackend | None:
    """Factory function to create the right image backend."""
    if backend == "grok":
        api_key = kwargs.get("api_key", "")
        if not api_key:
            log.warning("Grok image gen enabled but no API key set")
            return None
        return GrokImageBackend(
            api_key=api_key,
            url=kwargs.get("url", "https://api.x.ai/v1"),
            model=kwargs.get("model", "grok-imagine-image"),
        )
    elif backend == "openai":
        api_key = kwargs.get("api_key", "")
        if not api_key:
            log.warning("OpenAI image gen enabled but no API key set")
            return None
        return OpenAIImageBackend(
            api_key=api_key,
            url=kwargs.get("url", "https://api.openai.com/v1"),
            model=kwargs.get("model", "dall-e-3"),
        )
    elif backend == "comfyui":
        return ComfyUIImageBackend(url=kwargs.get("url", "http://localhost:8188"))
    else:
        log.warning(f"Unknown image backend: {backend}")
        return None
