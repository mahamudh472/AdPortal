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


def generate_copy(product, audience, benefits, tone, copy_type):

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


def generate_ad_copy(product_service, target_audience, key_benefits, tone):
    """
    Generates high-quality ad copy with strict tone adherence and richer descriptions.
    """
    client = get_openai_client()

    # --- ADVANCED PROMPT ENGINEERING ---
    # We give the AI specific instructions on how to handle different tones.
    
    tone_instructions = {
        "Professional": "Use formal, authoritative, and trust-building language. Focus on value, efficiency, and quality. No slang. Minimal emojis.",
        "Friendly": "Be conversational, warm, and relatable. Use 'You' and 'We'. It's okay to use 1-2 relevant emojis.",
        "Urgent": "Use short, punchy sentences. Focus on FOMO (Fear Of Missing Out), limited time, and immediate action.",
        "Luxury": "Use sophisticated, elegant vocabulary. Focus on exclusivity, premium quality, and status.",
        "Witty": "Be clever, playful, and humorous. Use puns or wordplay if appropriate for the product."
    }
    
    # Get the specific instruction for the selected tone, or default to professional
    selected_tone_instruction = tone_instructions.get(tone, tone_instructions["Professional"])

    system_prompt = f"""
    You are an elite Senior Marketing Copywriter with 10 years of experience.
    Your goal is to write high-converting Facebook and Instagram ad copy.
    
    STRICT TONE GUIDELINES:
    The user has selected the tone: '{tone}'.
    Instruction: {selected_tone_instruction}
    
    OUTPUT REQUIREMENTS:
    You must return a valid JSON object with these exact keys:
    
    1. "headline": A powerful hook. (Max 50 characters).
       - If Professional: Focus on the main result.
       - If Friendly: Focus on the feeling.
       
    2. "primary_text": The main body of the ad. (2-4 sentences, Max 300 characters).
       - Elaborate on the 'Key Benefits' provided.
       
    3. "description": A detailed and persuasive link description. (Max 150 characters).
       - Do NOT be short. Write 1-2 complete sentences.
       - Explain specifically *why* this offer is valuable or add social proof.
       - Example: "Join 10,000+ happy customers who have upgraded their style. Includes a 30-day money-back guarantee."
       
    4. "call_to_action": The best button choice (e.g., Learn More, Shop Now, Sign Up).
    """

    user_prompt = f"""
    Here are the product details. Write the ad copy now.
    
    Product/Service: {product_service}
    Target Audience: {target_audience}
    Key Benefits: {key_benefits}
    Tone: {tone}
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o",  # Use gpt-4o or gpt-4-turbo for high quality. gpt-3.5 is too simple.
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.75 # Slightly higher creativity
        )
        
        content = response.choices[0].message.content
        parsed_output = json.loads(content)

        return {
            "headline": parsed_output.get("headline"),
            "primary_text": parsed_output.get("primary_text"),
            "description": parsed_output.get("description"),
            "call_to_action": parsed_output.get("call_to_action"),

        
            "success": True
    }
    

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


