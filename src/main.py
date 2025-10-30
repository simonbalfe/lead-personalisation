import asyncio
import logging
import os
from pathlib import Path

import gspread
from apify_client import ApifyClient
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openrouter import OpenRouterProvider


def load_prompt(filename: str) -> str:
    prompts_dir = Path(__file__).parent.parent / "prompts"
    prompt_path = prompts_dir / filename
    return prompt_path.read_text().strip()


class Lead(BaseModel):
    id: str | None = None
    business: str | None = None
    website: str | None = None
    email: str | None = None
    phone: str | None = None
    instagram: str | None = None
    facebook: str | None = None
    linkedin: str | None = None
    address: str | None = None
    owner_name: str | None = None
    review_summary: str | None = None


class LeadPersonalization(BaseModel):
    id: str
    phone: str
    dm_opener: str


class PersonalizedMessage(BaseModel):
    dm_opener: str


class ReviewSummary(BaseModel):
    owner_name: str
    review_summary: str


class Review(BaseModel):
    title: str | None = None
    name: str | None = None
    text: str | None = None


class Config:
    def __init__(self) -> None:
        load_dotenv()
        self.google_sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
        self.google_sheet_name = os.getenv("GOOGLE_SHEET_NAME", "test_sheets")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.openrouter_model = os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini")
        self.apify_token = os.getenv("APIFY_TOKEN", "")

        for key, value in [
            ("OPENROUTER_API_KEY", self.openrouter_api_key),
            ("GOOGLE_SHEET_ID", self.google_sheet_id),
            ("APIFY_TOKEN", self.apify_token),
        ]:
            if not value:
                raise ValueError(f"{key} is not set in environment")


class ReviewFetcher:
    def __init__(self, api_token: str, max_reviews: int = 20, language: str = "en") -> None:
        self.client = ApifyClient(api_token)
        self.max_reviews = max_reviews
        self.language = language

    def fetch_reviews(self, place_ids: list[str]) -> list[list[Review]]:
        if not place_ids:
            raise ValueError("place_ids cannot be empty")

        run = self.client.actor("compass/google-maps-reviews-scraper").call(run_input={
            "placeIds": place_ids,
            "maxReviews": self.max_reviews,
            "language": self.language,
        })

        all_reviews = [
            Review(title=item.get("title", ""), name=item.get("name", ""), text=item.get("text", ""))
            for item in self.client.dataset(run["defaultDatasetId"]).iterate_items()
        ]

        return [
            all_reviews[i * self.max_reviews:(i + 1) * self.max_reviews]
            for i in range(len(place_ids))
        ]


class SheetsManager:
    def __init__(self, sheet_id: str, sheet_name: str, credentials_file: str = "credentials.json") -> None:
        self.sheet_id = sheet_id
        self.sheet_name = sheet_name

        if not Path(credentials_file).is_absolute():
            credentials_file = str(Path(__file__).parent.parent / credentials_file)

        creds = Credentials.from_service_account_file(
            credentials_file, scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        self.client = gspread.authorize(creds)

    def read_leads(self) -> list[Lead]:
        worksheet = self.client.open_by_key(self.sheet_id).worksheet(self.sheet_name)
        all_values = worksheet.get_all_values()

        if not all_values:
            return []

        headers, *data_rows = all_values

        return [
            Lead(**{headers[i].lower(): (row[i] if i < len(row) and row[i] else None) for i in range(len(headers))})
            for row in data_rows
        ]

    def get_processed_lead_ids(self) -> set[str]:
        worksheet = self.client.open_by_key(self.sheet_id).worksheet("outreach_personalisation")
        all_values = worksheet.get_all_values()

        if not all_values or len(all_values) < 2:
            return set()

        headers = all_values[0]
        id_col = next((i for i, h in enumerate(headers) if h.lower() == "id"), 0)

        return {
            row[id_col]
            for row in all_values[1:]
            if row and len(row) > id_col and row[id_col]
        }

    def write_personalization(self, personalization: LeadPersonalization) -> None:
        worksheet = self.client.open_by_key(self.sheet_id).worksheet("outreach_personalisation")
        all_values = worksheet.get_all_values()

        if not all_values:
            headers = ["ID", "Phone", "DM opener"]
            worksheet.append_row(headers)
            all_values = [headers]

        headers = all_values[0]
        id_col = next((i for i, h in enumerate(headers) if h.lower() == "id"), 0)

        existing_row = next(
            (idx for idx, row in enumerate(all_values[1:], start=2)
             if row and len(row) > id_col and row[id_col] == personalization.id),
            None
        )

        row_data = [
            personalization.id,
            personalization.phone,
            personalization.dm_opener,
        ]

        if existing_row:
            for col_idx, value in enumerate(row_data, start=1):
                worksheet.update_cell(existing_row, col_idx, value)
        else:
            worksheet.append_row(row_data)


class AIAgentManager:
    def __init__(self, api_key: str, model_name: str) -> None:
        model = OpenAIChatModel(model_name, provider=OpenRouterProvider(api_key=api_key))

        self.personalization_agent: Agent[None, PersonalizedMessage] = Agent(
            model, output_type=PersonalizedMessage, system_prompt=load_prompt("dm.md")
        )

        self.review_agent: Agent[None, ReviewSummary] = Agent(
            model, output_type=ReviewSummary, system_prompt=load_prompt("review_summary.md")
        )

    async def summarize_reviews(self, reviews: list[Review], business_name: str) -> ReviewSummary:
        review_texts = [
            f"Review {i + 1}: {review.text}"
            for i, review in enumerate(reviews[:5])
            if review.text
        ]

        if not review_texts:
            return ReviewSummary(owner_name="Unknown", review_summary="No reviews available")

        prompt = f"Business: {business_name}\n\nReviews:\n{'\n\n'.join(review_texts)}"
        result = await self.review_agent.run(prompt)
        return result.output

    async def generate_personalized_message(self, lead: Lead) -> PersonalizedMessage:
        lead_info = f"""Lead Information:
- Business Name: {lead.business or "Unknown"}
- Owner Name: {lead.owner_name or "Unknown"}
- Review Summary: {lead.review_summary or "No reviews available"}"""

        result = await self.personalization_agent.run(f"Generate a personalized WhatsApp opener for this lead.\n{lead_info}")
        return result.output


class LeadProcessor:
    def __init__(self, config: Config) -> None:
        self.sheets_manager = SheetsManager(config.google_sheet_id, config.google_sheet_name)
        self.review_fetcher = ReviewFetcher(config.apify_token, max_reviews=20)
        self.ai_manager = AIAgentManager(config.openrouter_api_key, config.openrouter_model)
        self.logger = logging.getLogger(__name__)

    async def enrich_lead_with_reviews(self, lead: Lead) -> Lead:
        if not lead.id:
            return lead

        reviews = self.review_fetcher.fetch_reviews([lead.id])[0] if lead.id else []

        if not reviews:
            return lead

        summary = await self.ai_manager.summarize_reviews(reviews, lead.business or "")

        return lead.model_copy(update={
            "owner_name": summary.owner_name,
            "review_summary": summary.review_summary,
        })

    async def process_lead(self, lead: Lead) -> None:
        enriched_lead = await self.enrich_lead_with_reviews(lead)
        personalized_message = await self.ai_manager.generate_personalized_message(enriched_lead)

        self.logger.info(f"Generated DM opener: {personalized_message.dm_opener}")

        if enriched_lead.id:
            self.sheets_manager.write_personalization(LeadPersonalization(
                id=enriched_lead.id,
                phone=enriched_lead.phone or "",
                dm_opener=personalized_message.dm_opener,
            ))

    async def process_multiple_leads(self, max_leads: int | None = None) -> None:
        processed_ids = self.sheets_manager.get_processed_lead_ids()

        leads = self.sheets_manager.read_leads()

        if not leads:
            raise ValueError("No leads found in Google Sheets")

        unprocessed_leads = [lead for lead in leads if lead.id and lead.id not in processed_ids]

        if not unprocessed_leads:
            self.logger.info("No new leads to process, all leads have already been personalized")
            return

        leads_to_process = unprocessed_leads if max_leads is None else unprocessed_leads[:max_leads]

        self.logger.info(f"Found {len(unprocessed_leads)} unprocessed leads out of {len(leads)} total leads")
        self.logger.info(f"Processing {len(leads_to_process)} leads")

        for lead in leads_to_process:
            await self.process_lead(lead)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    logging.getLogger("apify_client").setLevel(logging.WARNING)
    logging.getLogger("apify").setLevel(logging.WARNING)

    try:
        asyncio.run(LeadProcessor(Config()).process_multiple_leads())
    except Exception as e:
        logging.getLogger(__name__).exception(f"Application failed with error: {e}")
        raise


if __name__ == "__main__":
    main()
