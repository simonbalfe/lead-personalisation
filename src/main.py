import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_ai import Agent
import logfire
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openrouter import OpenRouterProvider

class Config(BaseModel):
    """
    Configuration for connecting to external services and models.
    """
    google_sheet_id: str
    google_sheet_name: str
    openrouter_api_key: str
    openrouter_model: str

class LeadData(BaseModel):
    """
    Data model representing a lead's details.
    """
    owner_name: str = Field(description="Owner/Contact name")
    business_summary: str = Field(description="Summary of the business")
    review_summary: str = Field(description="Summary of customer reviews")

class PersonalizedMessage(BaseModel):
    """
    Model representing a personalized WhatsApp message.
    """
    phone_number: str
    dm_opener: str

async def personalize_lead(lead: LeadData, agent: Agent[LeadData, PersonalizedMessage]) -> PersonalizedMessage:
    """
    Generate a personalized WhatsApp opener for a given lead using the provided agent.

    Args:
        lead: LeadData instance containing lead details.
        agent: Agent used to generate the message.

    Returns:
        PersonalizedMessage: The result containing the phone number and message.
    """
    result = await agent.run("Generate a personalized WhatsApp opener for this lead.", deps=lead)
    return result.output

def main():
    """
    Main function to load environment variables, set up models and agent, and print a sample personalized message.
    """
    load_dotenv()
    config = Config(
        google_sheet_id=os.getenv("GOOGLE_SHEET_ID", ""),
        google_sheet_name=os.getenv("GOOGLE_SHEET_NAME", "test_sheets"),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini"),
    )
    if not config.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY is not set")
    logfire.configure(
        console=False,
    )
    logfire.instrument_pydantic_ai()
    model = OpenAIChatModel(
        config.openrouter_model,
        provider=OpenRouterProvider(api_key=config.openrouter_api_key),
    )
    prompt_path = Path(__file__).parent.parent / "prompts" / "dm.md"
    system_prompt = prompt_path.read_text()
    agent: Agent[LeadData, PersonalizedMessage] = Agent(
        model,
        deps_type=LeadData,
        output_type=PersonalizedMessage,
        system_prompt=system_prompt,
    )
    sample_lead = LeadData(
        owner_name="John Smith",
        business_summary="Acme Plumbing - Family-owned plumbing business serving London area for 15 years",
        review_summary="Great service, very professional. Customers consistently rate 5 stars for reliability and quality work.",
    )
    result = asyncio.run(personalize_lead(sample_lead, agent))
    print(f"Phone: {result.phone_number}")
    print(f"Message: {result.dm_opener}")

if __name__ == "__main__":
    main()
