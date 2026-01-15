import base64
import json
import re

from openai import OpenAI

from app.schemas import InstrumentDescription
from app.settings import get_settings
from app.vlm.prompts import DESCRIPTION_PROMPT


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("No JSON object found in VLM response")
    return json.loads(match.group(0))


def create_vlm_client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=settings.openai_api_key)


def build_image_data_url(image_bytes: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:{mime_type};base64,{encoded}"


def request_description(client: OpenAI, image_url: str) -> str:
    settings = get_settings()
    response = client.responses.create(
        model=settings.openai_vlm_model,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": DESCRIPTION_PROMPT},
                    {"type": "input_image", "image_url": image_url},
                ],
            }
        ],
    )
    return response.output_text


def parse_description(output_text: str) -> InstrumentDescription:
    data = _extract_json(output_text)
    return InstrumentDescription.model_validate(data)


def describe_instrument(image_bytes: bytes, mime_type: str) -> InstrumentDescription:
    client = create_vlm_client()
    image_url = build_image_data_url(image_bytes, mime_type)
    output_text = request_description(client, image_url)
    return parse_description(output_text)
