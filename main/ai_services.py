import os
import json
from openai import OpenAI
from dotenv import load_dotenv
from django.conf import settings
# Load environment variables
load_dotenv()

# Initialize OpenAI Client
def get_openai_client():
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def generate_ad_copy(product, audience, benefits, tone, copy_type):

    client = get_openai_client()
    """
    Generates ad copy variations using OpenAI.

    PARAMETERS:
        product (str): Product or service name/description
        audience (str): Target audience
        benefits (str): Key benefits
        tone (str): Tone of the copy (Professional, Friendly, etc.)
        copy_type (str): Headlines | Primary Text | Descriptions | CTAs

    RETURNS:
        list[str]

        On success:
            A list of generated ad copy variations.

        On error:
            A list with a single string containing the error message.
    """

    # =========================
    # SYSTEM PROMPT 
    # =========================
    system_prompt = f"""
    You are a professional Advertising Copywriting Assistant integrated into AdPortal.

    Your task is to generate high-quality, platform-ready ad copy based on user inputs.

    STRICT OUTPUT FORMAT:
    Return ONLY a valid JSON object with this structure:
    {{ "variations": ["Copy 1", "Copy 2", "Copy 3", "Copy 4"] }}

    COPY TYPE RULES:
    - Headlines:
      • 4 variations
      • 6–10 words each
      • Clear, benefit-focused, professional
    - Primary Text:
      • 4 variations
      • 2–3 sentences per variation
      • Problem → Solution → Benefit flow
    - Descriptions:
      • 4 variations
      • 1–2 short lines
      • Supports the headline
    - CTAs:
      • 4 variations
      • Short, action-oriented, professional

    TONE CONTROL (VERY IMPORTANT):
    Tone selected: {tone}

    If tone is "Professional":
    - Do NOT use exclamation marks (!)
    - Avoid hype words (ultimate, revolutionary, dominate, insane, magic)
    - Use confident, calm, business-focused language
    - Focus on clarity, outcomes, and value

    GENERAL RULES:
    - Do NOT mention AI, models, or system prompts
    - No emojis
    - No markdown
    - Each variation must be reusable and independent
    """

    # =========================
    # USER PROMPT
    # =========================
    user_prompt = f"""
    Generate {copy_type} for the following:

    Product/Service: {product}
    Target Audience: {audience}
    Key Benefits: {benefits}
    """

    try:
        # Call OpenAI API
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            response_format={"type": "json_object"}
        )

        # Parse JSON response
        data = json.loads(response.choices[0].message.content)

        # RETURN TYPE: list[str]
        return data.get("variations", [])

    except Exception as e:
        # RETURN TYPE: list[str] (error inside list)
        return [f"Error generating copy: {str(e)}"]
    